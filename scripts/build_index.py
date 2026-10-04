"""조문 임베딩 → Chroma 인덱싱 (조문 단위 + 항 단위 조각).

Phase 2 완료기준: "유출 통지" 검색 시 관련 조문(제34조) 반환.
실행: python -m scripts.build_index   (프로젝트 루트에서)
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 대응

from app.config import settings
from app.loader import load_articles
from app.rag.chunking import split_chunks
from app.rag.embedder import embed_texts
from app.rag.vectorstore import get_collection


def _meta(a) -> dict:
    return {
        "law": a.law,
        "id": a.id,
        "title": a.title,
        "category": a.category,
        "ref": a.ref,
        "source_url": a.source_url or "",
    }


def main() -> int:
    from collections import Counter

    articles = load_articles()  # data/*.json 전체(멀티 법령)
    laws = Counter(a.law for a in articles)
    print(f"조문 {len(articles)}개 로드 {dict(laws)} — 임베딩 모델: {settings.embedding_model}")

    # ① 조문 단위 — 조문 전체의 주제를 담는 벡터
    col = get_collection(reset=True)
    col.add(
        ids=[a.uid for a in articles],  # 법령:조문 (법령 간 ID 충돌 방지)
        documents=[a.text for a in articles],
        embeddings=embed_texts([a.embedding_text for a in articles]),
        metadatas=[_meta(a) for a in articles],
    )

    # ② 항 단위 조각 — 긴 조문의 뒤쪽 항까지 검색되도록. 각 조각은 uid로 소속 조문을 가리킨다
    chunks = [(a, i, c) for a in articles for i, c in enumerate(split_chunks(a.text))]
    chunk_col = get_collection(reset=True, chunks=True)
    chunk_col.add(
        ids=[f"{a.uid}#{i}" for a, i, _ in chunks],
        documents=[c for _, _, c in chunks],
        embeddings=embed_texts([f"{a.heading}\n{c}" for a, _, c in chunks]),
        metadatas=[{"uid": a.uid, "law": a.law} for a, _, _ in chunks],
    )
    print(f"임베딩·저장 완료: 조문 {col.count()}개 + 조각 {chunk_col.count()}개 → {settings.chroma_dir}")

    # --- 스모크 테스트: 실제 검색 경로(세 검색기 융합)가 동작하는지 ---
    from app.rag.retriever import retrieve

    for q in ("유출 통지", "동의 없이 수집", "과징금"):
        print(f"\n[테스트] '{q}' top-3:")
        for i, a in enumerate(retrieve(q, 3)):
            print(f"  {i + 1}. {a.law} {a.id} {a.title} (융합 점수 {a.score:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
