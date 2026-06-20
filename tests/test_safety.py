"""generator 안전망(면책 고지·출처 검증) 단위 테스트 — LLM 비호출."""
from app.rag.generator import DISCLAIMER, _cited_ids, _finalize
from app.rag.retriever import RetrievedArticle


def _art(article_id: str) -> RetrievedArticle:
    return RetrievedArticle(
        id=article_id, title="제목", category="c", ref="개인정보 보호법",
        text="t", source_url="", score=0.5,
    )


def test_disclaimer_appended_when_missing():
    out = _finalize("답변 [출처: 제29조(안전조치의무)]", [_art("제29조")], "end_turn")
    assert DISCLAIMER in out


def test_disclaimer_not_duplicated():
    out = _finalize(f"답변 [출처: 제29조(x)]\n\n{DISCLAIMER}", [_art("제29조")], "end_turn")
    assert out.count(DISCLAIMER) == 1


def test_empty_answer_gets_safe_message_and_disclaimer():
    out = _finalize("", [_art("제29조")], "end_turn")
    assert "정상적으로 완료되지 않았" in out
    assert DISCLAIMER in out


def test_max_tokens_truncation_flagged():
    out = _finalize("부분 답변", [_art("제29조")], "max_tokens")
    assert "정상적으로 완료되지 않았" in out


def test_unverified_citation_flagged():
    # 검색 조문엔 제29조만 있는데 답변이 제99조를 인용 → 경고 배너
    out = _finalize("내용 [출처: 제99조(가짜)]", [_art("제29조")], "end_turn")
    assert "제99조" in out and "확인되지 않았" in out


def test_missing_citation_flagged():
    out = _finalize("출처 없는 답변", [_art("제29조")], "end_turn")
    assert "근거 조문 인용이 확인되지 않았" in out


def test_valid_citation_passes_without_warning():
    out = _finalize("답변 [출처: 제29조(안전조치의무)]", [_art("제29조")], "end_turn")
    assert "확인되지 않았" not in out


def test_nomatch_answer_not_flagged():
    out = _finalize("제공된 조문에서는 찾지 못했습니다.", [_art("제29조")], "end_turn")
    assert "근거 조문 인용이 확인되지 않았" not in out


def test_cited_ids_extraction():
    assert _cited_ids("a [출처: 제29조(x)] b [출처: 제28조의2(y)]") == {"제29조", "제28조의2"}
