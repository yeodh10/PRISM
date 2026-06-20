"""검색 정확도 평가 — recall@1, recall@k, MRR.

LLM을 호출하지 않는다(질문 임베딩 → 벡터 top-k 검색만). 정답은 "가장 관련 깊은 단일 조문".
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
    for it in data:
        q, expect = it["q"], it["expect"]
        ids = [a.id for a in retrieve(q, k)]
        if ids[:1] == [expect]:
            r1 += 1
        if expect in ids:
            rk += 1
            mrr += 1.0 / (ids.index(expect) + 1)
        else:
            misses.append((q, expect, ids))

    print(f"평가 문항 N={n}")
    print(f"  recall@1  = {r1/n:.3f}  ({r1}/{n})")
    print(f"  recall@{k}  = {rk/n:.3f}  ({rk}/{n})")
    print(f"  MRR       = {mrr/n:.3f}")
    if misses:
        print(f"\n[miss {len(misses)}건]")
        for q, e, ids in misses:
            print(f"  '{q}'\n    expect {e}  got {ids}")
    return {"n": n, "recall@1": round(r1 / n, 3), f"recall@{k}": round(rk / n, 3), "mrr": round(mrr / n, 3)}


if __name__ == "__main__":
    run()
