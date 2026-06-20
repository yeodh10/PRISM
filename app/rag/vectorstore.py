"""Chroma 벡터스토어 헬퍼 (영구 저장)."""
from app.config import settings


def get_client():
    import chromadb

    return chromadb.PersistentClient(path=settings.chroma_dir)


def get_collection(reset: bool = False):
    """컬렉션 반환. reset=True 면 기존 컬렉션 삭제 후 재생성(재인덱싱용).

    코사인 거리(hnsw:space=cosine) 사용.
    """
    client = get_client()
    if reset:
        try:
            client.delete_collection(settings.collection_name)
        except Exception:
            pass  # 없으면 무시
    return client.get_or_create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
    )
