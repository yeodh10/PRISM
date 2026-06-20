"""개인정보·보안 뉴스 — 다매체 RSS 집계(최신순) + 페이지네이션.

PRISM 법령 답변(검색 조문 근거)과는 별개인 '정보성' 외부 뉴스 탭.
- 출처: 구글뉴스 검색(수십 개 매체 집계) + 데일리시큐 + 보안뉴스
- 각 RSS의 제목·원문링크·매체·작성자·일자·이미지(enclosure/media/본문 img) 수집
- 개인정보/보안 키워드 관련성 필터 → 제목 정규화 중복 제거 → pubDate 최신순 → 최대 200건
- 견고성: SSRF 방어(사설/루프백/링크로컬 IP 차단), 응답 크기 상한, 단일비행 캐시(락), 로깅
- API 키 불필요. 실패·빈결과 시 직전 캐시로 안전 폴백.
"""
import html
import ipaddress
import logging
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit

import httpx

from app.config import settings

logger = logging.getLogger("prism")

_NS = {"dc": "http://purl.org/dc/elements/1.1/"}
_MEDIA = "http://search.yahoo.com/mrss/"
_CONTENT = "http://purl.org/rss/1.0/modules/content/"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# 다양한 출처: 구글뉴스 검색(다매체 최신 집계) + 보안 전문지 직접 피드
_GNEWS_Q = '개인정보보호 OR "개인정보 유출" OR 개인정보위원회 OR 프라이버시 OR 정보보호'
_FEEDS = [
    ("구글뉴스", "https://news.google.com/rss/search?q=" + quote(_GNEWS_Q) + "&hl=ko&gl=KR&ceid=KR:ko"),
    ("데일리시큐", settings.news_rss_url),
    ("보안뉴스", "https://www.boannews.com/media/news_rss.xml"),
]
_KEYWORDS = (
    "개인정보", "프라이버시", "정보보호", "개인정보위", "마이데이터", "가명정보",
    "영상정보", "cctv", "유출", "해킹", "랜섬", "침해", "gdpr", "사생활", "보안",
)
_MAX_BYTES = 4_000_000  # 외부 응답 본문 상한(4MB) — RSS 피드 크기 충분, OOM 방지
_MAX_ITEMS = 200        # 최신순 최대 보관(20개 × 10페이지)
_Q = chr(34) + chr(39)  # " 와 '
_QCLS, _NCLS = "[" + _Q + "]", "[^" + _Q + "]"

_cache: dict = {"t": 0.0, "items": []}
_lock = threading.Lock()  # 콜드/만료 시 단일비행(스탬피드 방지)


def _is_public_host(host: str) -> bool:
    """호스트가 공인 IP로 resolve되는지 — 사설/루프백/링크로컬/예약 IP면 차단(SSRF 방어)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return bool(infos)


def _safe_fetch(url: str, timeout: float) -> bytes:
    """http(s)·공인호스트만, 리다이렉트 수동 검증(최대 5홉), 본문 크기 상한. 실패 시 b''."""
    for _ in range(5):
        p = urlsplit(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return b""
        if not _is_public_host(p.hostname):
            logger.warning("news: 비공인 호스트 차단 %s", p.hostname)
            return b""
        with httpx.stream("GET", url, timeout=timeout, headers=_UA, follow_redirects=False) as r:
            if r.is_redirect:
                loc = r.headers.get("location")
                if not loc:
                    return b""
                url = str(httpx.URL(url).join(loc))
                continue
            if r.status_code >= 400:
                return b""
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > _MAX_BYTES:
                    break
            return bytes(buf)
    return b""  # 리다이렉트 과다


def _og_image(html_text: str) -> str:
    """HTML에서 og:image / twitter:image 추출(로고로 보이는 이미지는 제외)."""
    for m in re.finditer(r"<meta\b[^>]*>", html_text, re.I):
        t = m.group(0)
        prop = re.search(r"(?:property|name)\s*=\s*" + _QCLS + r"(" + _NCLS + r"+)", t, re.I)
        cont = re.search(r"content\s*=\s*" + _QCLS + r"(" + _NCLS + r"*)", t, re.I)
        if prop and cont and prop.group(1).lower() in ("og:image", "twitter:image"):
            url = cont.group(1).strip()
            if url and "logo" not in url.lower():
                return url
    return ""


def _img_from_item(it: ET.Element) -> str:
    """RSS item에서 이미지 URL 추출: enclosure → media:content/thumbnail → 본문 <img>."""
    enc = it.find("enclosure")
    if enc is not None and enc.get("url") and "image" in (enc.get("type") or "image"):
        return enc.get("url")
    for tag in (f"{{{_MEDIA}}}content", f"{{{_MEDIA}}}thumbnail"):
        m = it.find(tag)
        if m is not None and m.get("url"):
            return m.get("url")
    body = (it.findtext("description") or "") + (it.findtext(f"{{{_CONTENT}}}encoded") or "")
    m = re.search(r"<img\b[^>]*\bsrc\s*=\s*" + _QCLS + r"(" + _NCLS + r"+)", body, re.I)
    if m:
        u = html.unescape(m.group(1)).strip()
        if u and "logo" not in u.lower():
            return u
    return ""


def _enrich(item: dict) -> dict:
    """기사 페이지 og:image로 썸네일 보강(직접 링크 항목용, 구글뉴스 리다이렉트 제외)."""
    try:
        body = _safe_fetch(item["link"], settings.news_http_timeout)
        if body:
            img = _og_image(body.decode("utf-8", errors="replace"))
            if img:
                item["image"] = img
    except Exception as e:
        logger.debug("news og:image 실패 %s: %s", item.get("link"), e)
    return item


def _ts(pub: str) -> float:
    try:
        return parsedate_to_datetime(pub).timestamp()
    except Exception:
        return 0.0


def _decode_xml(body: bytes) -> str:
    """바이트 RSS를 str로 디코드 — EUC-KR/CP949 등 expat 미지원 인코딩 대응 + prolog의 encoding 선언 제거."""
    enc = "utf-8"
    m = re.search(rb"encoding=[\"']([\w-]+)[\"']", body[:200])
    if m:
        enc = m.group(1).decode("ascii", "ignore").lower()
    text = None
    for e in (enc, "utf-8", "cp949", "euc-kr", "latin-1"):
        try:
            text = body.decode(e)
            break
        except Exception:
            continue
    if text is None:
        text = body.decode("utf-8", "replace")
    return re.sub(r"(<\?xml[^>]*?)\s+encoding=[\"'][\w-]+[\"']", r"\1", text, count=1)


def _parse_feed(body: bytes, default_source: str) -> list[dict]:
    try:
        root = ET.fromstring(_decode_xml(body))
    except ET.ParseError as e:
        logger.warning("news: RSS 파싱 실패(%s): %s", default_source, e)
        return []
    out = []
    for it in root.findall(".//item"):
        title = html.unescape((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        src_el = it.find("source")
        source = (src_el.text.strip() if src_el is not None and src_el.text else default_source)
        # 구글뉴스 제목 끝의 " - 매체명" 제거
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)].strip()
        elif default_source == "구글뉴스" and " - " in title:
            title, _, src2 = title.rpartition(" - ")
            source = src2.strip() or source
        pub = (it.findtext("pubDate") or "").strip()
        out.append({
            "title": title,
            "link": link,
            "author": (it.findtext("dc:creator", namespaces=_NS) or it.findtext("author") or "").strip(),
            "source": source,
            "pubDate": pub,
            "image": _img_from_item(it),
            "ts": _ts(pub),
        })
    return out


def _fetch_and_build() -> list[dict]:
    def fetch(feed):
        name, url = feed
        try:
            body = _safe_fetch(url, settings.news_http_timeout)
            return _parse_feed(body, name) if body else []
        except Exception as e:
            logger.warning("news: 피드 실패(%s): %s", name, e)
            return []

    collected: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(3, settings.news_max_workers)) as ex:
        for lst in ex.map(fetch, _FEEDS):
            collected.extend(lst)

    relevant = [x for x in collected if any(k in x["title"].lower() for k in _KEYWORDS)]
    pool = relevant or collected
    seen, uniq = set(), []
    for x in sorted(pool, key=lambda i: i["ts"], reverse=True):  # 최신순
        key = re.sub(r"\s+", "", x["title"]).lower()[:40]
        if key and key in seen:
            continue
        seen.add(key)
        uniq.append({k: x[k] for k in ("title", "link", "author", "source", "pubDate", "image")})
        if len(uniq) >= _MAX_ITEMS:
            break
    # 직접 링크(구글뉴스 리다이렉트 제외) 상위 항목만 og:image 보강 — 캐시되므로 1회
    targets = [x for x in uniq if not x["image"] and "news.google.com" not in x["link"]][:40]
    if targets:
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(_enrich, targets))
    logger.info("news: %d개 피드 집계 → %d건(최신순), 이미지 %d건",
                len(_FEEDS), len(uniq), sum(1 for x in uniq if x["image"]))
    return uniq


def get_news() -> list[dict]:
    """집계된 전체 뉴스(최신순, 최대 200건). 페이지네이션은 호출측(엔드포인트)에서."""
    now = time.time()
    if _cache["items"] and now - _cache["t"] < settings.news_cache_ttl:
        return _cache["items"]
    with _lock:  # 단일비행
        now = time.time()
        if _cache["items"] and now - _cache["t"] < settings.news_cache_ttl:
            return _cache["items"]
        try:
            items = _fetch_and_build()
            if items:
                _cache["items"] = items
                _cache["t"] = now
            else:
                logger.warning("news: 집계 0건 — 기존 캐시 유지")
        except Exception as e:
            logger.warning("news fetch 실패: %s", e)
        return _cache["items"]
