"""조문 본문을 임베딩용 조각으로 나눈다.

SBERT는 입력 앞쪽 128토큰만 본다. 조문 전체를 한 벡터로 만들면 긴 조문은 제목과 제1항만 반영되고
뒤쪽 항(예: 과징금 10% 구간, 유출 가능성 통지)은 검색에 잡히지 않는다. 그래서 항 경계로 나눠
조각마다 벡터를 만들고, 검색 결과는 조 단위로 묶어 돌려준다(작게 찾고 크게 돌려주기).
"""
import re

_PARAGRAPH = re.compile(r"^[①-⑳㉑-㉟㊱-㊿]")  # 항 머리(원문자)
CHUNK_CHARS = 240  # 조각 길이 상한(자). 한국어 SBERT 128토큰에 대략 맞춘 값


def split_chunks(text: str, budget: int = CHUNK_CHARS) -> list[str]:
    """본문(줄 단위: 항·호·목) → 조각 목록.

    새 항에서는 항상 새 조각을 시작하고, 한 항이 budget을 넘으면 호·목 줄 경계에서 다시 나눈다.
    한 줄이 budget보다 길어도 줄 중간에서는 자르지 않는다(임베딩 시 뒷부분만 잘린다).
    """
    chunks: list[str] = []
    cur = ""
    for line in text.split("\n"):
        if cur and (_PARAGRAPH.match(line) or len(cur) + len(line) + 1 > budget):
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks
