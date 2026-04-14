
import re
from urllib.parse import urlparse

SENSATIONAL_WORDS = set([
    "shocking","you won't believe","breaking","must see","exposed","secret","banned",
    "miracle","cure","instant","guaranteed","scandal","viral","explosive"
])

def domain_from_url(u:str):
    try:
        n = urlparse(u).netloc.lower()
        return n.split(":")[0]
    except Exception:
        return ""

def is_probably_sensational(text:str):
    if not text: return 0
    t = text.lower()
    score = 0
    if any(w.isupper() and len(w) > 4 for w in text.split()):
        score += 0.2
    exclaims = text.count("!")
    if exclaims >= 3:
        score += 0.3
    if any(w in t for w in SENSATIONAL_WORDS):
        score += 0.3
    if re.search(r"\b(recently|soon|some time ago|a while back|soon)\b", t):
        score += 0.2
    return min(score, 1.0)
