# fakecheck/analyzers/social.py
from dataclasses import dataclass
from urllib.parse import urlparse

@dataclass
class SectionScore:
    score: float
    max_score: float
    notes: str

TRUSTED_X_HANDLES = {
    # Minimal seed list — extend this to your needs
    "reuters", "ap", "bbcworld", "bbcbreaking",
    "the_hindu", "indianexpress", "livemint", "ndtv",
    "htTweets", "htTweetsIndia", "HindustanTimes".lower(),  # Hindustan Times variants
}

class SocialAnalyzer:
    def __init__(self):
        self.max_score = 10.0  # used as +/- adjustment

    def score(self, url: str = None) -> SectionScore:
        if not url:
            return SectionScore(0.0, self.max_score, "No social context provided.")
        host = urlparse(url).netloc.lower()
        if "twitter.com" in host or "x.com" in host:
            path = urlparse(url).path.strip("/")
            handle = (path.split("/")[0] if path else "").lower()
            if handle in {h.lower() for h in TRUSTED_X_HANDLES}:
                return SectionScore(+4.0, self.max_score, f"X handle=@{handle} (trusted list).")
            elif handle:
                return SectionScore(-2.0, self.max_score, f"X handle=@{handle} (unknown; needs corroboration).")
            else:
                return SectionScore(-2.0, self.max_score, "X link with unknown handle.")
        if "youtube.com" in host or "youtu.be" in host:
            return SectionScore(+2.0, self.max_score, "YouTube link; verify channel authority.")
        return SectionScore(0.0, self.max_score, "No special social heuristics applied.")
