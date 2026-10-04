"""조문 데이터 불변식 — 네트워크 없이 확인할 수 있는 무결성(현행본 대조 자체는 scripts.sync_laws)."""
import re

from app.loader import load_articles, load_versions
from scripts.sync_laws import law_url

# 연혁 표기·HTML 잔재 — 원문 본문이 아닌 것이 섞였다는 신호
_RESIDUE = re.compile(r"<(?:개정|신설|전문개정)|\[(?:본조신설|전문개정|제목개정|시행일)|&(?:lt|gt|amp|nbsp);|<span|<a ")


def test_meta_file_is_not_loaded_as_articles():
    # data/_versions.json(메타)이 조문으로 읽히면 로더가 예외를 던진다
    assert load_articles()
    assert load_versions()


def test_every_law_has_recorded_basis_version():
    versions = load_versions()
    for law in {a.law for a in load_articles()}:
        v = versions.get(law)
        assert v, f"{law}: 기준 시행본 기록 없음 — python -m scripts.sync_laws --write"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", v["effective"])
        assert re.search(r"제\d+호$", v["number"])


def test_source_url_points_to_current_version_of_the_article():
    # 특정 연혁 버전(lsiSeq)에 고정된 링크는 개정 후 옛 본문을 보여준다 → 법령명 기반 주소만 허용
    for a in load_articles():
        assert a.source_url == law_url(a.ref, a.id), a.uid


def test_text_has_no_history_marks_or_html_residue():
    for a in load_articles():
        m = _RESIDUE.search(a.text)
        assert not m, f"{a.uid}: {a.text[max(0, m.start() - 20):m.start() + 30]!r}"
        assert not re.match(r"제\d+조(의\d+)?\s*\(", a.text), f"{a.uid}: 본문이 조문 라벨로 시작"
