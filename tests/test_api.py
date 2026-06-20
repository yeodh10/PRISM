"""API 검증 경로 — TestClient (LLM 비호출: 검증·키 분기만)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "PRISM"
    assert "index_ready" in body and "index_count" in body


@pytest.mark.parametrize("q", ["", "   ", "가" * 1001])
def test_ask_invalid_question_422(q):
    assert client.post("/ask", json={"question": q}).status_code == 422


def test_ask_missing_field_422():
    assert client.post("/ask", json={}).status_code == 422


def test_ask_without_key_503(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = client.post("/ask", json={"question": "정상적인 질문입니다"})
    assert r.status_code == 503
