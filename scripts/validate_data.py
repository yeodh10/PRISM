"""data/pipa.json 로드·검증 → 리포트.

Phase 1 완료기준: 조문 로드 + 누락 리포트.
실행: python -m scripts.validate_data   (프로젝트 루트에서)
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 대응

import json
from collections import Counter
from pathlib import Path

from app.config import settings

REQUIRED = ("id", "title", "category", "text", "ref")


def main() -> int:
    p = Path(settings.data_path)
    if not p.exists():
        print(f"[FAIL] 데이터 파일 없음: {p}")
        return 1
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[FAIL] JSON 파싱 실패: {e}")
        return 1
    if not isinstance(data, list) or not data:
        print("[FAIL] 최상위가 '비어있지 않은 배열'이 아님")
        return 1

    print(f"=== PRISM 데이터 검증: {p} ===")
    print(f"총 조문 수: {len(data)}")

    errors: list[str] = []
    warns: list[str] = []

    for i, item in enumerate(data):
        if not isinstance(item, dict):
            errors.append(f"[index {i}]: 객체(dict)가 아님")
            continue
        ident = item.get("id") or f"[index {i}]"
        for f in REQUIRED:
            v = item.get(f)
            if not isinstance(v, str) or not v.strip():
                errors.append(f"{ident}: 빈/누락 필드 '{f}'")
        text = item.get("text", "")
        if isinstance(text, str) and 0 < len(text) < 10:
            errors.append(f"{ident}: text 너무 짧음({len(text)}자)")
        if not item.get("source_url"):
            warns.append(f"{ident}: source_url 없음")

    # 중복 id
    ids = [i.get("id") for i in data if isinstance(i, dict) and i.get("id")]
    for d, n in Counter(ids).items():
        if n > 1:
            errors.append(f"중복 id: {d} ({n}회)")

    # 분류 분포
    cats = Counter(i.get("category", "?") for i in data if isinstance(i, dict))
    print("\n분류 분포:")
    for c, n in cats.most_common():
        print(f"  - {c}: {n}")

    # 조문 목록
    print("\n조문 목록:")
    for i in data:
        if isinstance(i, dict):
            t = i.get("text", "") or ""
            print(f"  {i.get('id', '?')} {i.get('title', '?')} ({len(t)}자)")

    if warns:
        print(f"\n[WARN] 경고 {len(warns)}건:")
        for w in warns:
            print(f"  - {w}")
    if errors:
        print(f"\n[FAIL] 오류 {len(errors)}건:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"\n[OK] 검증 통과 — 조문 {len(data)}개, 분류 {len(cats)}종")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
