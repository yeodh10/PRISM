"""어휘 검색(BM25) — 질문과 조문이 같은 낱말을 얼마나 공유하는지로 순위를 매긴다.

임베딩 검색은 뜻이 비슷한 조문을 찾지만, 법률 질문에는 '통신사실확인자료'·'과태료'·'증거'처럼
조문에 그대로 나오는 용어가 많다. 이런 질문은 낱말 일치가 더 정확하다. 형태소 분석기 없이
글자 2-gram으로 토큰화한다(조사·어미가 붙어도 어간 2-gram은 일치) — 추가 의존성 없음.
"""
import math
import re
from collections import Counter
from functools import lru_cache

from app.rag.relations import articles_by_uid

_RUN = re.compile(r"[가-힣A-Za-z0-9]+")
_K1, _B = 1.5, 0.75  # BM25 표준값


def tokenize(text: str) -> list[str]:
    """한글·영숫자 덩어리별 글자 2-gram(2자 이하 덩어리는 그대로)."""
    out: list[str] = []
    for run in _RUN.findall(text.lower()):
        out.extend([run] if len(run) <= 2 else [run[i : i + 2] for i in range(len(run) - 1)])
    return out


class LexicalIndex:
    """문서(uid → 텍스트) 집합에 대한 BM25 역색인."""

    def __init__(self, docs: dict[str, str]):
        self.uids = list(docs)
        counts = [Counter(tokenize(docs[u])) for u in self.uids]
        self.lengths = [sum(c.values()) for c in counts]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for i, c in enumerate(counts):
            for tok, tf in c.items():
                self.postings.setdefault(tok, []).append((i, tf))
        n = len(self.uids)
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}

    def search(self, query: str, n: int, allow=None) -> list[str]:
        """query와 낱말이 겹치는 문서 uid를 BM25 점수 순으로 최대 n개. allow(uid→bool)로 범위 제한."""
        scores: dict[int, float] = {}
        for tok in set(tokenize(query)):
            for i, tf in self.postings.get(tok, ()):
                norm = tf + _K1 * (1 - _B + _B * self.lengths[i] / self.avg_len)
                scores[i] = scores.get(i, 0.0) + self.idf[tok] * tf * (_K1 + 1) / norm
        ranked = sorted(scores, key=lambda i: (-scores[i], i))
        uids = (self.uids[i] for i in ranked)
        return [u for u in uids if allow is None or allow(u)][:n]


@lru_cache(maxsize=1)
def _index() -> LexicalIndex:
    # 법령명·제목을 본문 앞에 붙인다(제목은 두 번 — 제목의 낱말에 가중치)
    return LexicalIndex({uid: f"{a.law} {a.title} {a.title} {a.text}" for uid, a in articles_by_uid().items()})


def lexical_search(question: str, n: int, law: str | None = None) -> list[str]:
    """질문과 낱말이 겹치는 조문 uid 목록(BM25 순). law 지정 시 해당 법령만."""
    allow = (lambda uid: uid.startswith(f"{law}:")) if law else None
    return _index().search(question, n, allow)
