import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

# A realistic desktop UA helps avoid some bot blocks.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120 Safari/537.36"
)

# Phrases that indicate we didn't get real article/tweet content
GENERIC_MARKERS = [
    "log in",
    "sign up",
    "something went wrong",
    "try again",
    "join x today",
    "don’t miss what’s happening",
    "you’re offline",
    "enable cookies",
]


def _looks_generic(text: str) -> bool:
    """Return True if the extracted text looks like a login/placeholder stub."""
    t = (text or "").lower().strip()
    return any(m in t for m in GENERIC_MARKERS) or len(t) < 120


def resolve_url(url: str) -> str:
    """
    Follow redirects/shorteners and return the final URL if reachable.
    Falls back to the original URL on any error.
    """
    if not url:
        return url
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=8, allow_redirects=True)
        return r.url or url
    except Exception:
        return url


def fetch_text(url: str):
    """
    Fetch and extract readable text from a web page.

    Returns:
      (final_url, extracted_text)

    Rules:
      - For X/Twitter (x.com/twitter.com), return empty text (login-walled),
        so we don't "pretend" to have tweet content without an API.
      - Extract title, meta description, headings, and first paragraphs.
      - If we only captured a login/placeholder, return empty text.
    """
    if not url:
        return (url, "")

    host = urlparse(url).netloc.lower().split(":")[0]
    if host in {"x.com", "twitter.com"}:
        # Skip: tweets are login-walled; rely on pasted text or API instead
        return (url, "")

    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        html = resp.text or ""
        soup = BeautifulSoup(html, "html5lib")

        pieces = []

        # <title>
        if soup.title and soup.title.text:
            pieces.append(soup.title.text.strip())

        # <meta name="description"...>
        md = soup.find("meta", attrs={"name": "description"})
        if md and md.get("content"):
            pieces.append(md["content"].strip())

        # Headlines
        for tag in soup.find_all(["h1", "h2", "h3"]):
            t = tag.get_text(" ", strip=True)
            if t:
                pieces.append(t)

        # First paragraphs (limit total length to keep things snappy)
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if t and len(t) > 60:
                pieces.append(t)
            if len(" ".join(pieces)) > 1800:
                break

        text = re.sub(r"\s+", " ", " ".join(pieces)).strip()

        # If it looks like a stub/login page, don't use it
        if _looks_generic(text):
            return (resp.url or url, "")

        return (resp.url or url, text[:4000])

    except Exception:
        return (url, "")
