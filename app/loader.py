"""조문 데이터 로더 — 인덱싱·앱에서 공용으로 사용."""
import json
from pathlib import Path

from app.models import Article


def load_articles(path: str) -> list[Article]:
    """pipa.json → Article 리스트. 형식 오류 시 예외."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"데이터 파일 없음: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("pipa.json 최상위는 JSON 배열이어야 함")
    return [Article(**item) for item in raw]
