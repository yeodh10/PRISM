"""data/*.json(멀티 법령) 로드·검증 → 리포트.

조문번호는 법령마다 겹칠 수 있으므로 중복 검사는 uid(법령:조문) 기준.
실행: python -m scripts.validate_data   (프로젝트 루트에서)
"""
import sys

sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 대응

from collections import Counter

from app.loader import load_articles


def main() -> int:
    try:
        arts = load_articles()  # data/*.json 전체(미검증·빈 본문 항목은 로더가 제외)
    except Exception as e:
        print(f"[FAIL] 데이터 로드 실패: {e}")
        return 1
    if not arts:
        print("[FAIL] 로드된 조문이 0개입니다.")
        return 1

    print("=== PRISM 데이터 검증 (멀티 법령) ===")
    print(f"총 조문 수: {len(arts)}")

    laws = Counter(a.law for a in arts)
    print("\n법령별 조문 수:")
    for law, n in laws.most_common():
        print(f"  - {law}: {n}")

    errors: list[str] = []
    # uid(법령:조문) 중복 — 같은 법령 내 같은 조문번호 중복만 오류(법령 간 겹침은 정상)
    for uid, n in Counter(a.uid for a in arts).items():
        if n > 1:
            errors.append(f"중복 uid: {uid} ({n}회)")
    # 본문 길이/필수값
    for a in arts:
        if len(a.text.strip()) < 10:
            errors.append(f"{a.uid}: text 너무 짧음({len(a.text)}자)")
        if not (a.title and a.category and a.ref):
            errors.append(f"{a.uid}: 빈 필드(title/category/ref)")

    cats = Counter(a.category for a in arts)
    print(f"\n분류 {len(cats)}종: {', '.join(c for c, _ in cats.most_common())}")

    if errors:
        print(f"\n[FAIL] 오류 {len(errors)}건:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"\n[OK] 검증 통과 — {len(laws)}개 법령, 조문 {len(arts)}개, 분류 {len(cats)}종")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
