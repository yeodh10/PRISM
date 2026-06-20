"""한국어 SBERT 임베딩 (sentence-transformers, 로컬·무료).

[환경 메모] 이 PC는 Windows Smart App Control(Enforce)이 켜져 있어
scipy 1.15+의 컴파일 DLL(_cyutility)을 차단한다. sentence-transformers는
import 시 sklearn→scipy를 끌어오므로, requirements.txt에서 scipy<1.15로
고정(1.14.x)해 차단을 회피한다.

normalize=True 로 L2 정규화 → 코사인 유사도(=내적)로 검색.
모델은 무거우니 1회만 로드(캐시).
"""
from functools import lru_cache

from app.config import settings


@lru_cache(maxsize=1)
def get_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def embed_texts(texts: list[str]) -> list[list[float]]:
    """여러 문서를 임베딩(L2 정규화)."""
    model = get_embedder()
    vecs = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    return vecs.tolist()


def embed_query(text: str) -> list[float]:
    """단일 질의 임베딩."""
    return embed_texts([text])[0]
