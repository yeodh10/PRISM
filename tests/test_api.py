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


def test_laws_include_basis_version(monkeypatch):
    # 법령 목록에 '어느 시행본 기준인지'가 함께 내려가야 화면에 기준일을 표시할 수 있다
    import app.main as main

    monkeypatch.setattr(main, "available_laws", lambda: [{"law": "개인정보보호법", "count": 3}, {"law": "기록없는법", "count": 1}])
    monkeypatch.setattr(
        main, "load_versions", lambda: {"개인정보보호법": {"effective": "2026-09-11", "number": "법률 제21445호", "checked": "2026-10-04"}}
    )
    laws = {d["law"]: d for d in client.get("/laws").json()["laws"]}
    assert laws["개인정보보호법"] == {
        "law": "개인정보보호법", "count": 3, "effective": "2026-09-11", "number": "법률 제21445호", "checked": "2026-10-04",
    }
    assert laws["기록없는법"]["effective"] is None  # 기록이 없어도 목록은 정상 응답


def test_ask_without_key_503(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = client.post("/ask", json={"question": "정상적인 질문입니다"})
    assert r.status_code == 503
