"""상호참조 그래프 + 외부법령 마스킹 단위 테스트."""
from app.rag.relations import _EXTERNAL, reference_graph


def test_external_law_masked():
    assert "제2조" not in _EXTERNAL.sub(" ", "「전자정부법」 제2조에 따른 처리")


def test_internal_ref_after_external_and_preserved():
    # 외부 법령 인용 뒤 연결어('및')로 이어지는 내부 조문은 보존돼야 함(마스킹이 삼키면 안 됨)
    masked = _EXTERNAL.sub(" ", "「전자정부법」 제2조 및 제15조")
    assert "제15조" in masked
    assert "「전자정부법」 제2조" not in masked


def test_internal_ref_after_external_or_preserved():
    assert "제23조" in _EXTERNAL.sub(" ", "「전자서명법」 제2조제1호 또는 제23조")


def test_reference_graph_excludes_external_includes_internal():
    g = reference_graph()
    # 제22조 본문은 「전자문서 및 전자거래 기본법」 제2조를 인용 → 내부 제2조로 잡히면 안 됨
    assert "제2조" not in g.get("제22조", [])
    # 내부 참조는 포함
    assert "제15조" in g.get("제22조", [])
