"""조문 상호참조 그래프 (Hybrid RAG의 '구조화' 축) — 멀티 법령 대응.

각 조문 본문에는 같은 법령 내 다른 조문 인용("제15조제1항" 등)이 들어 있다.
이 인용을 파싱해 '조문 → 인용 조문' 방향 그래프(법령 내부)를 만들고, 검색 시
연관 조문을 함께 묶어 반환한다. (Vector + 구조화 = Hybrid)

법령이 여러 개이므로 키는 `uid = 법령:조문`(예: 개인정보보호법:제15조).

세 종류의 간선을 만든다:
1) 법령 내부 참조 — 본문의 bare "제15조" 등(같은 법령). 「외부 법령」 인용은 마스킹해 오탐 방지.
2) 크로스-법령 참조 — 「정식 법령명」 제N조 인용에서, 그 법령이 **우리 데이터에 있는 법** 중
   하나이고 대상 조문도 보유 중이면 연결(예: 신용정보법 제40조 → 정보통신망법 제50조 "준용").
   우리가 보유하지 않은 외부법(「전자정부법」 등)은 여전히 연결하지 않는다.
3) 법↔시행령 참조 — 시행령(law가 "… 시행령") 본문의 'bare 법 제N조'는 모법(母法) 조문 인용이다.
   시행령→모법 간선과 함께 **역방향(모법 조문 → 그 조문을 구체화한 시행령 조문)** 간선도 추가해,
   '법 조문을 조회하면 위임된 시행령 세부기준이 함께 표면화'되도록 한다.
"""
import re
from functools import lru_cache

from app.loader import load_articles
from app.models import Article

# "제15조", "제28조의2" 같은 조문 참조 패턴
_REF = re.compile(r"제(\d+)조(?:의(\d+))?")

# 「외부 법령명」 뒤로 이어지는 조·항·호 참조 구간 → 내부 참조 추출 시 제외(오탐 방지).
_EXTERNAL = re.compile(
    r"「[^」]*」\s*(?:제\d+조(?:의\d+)?(?:제\d+[항호목])*[\s·ㆍ,]*)+"
)

# 「정식 법령명」 제N조(의M) — 크로스-법령 인용 추출(법명이 우리 데이터에 있을 때만 연결).
_EXT_REF = re.compile(r"「([^」]+)」\s*제(\d+)조(?:의(\d+))?")

# 시행령 본문의 'bare 법 제N조' = 모법 조문 인용(시행령에서만 모법으로 해석). 「…법」 형태는 안 잡힘.
_PARENT_REF = re.compile(r"법\s*제(\d+)조(?:의(\d+))?")
_DECREE_SUFFIX = " 시행령"


def _canonical(jo: str, ui: str | None) -> str:
    return f"제{jo}조의{ui}" if ui else f"제{jo}조"


def _parent_law(law: str) -> str | None:
    """'개인정보보호법 시행령' → '개인정보보호법'. 시행령이 아니면 None."""
    return law[: -len(_DECREE_SUFFIX)] if law.endswith(_DECREE_SUFFIX) else None


@lru_cache(maxsize=1)
def articles_by_uid() -> dict[str, Article]:
    return {a.uid: a for a in load_articles()}


@lru_cache(maxsize=1)
def _law_by_ref() -> dict[str, str]:
    """정식 법령명(ref) → 약칭(law). 공백 제거 정규화로 「개인정보 보호법」↔약칭 미세차 흡수."""
    return {a.ref.replace(" ", ""): a.law for a in load_articles()}


@lru_cache(maxsize=1)
def reference_graph() -> dict[str, list[str]]:
    """조문 uid → 연관 조문 uid 목록(법령 내부 + 크로스-법령 + 법↔시행령 양방향)."""
    by_uid = articles_by_uid()
    uids = set(by_uid)
    law_by_ref = _law_by_ref()
    graph: dict[str, list[str]] = {}
    for art in by_uid.values():
        refs: list[str] = []
        text_for_intra = art.text
        # (0) 시행령: 본문의 'bare 법 제N조' → 모법 조문 인용(시행령→모법)
        parent = _parent_law(art.law)
        if parent:
            for m in _PARENT_REF.finditer(art.text):
                puid = f"{parent}:{_canonical(m.group(1), m.group(2))}"
                if puid in uids and puid not in refs:
                    refs.append(puid)
            text_for_intra = _PARENT_REF.sub(" ", art.text)  # '법 제N조' 마스킹(시행령 내부참조 오탐 방지)
        # (1) 크로스-법령: 「정식법령명」 제N조 → 우리가 보유한 타 법령 조문이면 연결(원문에서)
        for m in _EXT_REF.finditer(art.text):
            target_law = law_by_ref.get(m.group(1).replace(" ", ""))
            if not target_law or target_law == art.law:
                continue  # 모르는 외부법이거나, 같은 법령(내부참조는 아래에서 처리)
            tuid = f"{target_law}:{_canonical(m.group(2), m.group(3))}"
            if tuid in uids and tuid not in refs:
                refs.append(tuid)
        # (2) 법령 내부: 외부 「」 인용 구간을 마스킹한 뒤 bare 제N조만 추출
        masked = _EXTERNAL.sub(" ", text_for_intra)
        for m in _REF.finditer(masked):
            ruid = f"{art.law}:{_canonical(m.group(1), m.group(2))}"
            if ruid in uids and ruid != art.uid and ruid not in refs:
                refs.append(ruid)
        graph[art.uid] = refs
    # (3) 역방향 시행령 간선: 모법 조문 → 그 조문을 구체화하는 시행령 조문(법 조회 시 시행령 표면화)
    for art in by_uid.values():
        parent = _parent_law(art.law)
        if not parent:
            continue
        for t in graph.get(art.uid, []):
            if t.startswith(parent + ":"):  # 시행령→모법 간선의 역방향
                graph.setdefault(t, [])
                if art.uid not in graph[t]:
                    graph[t].append(art.uid)
    return graph


def linked_uids(article_uid: str) -> list[str]:
    """해당 조문(uid)의 연관 조문 uid 목록(내부 참조·크로스-법령·법↔시행령)."""
    return reference_graph().get(article_uid, [])


def get_article_by_uid(uid: str) -> Article | None:
    return articles_by_uid().get(uid)
