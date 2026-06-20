"""조문 임베딩 → Chroma 인덱싱.

Phase 2 완료기준: "유출 통지" 검색 시 관련 조문(제34조) 반환.
실행: python -m scripts.build_index   (프로젝트 루트에서)
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 대응

from app.config import settings
from app.loader import load_articles
from app.rag.embedder import embed_query, embed_texts
from app.rag.vectorstore import get_collection


def main() -> int:
    articles = load_articles(settings.data_path)
    print(f"조문 {len(articles)}개 로드 — 임베딩 모델: {settings.embedding_model}")

    col = get_collection(reset=True)
    embeddings = embed_texts([a.embedding_text for a in articles])
    col.add(
        ids=[a.id for a in articles],
        documents=[a.text for a in articles],
        embeddings=embeddings,
        metadatas=[
            {
                "id": a.id,
                "title": a.title,
                "category": a.category,
                "ref": a.ref,
                "source_url": a.source_url or "",
            }
            for a in articles
        ],
    )
    print(f"임베딩·저장 완료: {col.count()}개 → {settings.chroma_dir}")

    # --- 스모크 테스트: 검색이 동작하는지 ---
    for q in ("유출 통지", "동의 없이 수집", "과징금"):
        res = col.query(query_embeddings=[embed_query(q)], n_results=3)
        print(f"\n[테스트] '{q}' top-3:")
        for i, _id in enumerate(res["ids"][0]):
            meta = res["metadatas"][0][i]
            dist = res["distances"][0][i]
            print(f"  {i + 1}. {meta['id']} {meta['title']} (거리 {dist:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
