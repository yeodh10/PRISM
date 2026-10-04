"""Chroma 벡터스토어 헬퍼 (영구 저장).

컬렉션은 둘이다 — 조문 단위 벡터(기본)와 항 단위 조각 벡터(chunks=True). 조각 컬렉션의 각 항목은
메타데이터 `uid`로 자신이 속한 조문을 가리킨다.
"""
from app.config import settings

CHUNK_SUFFIX = "_chunks"


def get_client():
    import chromadb

    return chromadb.PersistentClient(path=settings.chroma_dir)


def get_collection(reset: bool = False, chunks: bool = False):
    """컬렉션 반환. reset=True 면 기존 컬렉션 삭제 후 재생성(재인덱싱용).

    코사인 거리(hnsw:space=cosine) 사용.
    """
    client = get_client()
    name = settings.collection_name + (CHUNK_SUFFIX if chunks else "")
    if reset:
        try:
            client.delete_collection(name)
        except Exception:
            pass  # 없으면 무시
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )
