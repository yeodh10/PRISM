"""검색기 — 융합 검색(retrieve) + Hybrid 검색(retrieve_hybrid). 멀티 법령 대응.

retrieve는 세 검색기의 순위를 융합(RRF)한다:
  ① 조문 단위 벡터 — 조문 전체의 주제  ② 항 단위 조각 벡터 — 긴 조문의 뒤쪽 항까지
  ③ BM25 낱말 일치 — 조문에 그대로 나오는 법률 용어
Hybrid = 이렇게 찾은 핵심 조문에, 그 조문이 인용하는 연관 조문을 상호참조 그래프로 함께 묶어 반환(구조화).
`law` 인자로 특정 법령만 검색하거나(메타데이터 필터), None이면 전체 법령에서 검색.
"""
from dataclasses import dataclass, field

from app.config import settings
from app.rag.embedder import embed_query
from app.rag.lexical import lexical_search
from app.rag.relations import articles_by_uid, get_article_by_uid, linked_uids
from app.rag.vectorstore import get_collection

_DEPTH = 40  # 검색기마다 융합에 넣는 후보 조문 수
_CHUNK_DEPTH = 80  # 조각 검색 깊이 — 여러 조각이 한 조문에 속하므로 조문 수보다 넉넉히
_RRF_K = 60  # RRF 상수(관례값). 클수록 상위 순위 차이가 덜 반영된다


@dataclass
class RetrievedArticle:
    id: str
    title: str
    category: str
    ref: str
    text: str
    source_url: str
    score: float  # 융합 점수 0~1 (세 검색기 모두 1위면 1). 연관 조문은 0
    law: str = "개인정보보호법"
    kind: str = "검색"  # "검색"(융합 검색 적중) | "연관"(상호참조로 연결됨)
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


def rrf_fuse(rankings: list[list[str]], k: int = _RRF_K) -> list[tuple[str, float]]:
    """순위 목록 여러 개를 역순위 합(Reciprocal Rank Fusion)으로 융합 → (uid, 점수) 내림차순.

    점수가 아니라 순위만 쓰므로 척도가 다른 검색기(코사인 유사도·BM25)를 그대로 합칠 수 있다.
    점수는 '모든 목록에서 1위'를 1로 정규화한 값.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for pos, uid in enumerate(ranking):
            scores[uid] = scores.get(uid, 0.0) + 1.0 / (k + pos + 1)
    best = len(rankings) / (k + 1)
    return sorted(((uid, s / best) for uid, s in scores.items()), key=lambda x: (-x[1], x[0]))


def _dense_articles(query_vec: list[float], where: dict | None, n: int) -> list[str]:
    """조문 단위 벡터 검색 → uid 목록(가까운 순)."""
    col = get_collection()
    res = col.query(query_embeddings=[query_vec], n_results=min(n, col.count()), where=where, include=["distances"])
    return res["ids"][0]


def _dense_chunks(query_vec: list[float], where: dict | None, n: int) -> list[str]:
    """항 단위 조각 벡터 검색 → 조각이 속한 조문 uid 목록(가장 가까운 조각 순, 중복 제거)."""
    col = get_collection(chunks=True)
    total = col.count()
    if total == 0:  # 조각 색인이 없는 옛 인덱스 — 나머지 검색기만으로 동작
        return []
    res = col.query(query_embeddings=[query_vec], n_results=min(n, total), where=where, include=["metadatas"])
    uids: list[str] = []
    for m in res["metadatas"][0]:
        if m["uid"] not in uids:
            uids.append(m["uid"])
    return uids


def retrieve(question: str, k: int | None = None, law: str | None = None) -> list[RetrievedArticle]:
    """질문과 가장 관련 깊은 조문 k개 (세 검색기 융합). law 지정 시 해당 법령만. 인덱스 비면 빈 리스트."""
    k = k or settings.top_k
    if get_collection().count() == 0:
        return []
    query_vec = embed_query(question)
    where = {"law": law} if law else None
    fused = rrf_fuse(
        [
            _dense_articles(query_vec, where, _DEPTH),
            _dense_chunks(query_vec, where, _CHUNK_DEPTH),
            lexical_search(question, _DEPTH, law),
        ]
    )
    by_uid = articles_by_uid()
    out: list[RetrievedArticle] = []
    for uid, score in fused:
        art = by_uid.get(uid)
        if art is None:  # 색인에는 있지만 데이터에서 빠진 조문(인덱스가 오래됨)
            continue
        out.append(
            RetrievedArticle(
                law=art.law,
                id=art.id,
                title=art.title,
                category=art.category,
                ref=art.ref,
                text=art.text,
                source_url=art.source_url or "",
                score=score,
                kind="검색",
            )
        )
        if len(out) == k:
            break
    return out


def retrieve_hybrid(
    question: str, k: int | None = None, max_linked: int = 4, law: str | None = None
) -> list[RetrievedArticle]:
    """융합 검색 결과 + 그 조문이 인용하는 연관 조문(법령 내부·크로스-법령·법↔시행령)을 묶어 반환.

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
