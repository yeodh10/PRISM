"""RAG 오케스트레이션: 질문 → Hybrid 검색 → 생성 → {answer, sources}."""
from app.rag.generator import DISCLAIMER, generate_answer
from app.rag.retriever import retrieve_hybrid


def answer_question(question: str, k: int | None = None) -> dict:
    articles = retrieve_hybrid(question, k)  # k=None이면 retriever가 top_k 기본값 적용
    if not articles:  # 인덱스 미빌드 시 Claude 호출 없이 안내
        return {
            "answer": "현재 색인된 조문이 없어 답변할 수 없습니다. "
            "`python -m scripts.build_index`로 인덱스를 먼저 빌드하세요.\n\n" + DISCLAIMER,
            "sources": [],
        }
    answer = generate_answer(question, articles)
    return {"answer": answer, "sources": [a.to_source_dict() for a in articles]}
