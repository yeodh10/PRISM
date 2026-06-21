"""조문 상호참조 그래프 (Hybrid RAG의 '구조화' 축) — 멀티 법령 대응.

각 조문 본문에는 같은 법령 내 다른 조문 인용("제15조제1항" 등)이 들어 있다.
이 인용을 파싱해 '조문 → 인용 조문' 방향 그래프(법령 내부)를 만들고, 검색 시
연관 조문을 함께 묶어 반환한다. (Vector + 구조화 = Hybrid)

법령이 여러 개이므로 키는 `uid = 법령:조문`(예: 개인정보보호법:제15조).

두 종류의 간선을 만든다:
1) 법령 내부 참조 — 본문의 bare "제15조" 등(같은 법령). 「외부 법령」 인용은 마스킹해 오탐 방지.
2) 크로스-법령 참조 — 「정식 법령명」 제N조 인용에서, 그 법령이 **우리 데이터에 있는 5개 법** 중
   하나이고 대상 조문도 보유 중이면 연결(예: 신용정보법 제40조 → 정보통신망법 제50조 "준용").
   우리가 보유하지 않은 외부법(「전자정부법」 등)은 여전히 연결하지 않는다.
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


def _canonical(jo: str, ui: str | None) -> str:
    return f"제{jo}조의{ui}" if ui else f"제{jo}조"


@lru_cache(maxsize=1)
def articles_by_uid() -> dict[str, Article]:
    return {a.uid: a for a in load_articles()}


@lru_cache(maxsize=1)
def _law_by_ref() -> dict[str, str]:
    """정식 법령명(ref) → 약칭(law). 공백 제거 정규화로 「개인정보 보호법」↔약칭 미세차 흡수."""
    return {a.ref.replace(" ", ""): a.law for a in load_articles()}


@lru_cache(maxsize=1)
def reference_graph() -> dict[str, list[str]]:
    """조문 uid → 인용 조문 uid 목록(법령 내부 참조 + 보유 중인 타 법령으로의 크로스-법령 참조)."""
    by_uid = articles_by_uid()
    uids = set(by_uid)
    law_by_ref = _law_by_ref()
    graph: dict[str, list[str]] = {}
    for art in by_uid.values():
        refs: list[str] = []
        # (1) 크로스-법령: 「정식법령명」 제N조 → 우리가 보유한 타 법령 조문이면 연결(마스킹 전 원문에서)
        for m in _EXT_REF.finditer(art.text):
            target_law = law_by_ref.get(m.group(1).replace(" ", ""))
            if not target_law or target_law == art.law:
                continue  # 모르는 외부법이거나, 같은 법령(내부참조는 아래에서 처리)
            tuid = f"{target_law}:{_canonical(m.group(2), m.group(3))}"
            if tuid in uids and tuid not in refs:
                refs.append(tuid)
        # (2) 법령 내부: 외부 「」 인용 구간을 마스킹한 뒤 bare 제N조만 추출
        masked = _EXTERNAL.sub(" ", art.text)
        for m in _REF.finditer(masked):
            ruid = f"{art.law}:{_canonical(m.group(1), m.group(2))}"
            if ruid in uids and ruid != art.uid and ruid not in refs:
                refs.append(ruid)
        graph[art.uid] = refs
    return graph


def linked_uids(article_uid: str) -> list[str]:
    """해당 조문(uid)이 같은 법령 내에서 인용하는 연관 조문 uid 목록."""
    return reference_graph().get(article_uid, [])


def get_article_by_uid(uid: str) -> Article | None:
    return articles_by_uid().get(uid)
