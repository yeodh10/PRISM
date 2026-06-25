"""중앙 설정. .env 에서 값을 읽어온다 (pydantic-settings)."""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    anthropic_api_key: str = ""
    # 답변 생성용. Anthropic 권장 기본값. 비용 민감 데모면 .env의 CLAUDE_MODEL로
    # claude-sonnet-4-6 / claude-haiku-4-5 로 교체 가능.
    claude_model: str = "claude-opus-4-8"
    # adaptive thinking 깊이(output_config.effort). opus-4-8 유효 티어 전부 허용.
    # (Claude Code 세션의 CLAUDE_EFFORT=max 등 환경변수도 그대로 수용) 오타는 기동 시 ValidationError로 즉시 잡힘.
    claude_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"

    # --- 임베딩 ---
    embedding_model: str = "jhgan/ko-sroberta-multitask"  # 한국어 SBERT (768d)

    # --- 벡터스토어 ---
    chroma_dir: str = "./chroma_db"
    collection_name: str = "pipa"

    # --- 검색 ---
    top_k: int = 4

    # --- 데이터 ---
    data_path: str = "./data/pipa.json"     # (하위호환) 단일 파일 경로
    data_dir: str = "./data"                # 여기의 모든 *.json(법령별)을 로드 — 멀티 법령

    # --- 뉴스 탭 (정보성 외부 뉴스, 법령 답변과 분리) ---
    news_rss_url: str = "https://www.dailysecu.com/rss/allArticle.xml"
    news_cache_ttl: int = 1800  # 초
    news_http_timeout: float = 6.0
    news_max_workers: int = 6

    # --- CORS (콤마 구분) ---
    # 기본은 cross-origin 차단(빈 값). 프론트는 FastAPI가 같은 오리진으로 서빙하므로
    # 영향 없음. 외부 도메인에서 /ask를 호출해야 할 때만 그 도메인을 .env로 지정.
    cors_allow_origins: str = ""


settings = Settings()
