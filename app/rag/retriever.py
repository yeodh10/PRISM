"""검색기 — 벡터 검색(retrieve) + Hybrid 검색(retrieve_hybrid). 멀티 법령 대응.

Hybrid = 의미 기반 벡터 검색으로 핵심 조문을 찾고(Vector),
그 조문이 같은 법령 내에서 인용하는 연관 조문을 상호참조 그래프로 함께 묶어 반환(구조화).
`law` 인자로 특정 법령만 검색하거나(메타데이터 필터), None이면 전체 법령에서 검색.
"""
from dataclasses import dataclass, field

from app.config import settings
from app.rag.embedder import embed_query
from app.rag.relations import get_article_by_uid, linked_uids
from app.rag.vectorstore import get_collection


@dataclass
class RetrievedArticle:
    id: str
    title: str
    category: str
    ref: str
    text: str
    source_url: str
    score: float
    law: str = "개인정보보호법"
    kind: str = "검색"  # "검색"(벡터 적중) | "연관"(상호참조로 연결됨)
    linked_from: list[str] = field(default_factory=list)  # 이 조문을 인용한 검색 조문들(조문번호)

    @property
    def uid(self) -> str:
        return f"{self.law}:{self.id}"

    @property
    def citation(self) -> str:
        return f"{self.law} {self.id}({self.title})"

    def to_source_dict(self) -> dict:
        """API 응답용 출처 dict (본문 text 제외). 형상 정의 단일화."""
        return {
            "law": self.law,
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "ref": self.ref,
            "source_url": self.source_url,
            "score": round(self.score, 3),
            "kind": self.kind,
            "linked_from": self.linked_from,
        }


def available_laws() -> list[dict]:
    """인덱스에 존재하는 법령별 조문 수 (필터 UI 구성·law 파라미터 검증용). 조문 많은 순."""
    col = get_collection()
    if col.count() == 0:
        return []
    metas = col.get(include=["metadatas"]).get("metadatas", []) or []
    counts: dict[str, int] = {}
    for m in metas:
        law = (m or {}).get("law", "개인정보보호법")
        counts[law] = counts.get(law, 0) + 1
    return [{"law": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]


def retrieve(question: str, k: int | None = None, law: str | None = None) -> list[RetrievedArticle]:
    """질문과 가장 가까운 조문 k개 (벡터 검색). law 지정 시 해당 법령만. 인덱스 비면 빈 리스트."""
    k = k or settings.top_k
    col = get_collection()
    if col.count() == 0:
        return []
    where = {"law": law} if law else None
    res = col.query(query_embeddings=[embed_query(question)], n_results=k, where=where)
    ids = res["ids"][0]
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]

    out: list[RetrievedArticle] = []
    for i in range(len(ids)):
        m = metas[i]
        out.append(
            RetrievedArticle(
                law=m.get("law", "개인정보보호법"),
                id=m.get("id", ids[i]),
                title=m.get("title", ""),
                category=m.get("category", ""),
                ref=m.get("ref", "개인정보 보호법"),
                text=docs[i],
                source_url=m.get("source_url", ""),
                # 코사인 거리 [0,2] → 유사도가 음수가 되지 않도록 [0,1]로 클램프
                score=max(0.0, 1.0 - dists[i]),
                kind="검색",
            )
        )
    return out


def retrieve_hybrid(
    question: str, k: int | None = None, max_linked: int = 4, law: str | None = None
) -> list[RetrievedArticle]:
    """벡터 검색 결과 + 그 조문이 (같은 법령 내에서) 인용하는 연관 조문을 묶어 반환.

    연관 조문은 '인용한 검색 조문 수'가 많은 순으로 우선해 max_linked개만 채택.
    """
    primary = retrieve(question, k, law)
    if not primary:
        return []
    primary_uids = {a.uid for a in primary}

    linked: dict[str, RetrievedArticle] = {}
    for p in primary:
        for luid in linked_uids(p.uid):
            if luid in primary_uids:  # 이미 검색에 잡힌 건 연관으로 중복 추가 안 함
                continue
            if luid in linked:
                linked[luid].linked_from.append(p.id)
                continue
            art = get_article_by_uid(luid)
            if art is None:
                continue
            linked[luid] = RetrievedArticle(
                law=art.law,
                id=art.id,
                title=art.title,
                category=art.category,
                ref=art.ref,
                text=art.text,
                source_url=art.source_url or "",
                score=0.0,
                kind="연관",
                linked_from=[p.id],
            )

    ordered = sorted(linked.values(), key=lambda a: len(a.linked_from), reverse=True)
    return primary + ordered[:max_linked]
