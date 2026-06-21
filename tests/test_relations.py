"""상호참조 그래프 + 외부법령 마스킹 단위 테스트."""
from app.rag.relations import _EXTERNAL, get_article_by_uid, reference_graph


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
    # 멀티 법령: 키·값이 uid(법령:조문). 개인정보보호법 제22조 기준.
    refs = g.get("개인정보보호법:제22조", [])
    # 제22조 본문의 「전자문서 및 전자거래 기본법」 제2조 인용 → 내부 제2조로 잡히면 안 됨
    assert "개인정보보호법:제2조" not in refs
    # 같은 법령 내부 참조는 포함
    assert "개인정보보호법:제15조" in refs


def test_cross_law_reference_linked():
    g = reference_graph()
    # 신용정보법 제40조②가 「정보통신망…법」 제50조를 '준용' → 크로스-법령 연결
    assert "정보통신망법:제50조" in g.get("신용정보법:제40조", [])
    # 신용정보법 제15조가 「개인정보 보호법」 제15조 인용 → 보유 중인 타 법 조문으로 연결
    assert "개인정보보호법:제15조" in g.get("신용정보법:제15조", [])


def test_graph_edges_point_to_owned_articles_only():
    # 모든 간선의 대상은 우리가 보유한 조문이어야 함(미보유 외부법으로의 dangling 간선 없음)
    g = reference_graph()
    for src, tgts in g.items():
        for t in tgts:
            assert get_article_by_uid(t) is not None, f"{src} → {t} (미보유 조문)"
