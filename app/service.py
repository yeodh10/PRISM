"""RAG 오케스트레이션: 질문 → Hybrid 검색 → 생성 → {answer, sources}.

답변 생성(LLM)이 실패해도 검색은 이미 끝나 있다. 그래서 오류만 돌려주는 대신 '검색 전용'으로
물러나 관련 조문 원문을 그대로 보여준다(원문 그대로이므로 지어낼 여지가 없다).
"""
import logging
from datetime import datetime, timezone

import anthropic

from app.rag.generator import DISCLAIMER, generate_answer
from app.rag.retriever import RetrievedArticle, retrieve_hybrid

logger = logging.getLogger("prism")

# 검색 전용 응답에 싣는 본문 상한(직접 검색된 조문, 순위별). 1순위는 넉넉히, 나머지는 앞부분만 —
# 넘으면 줄 단위로 자르고 원문 링크로 안내한다.
_EXCERPT_LIMITS = (2400, 400, 400)

# 마지막 LLM 호출 결과. /health가 읽는다 — 헬스체크가 유료 API를 직접 호출하지 않도록 수동 관측.
_llm_state: dict = {"status": "unknown", "reason": None, "at": None}


def llm_state() -> dict:
    return dict(_llm_state)


def _record(status: str, reason: str | None = None) -> None:
    _llm_state.update(status=status, reason=reason, at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


def _classify(e: anthropic.APIError) -> tuple[str, str]:
    """LLM API 오류 → (종류, 사용자 안내). 운영자 조치가 필요한 것과 일시적인 것을 구분해 알린다."""
    if isinstance(e, anthropic.BadRequestError) and "credit balance" in str(e).lower():
        return "credit", "지금은 답변 생성 모델을 이용할 수 없습니다(API 이용 한도 소진 — 운영자 조치 필요)."
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return "auth", "지금은 답변 생성 모델을 이용할 수 없습니다(API 인증 오류 — 운영자 조치 필요)."
    if isinstance(e, anthropic.RateLimitError):
        return "rate_limit", "요청이 몰려 답변 생성이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
    if isinstance(e, anthropic.APIConnectionError):
        return "connection", "답변 생성 모델에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."
    if isinstance(e, anthropic.APIStatusError) and e.status_code >= 500:
        return "upstream", "답변 생성 모델이 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해 주세요."
    return "request", "답변 생성 요청이 처리되지 않았습니다(운영자 확인 필요)."


def _excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if "\n" in cut:
        cut = cut[: cut.rfind("\n")]  # 항·호 중간에서 끊지 않는다
    return f"{cut}\n…(이하 생략 — 아래 참고 조문의 '원문 ↗'에서 전문 확인)"


def search_only_answer(articles: list[RetrievedArticle], notice: str) -> str:
    """LLM 없이 만드는 응답 — 직접 검색된 상위 조문의 원문을 출처와 함께 그대로 싣는다."""
    parts = [f"⚠️ {notice} 대신 질문과 가장 가까운 조문 원문을 그대로 보여드립니다."]
    primary = [a for a in articles if a.kind == "검색"]
    for a, limit in zip(primary, _EXCERPT_LIMITS):
        parts.append(f"[출처: {a.citation}]\n{_excerpt(a.text, limit)}")
    parts.append(DISCLAIMER)
    return "\n\n".join(parts)


def answer_question(question: str, k: int | None = None, law: str | None = None) -> dict:
    articles = retrieve_hybrid(question, k, law=law)  # k=None이면 top_k 기본값, law=None이면 전체 법령
    if not articles:  # 인덱스 미빌드 시 Claude 호출 없이 안내
        return {
            "answer": "현재 색인된 조문이 없어 답변할 수 없습니다. "
            "`python -m scripts.build_index`로 인덱스를 먼저 빌드하세요.\n\n" + DISCLAIMER,
            "sources": [],
            "degraded": False,
        }
    sources = [a.to_source_dict() for a in articles]
    try:
        answer = generate_answer(question, articles)
    except anthropic.APIError as e:
        kind, notice = _classify(e)
        logger.warning("LLM 호출 실패(%s) — 검색 전용 응답으로 대체: %s", kind, e)
        _record("unavailable", kind)
        return {"answer": search_only_answer(articles, notice), "sources": sources, "degraded": True}
    _record("ok")
    return {"answer": answer, "sources": sources, "degraded": False}
