# PRISM 컨테이너 이미지 — Fly.io / Railway / Render(Docker) / 그 외 어떤 호스트든.
# 인덱스와 임베딩 모델을 빌드 시점에 이미지에 베이크 → 런타임 다운로드/재빌드 불필요.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUTF8=1 \
    HF_HOME=/app/.hf

WORKDIR /app

# 의존성 먼저(레이어 캐시)
COPY requirements.txt .
RUN pip install -r requirements.txt

# 앱 소스
COPY . .

# 인덱스 빌드 → chroma_db/ 와 SBERT 모델 캐시가 이미지에 포함됨
# (.dockerignore가 로컬 chroma_db/·venv/·.env 등을 제외하므로 깨끗하게 새로 빌드)
RUN python -m scripts.build_index

EXPOSE 8000
# 플랫폼이 주는 $PORT 우선, 없으면 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
