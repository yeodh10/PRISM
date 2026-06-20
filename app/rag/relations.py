"""조문 상호참조 그래프 (Hybrid RAG의 '구조화' 축) — 멀티 법령 대응.

각 조문 본문에는 같은 법령 내 다른 조문 인용("제15조제1항" 등)이 들어 있다.
이 인용을 파싱해 '조문 → 인용 조문' 방향 그래프(법령 내부)를 만들고, 검색 시
연관 조문을 함께 묶어 반환한다. (Vector + 구조화 = Hybrid)

법령이 여러 개이므로 키는 `uid = 법령:조문`(예: 개인정보보호법:제15조).
「외부 법령」 인용(「전자정부법」 제2조 등)은 마스킹해 내부 참조 오탐을 막는다.
(크로스-법령 연결은 안전성을 위해 현재 미구현 — 같은 법령 내부 참조만.)
"""
import re
from functools import lru_cache

from app.loader import load_articles
from app.models import Article

# "제15조", "제28조의2" 같은 조문 참조 패턴
_REF = re.compile(r"제(\d+)조(?:의(\d+))?")

# 「외부 법령명」 뒤로 이어지는 조·항·호 참조 구간 → 그래프에서 제외(법령 내부 참조만 사용).
_EXTERNAL = re.compile(
    r"「[^」]*」\s*(?:제\d+조(?:의\d+)?(?:제\d+[항호목])*[\s·ㆍ,]*)+"
)


def _canonical(jo: str, ui: str | None) -> str:
    return f"제{jo}조의{ui}" if ui else f"제{jo}조"


@lru_cache(maxsize=1)
def articles_by_uid() -> dict[str, Article]:
    return {a.uid: a for a in load_articles()}


@lru_cache(maxsize=1)
def reference_graph() -> dict[str, list[str]]:
    """조문 uid → 같은 법령 내에서 인용하는 조문 uid 목록(외부 「」 법령 인용 제외)."""
    by_uid = articles_by_uid()
    uids = set(by_uid)
    graph: dict[str, list[str]] = {}
    for art in by_uid.values():
        masked = _EXTERNAL.sub(" ", art.text)  # 외부 법령 인용 구간 먼저 제거
        refs: list[str] = []
        for m in _REF.finditer(masked):
            ruid = f"{art.law}:{_canonical(m.group(1), m.group(2))}"  # 같은 법령 내부
            if ruid in uids and ruid != art.uid and ruid not in refs:
                refs.append(ruid)
        graph[art.uid] = refs
    return graph


def linked_uids(article_uid: str) -> list[str]:
    """해당 조문(uid)이 같은 법령 내에서 인용하는 연관 조문 uid 목록."""
    return reference_graph().get(article_uid, [])


def get_article_by_uid(uid: str) -> Article | None:
    return articles_by_uid().get(uid)
