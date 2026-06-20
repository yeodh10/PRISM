"""뉴스 유틸 — og:image 추출, SSRF 호스트 검증(네트워크 불필요: IP 리터럴 사용)."""
from app.news import _is_public_host, _og_image


def test_og_image_extracted():
    assert _og_image('<meta property="og:image" content="https://x.com/a.jpg">') == "https://x.com/a.jpg"


def test_og_image_logo_excluded():
    assert _og_image('<meta property="og:image" content="https://x.com/logo.png">') == ""


def test_og_image_none():
    assert _og_image("<html><body>no meta</body></html>") == ""


def test_loopback_blocked():
    assert _is_public_host("127.0.0.1") is False


def test_private_and_metadata_blocked():
    assert _is_public_host("10.0.0.1") is False
    assert _is_public_host("169.254.169.254") is False  # 클라우드 메타데이터 엔드포인트


def test_public_ip_allowed():
    assert _is_public_host("8.8.8.8") is True
