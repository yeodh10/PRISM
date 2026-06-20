"""도메인 모델 — 조문(Article)."""
from pydantic import BaseModel, Field


class Article(BaseModel):
    """법령 조문 하나(조 단위 청크). 여러 법령을 함께 서비스하므로 `law`로 구분."""

    law: str = Field(default="개인정보보호법", description="법령 약칭, 예: 개인정보보호법/정보통신망법/신용정보법/위치정보법")
    id: str = Field(..., description="조문 식별자, 예: 제29조")
    title: str = Field(..., description="조문 제목, 예: 안전조치의무")
    category: str = Field(..., description="분류, 예: 안전성 확보 조치")
    text: str = Field(..., description="조문 전문(항·호 포함)")
    ref: str = Field(default="개인정보 보호법", description="출처 법령 정식명")
    source_url: str | None = Field(default=None, description="원문 URL(law.go.kr)")

    @property
    def uid(self) -> str:
        """법령 간 고유 식별자(조문 번호가 법령마다 겹치므로). 예: 개인정보보호법:제15조"""
        return f"{self.law}:{self.id}"

    @property
    def embedding_text(self) -> str:
        """임베딩 대상: 제목 + 본문 (검색 적중률 향상)."""
        return f"{self.title}\n{self.text}"
