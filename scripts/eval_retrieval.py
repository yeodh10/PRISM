"""검색 정확도 평가 — recall@1, recall@k, MRR (멀티 법령, law-aware).

LLM을 호출하지 않는다(질문 임베딩 → 벡터 top-k 검색만). 정답은 "가장 관련 깊은 단일 (법령, 조문)".
같은 조문번호가 여러 법령에 존재하므로(예: 제15조는 개인정보보호법·신용정보법·위치정보법에 모두 있음)
정답 일치는 반드시 (law, id) 쌍으로 판정한다 — id만 비교하면 다른 법령의 동일 번호를 오답 처리/오정답 처리할 수 있다.
법령 필터 없이(real-world: 사용자가 법을 미리 고르지 않음) 전체에서 검색해 올바른 법령의 조문이 떠오르는지를 측정한다.
실행: python -m scripts.eval_retrieval
"""
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app.rag.retriever import retrieve  # noqa: E402


def run(k: int = 4) -> dict:
    data = json.loads(pathlib.Path("eval/eval_set.json").read_text(encoding="utf-8"))
    n = len(data)
    r1 = rk = 0
    mrr = 0.0
    misses = []
    per_law: dict[str, list[int]] = {}  # law -> [hit_at_1, total]
    for it in data:
        q, expect, law = it["q"], it["expect"], it.get("law")
        results = retrieve(q, k)
        # (law, id) 정답 일치 — law가 없으면(레거시) id만 비교
        hit = next(
            (i for i, a in enumerate(results) if a.id == expect and (law is None or a.law == law)),
            None,
        )
        bucket = per_law.setdefault(law or "(미지정)", [0, 0])
        bucket[1] += 1
        if hit == 0:
            r1 += 1
            bucket[0] += 1
        if hit is not None:
            rk += 1
            mrr += 1.0 / (hit + 1)
        else:
            got = [f"{a.law} {a.id}" for a in results]
            misses.append((f"{law or ''} {expect}".strip(), q, got))

    print(f"평가 문항 N={n} (멀티 법령 · (법령,조문) 정답 기준 · 필터 없이 전체 검색)")
    print(f"  recall@1  = {r1/n:.3f}  ({r1}/{n})")
    print(f"  recall@{k}  = {rk/n:.3f}  ({rk}/{n})")
    print(f"  MRR       = {mrr/n:.3f}")
    print("\n법령별 recall@1:")
    for law, (h, t) in sorted(per_law.items(), key=lambda kv: -kv[1][1]):
        print(f"  {law:<10} {h}/{t}  ({h/t:.3f})")
    if misses:
        print(f"\n[miss {len(misses)}건 — top-{k}에 정답 (법령,조문) 없음]")
        for tgt, q, got in misses:
            print(f"  expect {tgt}  ·  '{q}'\n    got {got}")
    return {"n": n, "recall@1": round(r1 / n, 3), f"recall@{k}": round(rk / n, 3), "mrr": round(mrr / n, 3)}


if __name__ == "__main__":
    run()
