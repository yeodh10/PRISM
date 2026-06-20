"""개인정보·보안 뉴스 — 데일리시큐 RSS 수집 + 기사 og:image 보강(캐시).

PRISM 법령 답변(검색 조문 근거)과는 별개인 '정보성' 외부 뉴스 탭.
- RSS에서 제목·원문링크·작성자(dc:creator)·일자 수집, 개인정보/보안 키워드 우선 필터
- 각 기사 og:image를 병렬 fetch해 썸네일 보강(로고 이미지 제외)
- 견고성: SSRF 방어(사설/루프백/링크로컬 IP 차단), 응답 크기 상한, 단일비행 캐시(락), 로깅
- API 키 불필요. 실패·빈결과 시 직전 캐시로 안전 폴백.
"""
import ipaddress
import logging
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx

from app.config import settings

logger = logging.getLogger("prism")

_NS = {"dc": "http://purl.org/dc/elements/1.1/"}
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_KEYWORDS = (
    "개인정보", "프라이버시", "정보보호", "개인정보위", "마이데이터", "가명정보",
    "영상정보", "CCTV", "유출", "해킹", "랜섬", "침해", "GDPR", "사생활",
)
_MAX_BYTES = 2_000_000  # 외부 응답 본문 상한(2MB) — og:image 메타 탐지엔 충분, OOM 방지
_CACHE_N = 15  # 캐시에 보관할 최대 항목(반환 시 limit으로 슬라이스)
_Q = chr(34) + chr(39)  # " 와 '
_QCLS, _NCLS = "[" + _Q + "]", "[^" + _Q + "]"

_cache: dict = {"t": 0.0, "items": []}
_lock = threading.Lock()  # 콜드/만료 시 단일비행(스탬피드 방지)


def _is_public_host(host: str) -> bool:
    """호스트가 공인 IP로 resolve되는지 — 사설/루프백/링크로컬/예약 IP면 차단(SSRF 방어).

    (참고: DNS rebinding까지 완전 차단하려면 resolve한 IP로 직접 연결해야 하나,
     데모 범위에서는 호스트 단위 검증으로 메타데이터/내부망 접근을 막는다.)
    """
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


def _og_image(html: str) -> str:
    """HTML에서 og:image / twitter:image 추출(로고로 보이는 이미지는 제외)."""
    for m in re.finditer(r"<meta\b[^>]*>", html, re.I):
        t = m.group(0)
        prop = re.search(r"(?:property|name)\s*=\s*" + _QCLS + r"(" + _NCLS + r"+)", t, re.I)
        cont = re.search(r"content\s*=\s*" + _QCLS + r"(" + _NCLS + r"*)", t, re.I)
        if prop and cont and prop.group(1).lower() in ("og:image", "twitter:image"):
            url = cont.group(1).strip()
            if url and "logo" not in url.lower():
                return url
    return ""


def _enrich(item: dict) -> dict:
    try:
        body = _safe_fetch(item["link"], settings.news_http_timeout)
        if body:
            item["image"] = _og_image(body.decode("utf-8", errors="replace"))
    except Exception as e:
        logger.debug("news og:image fetch 실패 %s: %s", item.get("link"), e)
    return item


def _fetch_and_build() -> list[dict]:
    body = _safe_fetch(settings.news_rss_url, settings.news_http_timeout)
    if not body:
        logger.warning("news: RSS 응답 없음/차단 (%s)", settings.news_rss_url)
        return []
    root = ET.fromstring(body)
    raw: list[dict] = []
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        author = (it.findtext("dc:creator", namespaces=_NS) or it.findtext("author") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        if title and link:
            raw.append({
                "title": title, "link": link, "author": author,
                "source": "데일리시큐", "pubDate": pub, "image": "",
            })
    relevant = [x for x in raw if any(k in x["title"] for k in _KEYWORDS)]
    picked = (relevant or raw)[:_CACHE_N]
    with ThreadPoolExecutor(max_workers=settings.news_max_workers) as ex:  # og:image 병렬
        picked = list(ex.map(_enrich, picked))
    return picked


def get_news(limit: int = 10) -> list[dict]:
    now = time.time()
    if _cache["items"] and now - _cache["t"] < settings.news_cache_ttl:
        return _cache["items"][:limit]
    with _lock:  # 단일비행: 한 스레드만 갱신, 나머지는 갱신 후 캐시 사용
        now = time.time()
        if _cache["items"] and now - _cache["t"] < settings.news_cache_ttl:
            return _cache["items"][:limit]
        try:
            picked = _fetch_and_build()
            if picked:  # 성공·비어있지 않을 때만 캐시 교체(빈결과면 직전 캐시 유지)
                _cache["items"] = picked
                _cache["t"] = now
            else:
                logger.warning("news: 파싱 결과 0건 — 기존 캐시 유지")
        except Exception as e:
            logger.warning("news fetch 실패: %s", e)
        return _cache["items"][:limit]
