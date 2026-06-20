"""PRISM — 개인정보보호법 RAG 챗봇 (FastAPI 진입점)."""
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.news import get_news
from app.service import answer_question

logger = logging.getLogger("prism")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

# --- 간단한 인메모리 레이트리밋 (/ask 비용 남용·DoS 완화, IP당 고정 윈도) ---
_RL_WINDOW = 60.0
_RL_MAX = 20  # IP당 분당 최대 호출
_rl_lock = threading.Lock()
_rl_hits: dict[str, list[float]] = defaultdict(list)


def _rate_limited(ip: str) -> bool:
    now = time.time()
    with _rl_lock:
        hits = [t for t in _rl_hits[ip] if now - t < _RL_WINDOW]
        if len(hits) >= _RL_MAX:
            _rl_hits[ip] = hits
            return True
        hits.append(now)
        _rl_hits[ip] = hits
        if len(_rl_hits) > 10000:  # 메모리 누수 방지: 비활성 IP 정리
            for k in [k for k, v in list(_rl_hits.items()) if not v or now - v[-1] > _RL_WINDOW]:
                _rl_hits.pop(k, None)
        return False

app = FastAPI(
    title="PRISM — 개인정보보호법 RAG 챗봇",
    description="개인정보 보호법 조문을 검색해 출처와 함께 답하는 RAG 챗봇. "
    "⚠️ 비공식 참고용이며 법률 자문이 아닙니다.",
    version="0.3.0",
)

# 프론트를 같은 오리진에서 서빙하므로 기본 데모는 전체 허용. 운영은 .env의 CORS_ALLOW_ORIGINS로 제한.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000, description="자연어 질문")


class Source(BaseModel):
    id: str
    title: str
    category: str
    ref: str
    source_url: str | None = None
    score: float
    kind: str = "검색"  # "검색"(벡터 적중) | "연관"(상호참조로 연결)
    linked_from: list[str] = []


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]


@app.get("/", include_in_schema=False)
def index():
    """프론트엔드(단일 HTML) 서빙. 갱신 즉시 반영되도록 no-cache."""
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/health", tags=["system"])
def health():
    """헬스체크 — 앱 기동·키·벡터 인덱스 준비 여부(인덱스 미빌드면 degraded)."""
    try:
        from app.rag.vectorstore import get_collection

        index_count = get_collection().count()
    except Exception:
        index_count = 0
    ready = bool(settings.anthropic_api_key) and index_count > 0
    return {
        "status": "ok" if ready else "degraded",
        "service": "PRISM",
        "model": settings.claude_model,
        "api_key_set": bool(settings.anthropic_api_key),
        "index_count": index_count,
        "index_ready": index_count > 0,
    }


@app.post("/ask", response_model=AskResponse, tags=["rag"])
def ask(req: AskRequest, request: Request):
    """질문 → 관련 조문 검색 → Claude가 출처 인용해 답변."""
    client_ip = request.client.host if request.client else "?"
    if _rate_limited(client_ip):
        raise HTTPException(status_code=429, detail="요청이 너무 잦습니다. 잠시 후 다시 시도해 주세요.")
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=422, detail="질문이 비어 있습니다.")
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.",
        )
    try:
        return answer_question(question)
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=401, detail="Anthropic API 키가 유효하지 않습니다. .env의 키를 확인하세요.")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="요청이 많아 잠시 지연되고 있습니다. 잠시 후 다시 시도해 주세요.")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=503, detail="Claude API에 연결하지 못했습니다. 네트워크 상태를 확인하세요.")
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"Claude API 오류({e.status_code})가 발생했습니다. 잠시 후 다시 시도해 주세요.")
    except Exception:
        logger.exception("ask() 처리 중 예기치 못한 오류")
        raise HTTPException(status_code=500, detail="답변 생성 중 오류가 발생했습니다.")


@app.get("/news", tags=["news"])
def news():
    """개인정보·보안 관련 외부 뉴스(데일리시큐 RSS). 법령 답변과 무관한 정보 탭."""
    return {"items": get_news()}
