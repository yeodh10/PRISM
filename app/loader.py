"""조문 데이터 로더 — 여러 법령 JSON(data/*.json)을 공용 로드. 인덱싱·앱·그래프에서 사용."""
import json
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.models import Article

VERSIONS_FILE = "_versions.json"  # 법령별 기준 시행본 — scripts.sync_laws --write가 기록


def _load_file(p: Path) -> list[Article]:
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{p.name} 최상위는 JSON 배열이어야 함")
    # 본문 없거나 UNVERIFIED 표시된 항목은 제외(절대원칙: 미검증 데이터는 색인하지 않음)
    return [
        Article(**item)
        for item in raw
        if item.get("text") and item.get("title") != "UNVERIFIED"
    ]


def load_articles(path: str | None = None) -> list[Article]:
    """단일 파일 경로면 그 파일만, 디렉터리/None이면 data_dir의 모든 *.json(법령별)을 로드.

    pipa.json 등 `law` 필드가 없는 항목은 모델 기본값(개인정보보호법)으로 처리된다.
    """
    if path and Path(path).is_file():
        return _load_file(Path(path))
    base = Path(path) if (path and Path(path).is_dir()) else Path(settings.data_dir)
    files = sorted(f for f in base.glob("*.json") if not f.name.startswith("_"))  # '_' 접두는 메타 파일
    if not files:
        raise FileNotFoundError(f"데이터 파일 없음: {base}/*.json")
    arts: list[Article] = []
    for f in files:
        arts.extend(_load_file(f))
    return arts


@lru_cache(maxsize=1)
def load_versions() -> dict[str, dict]:
    """법령 약칭 → 기준 시행본(effective·number 등). 조문 본문이 어느 시행본과 대조됐는지의 기록.

    파일이 없으면 빈 dict — 버전 표시는 부가 정보라 없어도 서비스는 동작한다.
    """
    p = Path(settings.data_dir) / VERSIONS_FILE
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))
