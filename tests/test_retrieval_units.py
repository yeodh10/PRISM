"""검색 구성요소 단위 테스트 — 조각 나누기·낱말 검색·순위 융합 (임베딩 모델·벡터스토어 비사용)."""
from app.rag.chunking import split_chunks
from app.rag.lexical import LexicalIndex, tokenize
from app.rag.retriever import rrf_fuse


def test_chunks_start_at_each_paragraph_and_keep_all_text():
    text = "① 첫 항\n1. 첫 호\n2. 둘째 호\n② 둘째 항\n③ 셋째 항"
    chunks = split_chunks(text, budget=240)
    assert chunks == ["① 첫 항\n1. 첫 호\n2. 둘째 호", "② 둘째 항", "③ 셋째 항"]  # 호는 자기 항에 붙는다
    assert "\n".join(chunks) == text  # 빠지는 글자 없음


def test_long_paragraph_is_split_at_item_lines_not_mid_line():
    items = [f"{i}. " + "가" * 60 for i in range(1, 7)]
    chunks = split_chunks("\n".join(["① 다음 각 호와 같다."] + items), budget=150)
    assert len(chunks) > 1 and all(len(c) <= 150 for c in chunks)
    assert [line for c in chunks for line in c.split("\n")][1:] == items  # 줄 단위로만 나뉨, 순서 유지


def test_single_overlong_line_stays_whole():
    line = "가" * 500
    assert split_chunks(line, budget=240) == [line]


def test_tokenize_uses_character_bigrams_so_particles_do_not_block_match():
    assert tokenize("과징금을 부과") == ["과징", "징금", "금을", "부과"]
    assert set(tokenize("과징금")) <= set(tokenize("과징금을"))  # 조사가 붙어도 어간 2-gram은 일치
    assert tokenize("AI 기본법 제2조") == ["ai", "기본", "본법", "제2", "2조"]


def test_lexical_search_ranks_by_shared_terms_and_filters():
    idx = LexicalIndex(
        {
            "A법:제1조": "불법감청에 의한 전기통신내용의 증거사용 금지",
            "A법:제2조": "개인정보의 수집 이용",
            "B법:제1조": "증거의 수집과 보전",
        }
    )
    assert idx.search("불법 감청으로 얻은 내용을 증거로 쓸 수 있나", 3)[0] == "A법:제1조"
    assert idx.search("감청", 3, allow=lambda uid: uid.startswith("B법:")) == []  # 범위 밖 문서는 제외
    assert idx.search("전혀무관한질의", 3) == []  # 겹치는 낱말이 없으면 결과 없음


def test_rrf_rewards_agreement_across_rankers():
    fused = rrf_fuse([["a", "b", "c"], ["b", "a", "d"], ["b", "e"]])
    order = [uid for uid, _ in fused]
    assert order[:2] == ["b", "a"]  # 세 목록에서 고르게 상위인 b가 1위
    scores = dict(fused)
    assert 0 < scores["e"] < scores["a"] < scores["b"] <= 1.0
    assert rrf_fuse([["x"], ["x"], ["x"]])[0] == ("x", 1.0)  # 모든 목록 1위 = 1
    assert rrf_fuse([[], []]) == []
