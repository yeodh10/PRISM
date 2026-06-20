"""도메인 모델 — 조문(Article)."""
from pydantic import BaseModel, Field


class Article(BaseModel):
    """개인정보 보호법 조문 하나(조 단위 청크)."""

    id: str = Field(..., description="조문 식별자, 예: 제29조")
    title: str = Field(..., description="조문 제목, 예: 안전조치의무")
    category: str = Field(..., description="분류, 예: 안전성 확보 조치")
    text: str = Field(..., description="조문 전문(항·호 포함)")
    ref: str = Field(default="개인정보 보호법", description="출처 법령명")
    source_url: str | None = Field(default=None, description="원문 URL(law.go.kr)")

    @property
    def embedding_text(self) -> str:
        """임베딩 대상: 제목 + 본문 (검색 적중률 향상)."""
        return f"{self.title}\n{self.text}"
