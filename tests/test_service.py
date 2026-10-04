"""검색 전용 응답(LLM 장애 시) — LLM 비호출: generate_answer를 오류로 대체해 검증."""
import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

import app.service as service
from app.main import app
from app.rag.generator import DISCLAIMER
from app.rag.retriever import RetrievedArticle

client = TestClient(app)
_REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _art(article_id: str, text: str, kind: str = "검색") -> RetrievedArticle:
    return RetrievedArticle(
        id=article_id, law="개인정보보호법", title="안전조치의무", category="c", ref="개인정보 보호법",
        text=text, source_url="", score=0.5, kind=kind,
    )


def _status_error(cls, status: int, message: str):
    return cls(message, response=httpx.Response(status, request=_REQ), body=None)


def _raising(exc):
    def gen(question, articles):
        raise exc

    return gen


CREDIT = _status_error(anthropic.BadRequestError, 400, "Your credit balance is too low to access the Anthropic API.")


@pytest.fixture
def retrieved(monkeypatch):
    arts = [_art("제29조", "① 본문 첫 항\n1. 첫 호"), _art("제31조", "연관 조문 본문", kind="연관")]
    monkeypatch.setattr(service, "retrieve_hybrid", lambda q, k, law=None: arts)
    return arts


def test_llm_failure_falls_back_to_verbatim_articles(retrieved, monkeypatch):
    monkeypatch.setattr(service, "generate_answer", _raising(CREDIT))
    out = service.answer_question("안전조치?")
    assert out["degraded"] is True
    assert "[출처: 개인정보보호법 제29조(안전조치의무)]\n① 본문 첫 항\n1. 첫 호" in out["answer"]  # 원문 그대로
    assert "연관 조문 본문" not in out["answer"]  # 본문은 직접 검색된 조문만
    assert out["answer"].endswith(DISCLAIMER)
    assert [s["id"] for s in out["sources"]] == ["제29조", "제31조"]  # 참고 조문 목록은 그대로 제공
    assert service.llm_state()["status"] == "unavailable" and service.llm_state()["reason"] == "credit"


@pytest.mark.parametrize(
    "exc, kind, hint",
    [
        (CREDIT, "credit", "운영자 조치 필요"),
        (_status_error(anthropic.AuthenticationError, 401, "invalid x-api-key"), "auth", "운영자 조치 필요"),
        (_status_error(anthropic.RateLimitError, 429, "rate limited"), "rate_limit", "잠시 후 다시"),
        (anthropic.APIConnectionError(request=_REQ), "connection", "잠시 후 다시"),
        (_status_error(anthropic.InternalServerError, 529, "overloaded"), "upstream", "잠시 후 다시"),
        (_status_error(anthropic.BadRequestError, 400, "max_tokens: invalid"), "request", "운영자 확인 필요"),
    ],
)
def test_failure_kinds_tell_user_whether_retry_helps(exc, kind, hint):
    got_kind, notice = service._classify(exc)
    assert got_kind == kind and hint in notice


def test_success_is_not_degraded_and_marks_llm_ok(retrieved, monkeypatch):
    monkeypatch.setattr(service, "generate_answer", lambda q, a: "답변 [출처: 개인정보보호법 제29조(안전조치의무)]")
    out = service.answer_question("안전조치?")
    assert out["degraded"] is False and out["answer"].startswith("답변")
    assert service.llm_state()["status"] == "ok"


def test_non_api_errors_are_not_masked(retrieved, monkeypatch):
    # 우리 코드의 버그까지 '검색 전용'으로 가리면 안 된다 — API 오류만 흡수
    monkeypatch.setattr(service, "generate_answer", _raising(KeyError("bug")))
    with pytest.raises(KeyError):
        service.answer_question("안전조치?")


def test_long_article_is_cut_at_line_boundary():
    lines = [f"{i}. " + "가" * 95 for i in range(1, 21)]  # 줄당 약 100자 × 20줄
    out = service._excerpt("\n".join(lines), 900)
    body, tail = out.rsplit("\n", 1)
    assert tail.startswith("…(이하 생략")
    assert len(body) <= 900 and body.split("\n") == lines[: len(body.split("\n"))]  # 줄 중간에서 끊지 않음
    assert service._excerpt("짧은 본문", 900) == "짧은 본문"


def test_ask_endpoint_returns_200_degraded_and_health_reports_it(retrieved, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(service, "generate_answer", _raising(CREDIT))
    r = client.post("/ask", json={"question": "안전조치 의무는?"})
    assert r.status_code == 200
    assert r.json()["degraded"] is True and "⚠️" in r.json()["answer"]
    health = client.get("/health").json()
    assert health["llm"]["status"] == "unavailable" and health["status"] == "degraded"
