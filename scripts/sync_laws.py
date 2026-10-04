"""법령 현행성 동기화 — 국가법령정보센터(law.go.kr) 현행 본문 ↔ data/*.json.

법령은 계속 개정된다. 수집 당시 정확했던 원문도 시간이 지나면 '현행'이 아니게 되고,
미러 사이트·수작업 대조는 개정 반영이 늦거나 누락을 놓친다. 그래서 법령별 현행 본문을
law.go.kr에서 직접 받아 조 단위로 파싱하고, 보유 조문의 본문·제목과 기계적으로 대조한다.

  python -m scripts.sync_laws                # 대조만 — 차이가 있으면 종료코드 1
  python -m scripts.sync_laws -v             # 차이 위치까지 출력
  python -m scripts.sync_laws --write        # 차이 나는 조문을 현행 원문으로 갱신
  python -m scripts.sync_laws --write --all  # 전 조문을 같은 서식으로 재생성

조문 추가도 같은 경로: data/*.json에 id·category만 채운 항목(title·text는 빈 문자열)을 넣고
--write 하면 제목·본문·원문 URL이 현행 원문에서 채워진다(본문을 손으로 옮기지 않는다).

표준 라이브러리만 사용한다(무거운 의존성 없이 CI 스케줄 점검에서 바로 실행).
종료코드: 0 동기 상태 / 1 차이 있음 / 2 수집 실패(네트워크·페이지 구조 변경 등)
"""
import argparse
import datetime as dt
import difflib
import html
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

BASE = "https://www.law.go.kr"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
VERSIONS_FILE = "_versions.json"  # 법령별 기준 시행본 기록('_' 접두 파일은 조문 로더가 건너뜀)
# app.models.Article 기본값과 동일(pipa.json은 law·ref 생략) — tests/test_sync_laws.py가 일치를 검증
DEFAULT_LAW, DEFAULT_REF = "개인정보보호법", "개인정보 보호법"
_UA = "Mozilla/5.0 (compatible; PRISM-law-sync; +https://github.com/yeodh10/PRISM)"


def _today() -> str:
    """오늘 날짜(한국 시간). 시행일은 한국 날짜 기준이라, UTC로 도는 CI에서 하루 어긋나지 않게 한다."""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()


class FetchError(RuntimeError):
    """law.go.kr 수집 실패 또는 예상과 다른 페이지 구조."""


@dataclass
class LawVersion:
    name: str  # 정식 법령명
    effective: str  # 시행일 YYYY-MM-DD
    promulgated: str  # 공포일 YYYY-MM-DD
    number: str  # 예: 법률 제21445호
    kind: str  # 예: 일부개정, 타법개정
    law_id: str
    lsi_seq: str


@dataclass
class OfficialArticle:
    id: str
    title: str
    text: str
    notes: list[str] = field(default_factory=list)  # <개정 …>, [본조신설 …] 등 연혁 표기
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 수집
def _http(url: str, data: dict | None = None, referer: str | None = None) -> str:
    body = urllib.parse.urlencode(data).encode() if data else None
    headers = {"User-Agent": _UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, data=body, headers=headers)
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise FetchError(f"{url} 요청 실패: {last}")


def law_url(ref: str, article_id: str | None = None) -> str:
    """항상 현행본으로 연결되는 원문 주소(법령명 기반 — 특정 연혁 버전에 고정되지 않음)."""
    url = f"{BASE}/법령/{ref.replace(' ', '')}"
    return f"{url}/{article_id}" if article_id else url


def fetch_law(ref: str) -> tuple[LawVersion, dict[str, OfficialArticle]]:
    """정식 법령명 → (현행 시행본 정보, 조문 dict). 현행본은 법령명 주소가 가리키는 시행일 기준."""
    top_url = urllib.parse.quote(law_url(ref), safe=":/")
    top = _http(top_url)
    m = re.search(r'src="([^"]*lsInfoP\.do\?[^"]*)"', top)
    if not m:
        raise FetchError(f"{ref}: 법령 페이지에서 본문 프레임을 찾지 못함(법령명 확인 필요)")
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(html.unescape(m.group(1))).query)
    try:
        lsi_seq, ef_yd = query["lsiSeq"][0], query["efYd"][0]
    except KeyError as e:
        raise FetchError(f"{ref}: 본문 프레임 주소에 {e} 없음") from None
    # 같은 공포본도 시행일(efYd)에 따라 본문이 다르다 — 프레임이 가리키는 현행 시행일을 그대로 넘긴다.
    body = _http(
        f"{BASE}/LSW/lsInfoR.do",
        data={"lsiSeq": lsi_seq, "efYd": ef_yd, "chrClsCd": "010202", "urlMode": "lsInfoP", "ancYnChk": "0"},
        referer=top_url,
    )
    version = parse_version(body)
    if version.effective.replace("-", "") != ef_yd:
        raise FetchError(f"{ref}: 본문 시행일({version.effective})이 현행 시행일({ef_yd})과 다름")
    if version.effective > _today():
        raise FetchError(f"{ref}: 시행 전 버전({version.effective})이 현행으로 반환됨")
    articles = parse_articles(body)
    if not articles:
        raise FetchError(f"{ref}: 본문에서 조문을 찾지 못함(페이지 구조 변경 가능)")
    return version, articles


# ---------------------------------------------------------------- 파싱
_SFON = re.compile(r'<span class="sfon">(.*?)</span>', re.S)  # 연혁 표기
_HEAD = re.compile(
    r"\[시행\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\]\s*"
    r"\[\s*([^\[\],]+?제\s*\d+호),\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.,\s*([^\]]+?)\s*\]"
)
_PGROUP = re.compile(r'<div class="pgroup"[^>]*>(.*?)(?=<div class="pgroup"|\Z)', re.S)
_PARA = re.compile(r"<p(?:\s[^>]*)?>(.*?)</p>", re.S)
_JO = re.compile(r'name="joNoList"[^>]*value="(\d+):(\d+):|value="(\d+):(\d+):[^"]*"[^>]*name="joNoList"')
_LABEL = re.compile(r"<label[^>]*>(.*?)</label>", re.S)
_LABEL_SPAN = re.compile(r'<span class="bl">.*?</span>', re.S)
_TITLE = re.compile(r"제\d+조(?:의\d+)?\s*\((.*)\)\s*", re.S)
_CIRCLED = "①-⑳㉑-㉟㊱-㊿"
_ITEM_HEAD = re.compile(rf"^([{_CIRCLED}]|\d+(?:의\d+)?\.(?!\d))\s*(?=\S)")  # 항·호 머리 뒤 공백을 한 칸으로 통일
_DELETED = re.compile(rf"(?:[{_CIRCLED}]|\d+(?:의\d+)?\.|[가-힣]\.)?\s*삭제")
_DATE_MARK = re.compile(r"<\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.>")
_PENDING = re.compile(r"시행일\s*:?\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.")
_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
_DOTS = str.maketrans({"·": "ㆍ", "‧": "ㆍ", "・": "ㆍ", "∙": "ㆍ"})


def _iso(y: str, m: str, d: str) -> str:
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _plain(fragment: str) -> str:
    """HTML 조각 → 텍스트. NFC로 호환 한자를 통합 한자로 맞춘다(略 U+F976 → U+7565)."""
    s = re.sub(r"<br\s*/?>", " ", fragment)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    s = unicodedata.normalize("NFC", s).translate(_QUOTES)
    return re.sub(r"\s+", " ", s).strip()


def _para_text(inner: str) -> str:
    """문단 하나 → 본문 한 줄. 연혁 표기는 떼되, 삭제된 항·호는 원문 표시대로 '삭제 <날짜>'를 남긴다."""
    marks = [_plain(x) for x in _SFON.findall(inner)]
    text = _plain(_SFON.sub("", inner))
    if _DELETED.fullmatch(text):
        date = next((x for x in marks if _DATE_MARK.fullmatch(x)), "")
        if date:
            text = f"{text} {date}"
    return _ITEM_HEAD.sub(r"\1 ", text)


def parse_version(body: str) -> LawVersion:
    def hidden(key: str) -> str:
        m = re.search(rf'id="{key}"[^>]*value="([^"]*)"', body)
        return html.unescape(m.group(1)) if m else ""

    first = body.find('<div class="pgroup"')  # 머리말은 첫 조문 묶음 앞에 있다
    head_text = re.sub(r"<(script|style).*?</\1>", " ", body[: first if first != -1 else len(body)], flags=re.S)
    m = _HEAD.search(_plain(head_text))
    if not m:
        raise FetchError("본문 머리말([시행 …] [법률 제…호, …])을 찾지 못함")
    return LawVersion(
        name=hidden("lsNm"),
        effective=_iso(*m.group(1, 2, 3)),
        promulgated=_iso(*m.group(5, 6, 7)),
        number=re.sub(r"\s+", " ", m.group(4)).strip(),
        kind=m.group(8),
        law_id=hidden("lsId"),
        lsi_seq=hidden("lsiSeq"),
    )


def parse_articles(body: str) -> dict[str, OfficialArticle]:
    """lsInfoR 본문 HTML → {조문번호: OfficialArticle}. 부칙·장절 제목은 제외."""
    cut = body.find('<div id="arDivArea"')  # 부칙 영역 시작
    main = body[:cut] if cut != -1 else body
    today = _today()
    out: dict[str, OfficialArticle] = {}
    for g in _PGROUP.finditer(main):
        blk = g.group(1)
        start = blk.find('<div class="lawcon">')
        jo = _JO.search(blk)
        if start == -1 or not jo:
            continue  # 장·절 제목 등 조문이 아닌 묶음
        blk = blk[start:]
        num, branch = (int(x) for x in (jo.group(1) or jo.group(3), jo.group(2) or jo.group(4)))
        art_id = f"제{num}조" + (f"의{branch}" if branch else "")
        label = _LABEL.search(blk)
        tm = _TITLE.fullmatch(_plain(label.group(1))) if label else None
        lines: list[str] = []
        warnings: list[str] = []
        for i, p in enumerate(_PARA.finditer(blk)):
            inner = p.group(1)
            if i == 0:
                inner = _LABEL_SPAN.sub("", inner, count=1)  # '제N조(제목)' 라벨은 본문이 아님
            if "<img" in inner:
                warnings.append("본문에 이미지(수식 등) 포함 — 텍스트로 옮겨지지 않음")
            line = _para_text(inner)
            if line:
                lines.append(line)
        if tm is None and lines and lines[0].startswith("삭제"):
            continue  # 조 전체가 삭제된 자리('제N조 삭제 <날짜>') — 보유 조문이면 '현행 본문에 없음'으로 보고된다
        if "<table" in blk:
            warnings.append("본문에 표 포함 — 텍스트로 옮겨지지 않음")
        notes = [n for n in (_plain(x) for x in _SFON.findall(blk)) if n]
        for n in notes:
            for d in _PENDING.finditer(n):
                if _iso(*d.groups()) > today:
                    warnings.append(f"아직 시행 전인 부분 있음 — {n}")
        if art_id in out:
            out[art_id].warnings.append("같은 조문번호가 본문에 두 번 나옴(시행일별 병기 가능)")
            continue
        out[art_id] = OfficialArticle(art_id, tm.group(1).strip() if tm else "", "\n".join(lines), notes, warnings)
    return out


def normalize(s: str) -> str:
    """대조용 정규화 — 공백·가운뎃점 글리프·따옴표 모양·한자 호환형 차이만 무시한다."""
    s = unicodedata.normalize("NFC", html.unescape(s)).translate(_QUOTES).translate(_DOTS)
    return re.sub(r"\s+", "", s)


# ---------------------------------------------------------------- 데이터 파일
def _read(path: Path) -> tuple[list[dict], str]:
    raw = path.read_bytes().decode("utf-8")
    return json.loads(raw), ("\r\n" if "\r\n" in raw else "\n")


def _write(path: Path, items: list[dict], newline: str) -> None:
    # 기존 서식 유지: 조문 하나가 한 줄(공백 없는 구분자) → 조문 단위 diff가 깔끔하다
    rows = ["  " + json.dumps(it, ensure_ascii=False, separators=(",", ":")) for it in items]
    path.write_bytes(("[" + newline + ("," + newline).join(rows) + newline + "]" + newline).encode("utf-8"))


def data_files(data_dir: Path) -> list[Path]:
    return sorted(p for p in data_dir.glob("*.json") if not p.name.startswith("_"))


def load_versions(data_dir: Path) -> dict[str, dict]:
    p = data_dir / VERSIONS_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ---------------------------------------------------------------- 대조·갱신
def _diff_lines(ours: str, official: str, limit: int = 12) -> list[str]:
    a, b = normalize(ours), normalize(official)
    ops = [o for o in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if o[0] != "equal"]
    out = [f"      …{a[max(0, i1 - 16):i1]}【{a[i1:i2][:90]}】→【{b[j1:j2][:90]}】" for _, i1, i2, j1, j2 in ops[:limit]]
    if len(ops) > limit:
        out.append(f"      (외 {len(ops) - limit}곳)")
    return out


def sync(data_dir: Path, write: bool, rewrite_all: bool, verbose: bool, only: set[str]) -> int:
    files = {p: _read(p) for p in data_files(data_dir)}
    refs: dict[str, str] = {}  # 정식명 → 약칭 (파일에 나온 순서)
    for items, _ in files.values():
        for it in items:
            refs.setdefault(it.get("ref", DEFAULT_REF), it.get("law", DEFAULT_LAW))
    if only:
        refs = {r: law for r, law in refs.items() if law in only}

    recorded = load_versions(data_dir)
    versions = dict(recorded)
    today = _today()
    total = same = changed = missing = 0
    stale_versions: list[str] = []
    dirty: set[Path] = set()
    print(f"=== 법령 현행성 대조 (law.go.kr 현행본 기준, {today}) ===")
    for ref, law in refs.items():
        version, official = fetch_law(ref)
        time.sleep(0.5)  # 요청 간격
        held = [(p, it) for p, (items, _) in files.items() for it in items if it.get("ref", DEFAULT_REF) == ref]
        print(f"\n{law} — 시행 {version.effective} · {version.number}({version.promulgated} {version.kind}) · 보유 {len(held)}조문")
        rec = recorded.get(law, {})
        if (rec.get("effective"), rec.get("number")) != (version.effective, version.number):
            was = f"{rec['effective']} · {rec['number']}" if rec else "없음"
            print(f"  ! 기준 시행본 기록이 현행과 다름 (기록: {was})")
            stale_versions.append(law)
        versions[law] = {
            "name": version.name,
            "effective": version.effective,
            "promulgated": version.promulgated,
            "number": version.number,
            "kind": version.kind,
            "law_id": version.law_id,
            "lsi_seq": version.lsi_seq,
            "checked": today,
        }
        for path, it in held:
            total += 1
            off = official.get(it["id"])
            if off is None or not off.text:
                missing += 1
                print(f"  ✗ {it['id']} — 현행 본문에 없음(삭제·이동 여부 확인 필요)")
                continue
            text_same = normalize(it.get("text", "")) == normalize(off.text)
            title_same = normalize(it.get("title", "")) == normalize(off.title)
            for w in off.warnings:
                print(f"  ⚠ {it['id']} — {w}")
            if text_same and title_same:
                same += 1
            else:
                changed += 1
                what = " · ".join(
                    x for x in ("" if title_same else f"제목 → {off.title}", "" if text_same else "본문") if x
                )
                print(f"  ≠ {it['id']}({it.get('title') or off.title}) — {what}")
                if verbose and not text_same:
                    print("\n".join(_diff_lines(it.get("text", ""), off.text)))
            if not write:
                continue
            before = json.dumps(it, ensure_ascii=False)
            if rewrite_all or not text_same:
                it["text"] = off.text
            if not title_same:
                it["title"] = off.title
            it["source_url"] = law_url(ref, it["id"])
            if json.dumps(it, ensure_ascii=False) != before:
                dirty.add(path)

    drift = changed + missing
    print(f"\n결과: {total}개 조문 — 일치 {same} · 차이 {changed} · 현행 본문에 없음 {missing}")
    if write:
        for p in sorted(dirty):
            _write(p, *files[p])
        (data_dir / VERSIONS_FILE).write_text(
            json.dumps(versions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"갱신: 데이터 파일 {len(dirty)}개 + {VERSIONS_FILE} (조문 {changed}개 본문·제목 반영)")
        if missing:
            print("현행 본문에 없는 조문은 자동으로 고치지 않았습니다 — 직접 확인하세요.")
        return 1 if missing else 0
    if stale_versions:
        print(f"기준 시행본 갱신 필요: {', '.join(stale_versions)}")
    if drift or stale_versions:
        print("→ `python -m scripts.sync_laws --write` 로 현행 원문을 반영하세요.")
        return 1
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows cp949 콘솔 대응
    ap = argparse.ArgumentParser(description="law.go.kr 현행 본문과 data/*.json 대조·갱신")
    ap.add_argument("--write", action="store_true", help="차이 나는 조문을 현행 원문으로 갱신")
    ap.add_argument("--all", action="store_true", help="(--write와 함께) 전 조문 본문을 재생성")
    ap.add_argument("--law", action="append", default=[], help="특정 법령(약칭)만. 여러 번 지정 가능")
    ap.add_argument("-v", "--verbose", action="store_true", help="차이 위치 출력")
    args = ap.parse_args()
    try:
        return sync(DATA_DIR, args.write, args.all, args.verbose, set(args.law))
    except FetchError as e:
        print(f"[수집 실패] {e}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
