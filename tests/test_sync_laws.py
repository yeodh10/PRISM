"""law.go.kr 현행본 대조·갱신(scripts.sync_laws) 단위 테스트 — 네트워크 비호출(HTML 픽스처)."""
import json

from app.models import Article
from scripts import sync_laws
from scripts.sync_laws import (
    DEFAULT_LAW,
    DEFAULT_REF,
    LawVersion,
    OfficialArticle,
    law_url,
    normalize,
    parse_articles,
    parse_version,
)

# law.go.kr lsInfoR.do 응답의 구조를 줄인 것: 머리말 · 장 제목 · 조문 2개 · 삭제된 조 · 부칙
BODY = """
<input type="hidden" id="lsNm" name="lsNm" value="시험법" />
<input type="hidden" id="lsId" name="lsId" value="000001" />
<input type="hidden" id="lsiSeq" name="lsiSeq" value="123456" />
<script>var x = "[시행 1999. 1. 1.] [법률 제1호, 1999. 1. 1., 제정]";</script>
<div id="conTop"><h2>시험법</h2><div class="ct_sub">[시행 2026. 9. 11.] [법률 제21445호, 2026. 3. 10., 일부개정]</div></div>
<div class="pgroup" style="padding-bottom: 0px;"><p class="gtit">제1장 총칙</p></div>
<a name="J1:0" id="J1:0"></a>
<div class="pgroup">
 <ul class="lawico01"><li><a href="#AJAX"><img alt="연혁" src="/LSW/images/button/btn_year3.gif" /></a></li></ul>
 <div class="lawcon">
  <p class="pty1_p4"> <input name="joNoList" id="Y000100" type="checkbox" value="1:0:000100:1" /> <span class="bl"><label for="Y000100"> 제1조(목적) </label> </span> 이 법은 시험을 목적으로 한다. <span class="sfon">&lt;개정 2023. 3. 14.&gt;</span> </p>
  <p></p>
 </div>
</div>
<div class="pgroup">
 <div class="lawcon">
  <p class="pty1_p4"> <input name="joNoList" type="checkbox" value="23:3:002303:2" /> <span class="bl"><label> 제23조의3(본인확인기관의 지정ㆍ취소) </label> </span> ①방송미디어통신위원회는 다음 각 호의 사항을   심사한다. <span class="sfon">&lt;개정 2025. 10. 1.&gt;</span> </p>
  <p class="pty1_de2h">1. <a class="link" href="javascript:;">「개인정보 보호법」</a> <a class="link" href="javascript:;">제24조</a>에 따른 “고유식별정보”의 처리 </p>
  <p class="pty1_de2h">2.삭제 <span class="sfon">&lt;2020. 2. 4.&gt;</span> </p>
  <p class="pty1_de3">가. 略式 절차 </p>
  <p class="pty1_de2_1">② 삭제 <span class="sfon">&lt;2014. 5. 28.&gt;</span> </p>
  <p class="pty1_de2"> <span class="sfon">[본조신설 2011. 4. 5.]</span> </p>
  <div class="rule_area"><div class="btn_rule"><a href="#"><img src="btn_rule_view.gif" alt="위임행정규칙" /></a></div></div>
  <p></p>
 </div>
</div>
<div class="pgroup">
 <div class="lawcon">
  <p class="pty1_p4"> <input name="joNoList" type="checkbox" value="40:0:004000:3" /> <span class="bl"><label> 제40조 </label> </span> 삭제 <span class="sfon">&lt;2020. 2. 4.&gt;</span> </p>
 </div>
</div>
<div class="pgroup">
 <div class="lawcon">
  <p class="pty1_p4"> <input name="joNoList" type="checkbox" value="50:0:005000:4" /> <span class="bl"><label> 제50조(뒤에 시행되는 조문) </label> </span> 나중에 시행된다. </p>
  <p class="pty1_de2"> <span class="sfon">[본조신설 2026. 3. 10.][시행일: 2999. 1. 1.] 제50조</span> </p>
 </div>
</div>
<div id="arDivArea">
 <div class="pgroup">
  <p class="pty3">부칙 <span class="sfon">&lt;법률 제21445호, 2026. 3. 10.&gt;</span></p>
  <div class="lawcon">
   <p class="pty1_p4"> <input name="joNoList" type="checkbox" value="1:0:000100:9" /> <span class="bl"><label> 제1조(시행일) </label> </span> 이 법은 공포한 날부터 시행한다. </p>
  </div>
 </div>
</div>
"""


def test_parse_version_reads_header_not_script():
    v = parse_version(BODY)
    assert (v.effective, v.promulgated) == ("2026-09-11", "2026-03-10")
    assert (v.number, v.kind) == ("법률 제21445호", "일부개정")
    assert (v.name, v.law_id, v.lsi_seq) == ("시험법", "000001", "123456")


def test_parse_articles_skips_headings_deleted_articles_and_addenda():
    arts = parse_articles(BODY)
    # 장 제목·통째로 삭제된 제40조는 조문이 아니고, 부칙의 제1조가 본문 제1조를 덮어쓰면 안 된다
    assert set(arts) == {"제1조", "제23조의3", "제50조"}
    assert arts["제1조"].title == "목적"
    assert arts["제1조"].text == "이 법은 시험을 목적으로 한다."


def test_parse_articles_text_is_verbatim_with_marks_removed():
    a = parse_articles(BODY)["제23조의3"]
    assert a.title == "본인확인기관의 지정ㆍ취소"
    assert a.text.split("\n") == [
        "① 방송미디어통신위원회는 다음 각 호의 사항을 심사한다.",  # 연혁 표기 제거, 항 머리 뒤 한 칸
        '1. 「개인정보 보호법」 제24조에 따른 "고유식별정보"의 처리',  # 링크 태그 제거, 곧은 따옴표
        "2. 삭제 <2020. 2. 4.>",  # 삭제된 호는 원문 표시대로 날짜를 남김
        "가. 略式 절차",  # 호환 한자(U+F976) → 통합 한자(U+7565)
        "② 삭제 <2014. 5. 28.>",
    ]
    assert "[본조신설 2011. 4. 5.]" in a.notes
    assert not a.warnings


def test_pending_provision_is_flagged():
    a = parse_articles(BODY)["제50조"]
    assert any("시행 전" in w for w in a.warnings)


def test_normalize_ignores_only_glyph_and_spacing_differences():
    assert normalize("수집·이용 “동의”\n① 한다") == normalize('수집ㆍ이용 "동의" ①한다')
    assert normalize("100분의 3") != normalize("100분의 10")


def test_defaults_match_article_model():
    # pipa.json은 law·ref를 생략한다 — 동기화 스크립트의 기본값이 모델 기본값과 어긋나면 엉뚱한 법령과 대조하게 된다
    assert Article.model_fields["law"].default == DEFAULT_LAW
    assert Article.model_fields["ref"].default == DEFAULT_REF


def test_law_url_is_version_independent():
    assert law_url("개인정보 보호법", "제39조의3") == "https://www.law.go.kr/법령/개인정보보호법/제39조의3"


def _fake_fetch(ref):
    version = LawVersion("시험법", "2026-09-11", "2026-03-10", "법률 제21445호", "일부개정", "000001", "123456")
    return version, {
        "제1조": OfficialArticle("제1조", "목적", "이 법은 시험을 목적으로 한다."),
        "제2조": OfficialArticle("제2조", "정의", "① 새 정의\n1. 가\n2. 나"),
        "제3조": OfficialArticle("제3조", "신설 조문", "새로 생긴 조문이다."),
    }


def test_sync_check_then_write_then_clean(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sync_laws, "fetch_law", _fake_fetch)
    monkeypatch.setattr(sync_laws.time, "sleep", lambda s: None)
    items = [
        {"law": "시험법", "id": "제1조", "title": "목적", "category": "총칙", "text": "이 법은 시험을 목적으로 한다.", "ref": "시험법"},
        {"law": "시험법", "id": "제2조", "title": "정의", "category": "총칙", "text": "① 옛 정의", "ref": "시험법"},
        {"law": "시험법", "id": "제3조", "title": "", "category": "총칙", "text": "", "ref": "시험법"},  # 추가용 빈 항목
    ]
    f = tmp_path / "test_act.json"
    f.write_bytes(("[\r\n" + ",\r\n".join("  " + json.dumps(i, ensure_ascii=False) for i in items) + "\r\n]\r\n").encode())

    assert sync_laws.sync(tmp_path, write=False, rewrite_all=False, verbose=True, only=set()) == 1  # 차이 감지
    assert json.loads(f.read_text(encoding="utf-8"))[1]["text"] == "① 옛 정의"  # 대조만으로는 안 바뀜

    assert sync_laws.sync(tmp_path, write=True, rewrite_all=False, verbose=False, only=set()) == 0
    raw = f.read_bytes().decode("utf-8")
    got = json.loads(raw)
    assert got[1]["text"] == "① 새 정의\n1. 가\n2. 나"
    assert (got[2]["title"], got[2]["text"]) == ("신설 조문", "새로 생긴 조문이다.")  # 빈 항목이 원문으로 채워짐
    assert got[0]["source_url"] == "https://www.law.go.kr/법령/시험법/제1조"
    assert raw.count("\r\n") == 5 and raw.startswith("[\r\n  {")  # 조문당 한 줄·줄바꿈 방식 유지
    versions = json.loads((tmp_path / "_versions.json").read_text(encoding="utf-8"))
    assert versions["시험법"]["effective"] == "2026-09-11"

    assert sync_laws.sync(tmp_path, write=False, rewrite_all=False, verbose=False, only=set()) == 0  # 동기 상태
    capsys.readouterr()


def test_sync_reports_article_missing_from_current_law(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sync_laws, "fetch_law", _fake_fetch)
    monkeypatch.setattr(sync_laws.time, "sleep", lambda s: None)
    item = {"law": "시험법", "id": "제99조", "title": "사라진 조문", "category": "c", "text": "옛 본문", "ref": "시험법"}
    (tmp_path / "test_act.json").write_text("[\n  " + json.dumps(item, ensure_ascii=False) + "\n]\n", encoding="utf-8")
    # 현행 본문에 없는 조문은 자동으로 고치지 않고 실패로 알린다(삭제·이동은 사람이 판단)
    assert sync_laws.sync(tmp_path, write=True, rewrite_all=False, verbose=False, only=set()) == 1
    assert "현행 본문에 없음" in capsys.readouterr().out
    assert json.loads((tmp_path / "test_act.json").read_text(encoding="utf-8"))[0]["text"] == "옛 본문"
