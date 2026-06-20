"""조문 상호참조 그래프 (Hybrid RAG의 '구조화' 축).

각 조문 본문에는 다른 조문 인용("제15조제1항", "제28조의8제1항" 등)이 들어 있다.
이 인용을 파싱해 '조문 → 인용하는 조문' 방향 그래프를 만들고, 검색 시
연관 조문을 함께 묶어 반환하는 데 사용한다. (Vector + 구조화 = Hybrid)
"""
import re
from functools import lru_cache

from app.config import settings
from app.loader import load_articles
from app.models import Article

# "제15조", "제28조의2" 같은 조문 참조 패턴
_REF = re.compile(r"제(\d+)조(?:의(\d+))?")

# 「외부 법령명」 뒤로 이어지는 조·항·호 참조 구간 → 그래프에서 제외(PIPA 내부 참조만 사용).
# 연쇄 인용("「전자정부법」 제2조 및 제15조")까지 통째로 마스킹해 오탐 방지.
_EXTERNAL = re.compile(
    r"「[^」]*」\s*(?:제\d+조(?:의\d+)?(?:제\d+[항호목])*[\s·ㆍ,]*)+"
)


def _canonical(jo: str, ui: str | None) -> str:
    return f"제{jo}조의{ui}" if ui else f"제{jo}조"


@lru_cache(maxsize=1)
def articles_by_id() -> dict[str, Article]:
    return {a.id: a for a in load_articles(settings.data_path)}


@lru_cache(maxsize=1)
def reference_graph() -> dict[str, list[str]]:
    """조문 id → 본문에서 인용하는 (우리 데이터셋 내) 조문 id 목록."""
    by_id = articles_by_id()
    ids = set(by_id)
    graph: dict[str, list[str]] = {}
    for art in by_id.values():
        # 외부 법령 인용 구간을 먼저 마스킹한 뒤 내부 참조만 추출
        masked = _EXTERNAL.sub(" ", art.text)
        refs: list[str] = []
        for m in _REF.finditer(masked):
            rid = _canonical(m.group(1), m.group(2))
            if rid in ids and rid != art.id and rid not in refs:
                refs.append(rid)
        graph[art.id] = refs
    return graph


def linked_ids(article_id: str) -> list[str]:
    """해당 조문이 인용하는 (데이터셋 내) 연관 조문 id."""
    return reference_graph().get(article_id, [])


def get_article(article_id: str) -> Article | None:
    return articles_by_id().get(article_id)
