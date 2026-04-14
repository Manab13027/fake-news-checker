
from dataclasses import dataclass
from urllib.parse import urlparse

@dataclass
class SectionScore:
    score: float
    max_score: float
    notes: str

HIGH_CRED = {
    "reuters.com","apnews.com","bbc.com","indianexpress.com","thehindu.com","thewire.in",
    "altnews.in","boomlive.in","factcheck.org","politifact.com","aljazeera.com","theguardian.com",
    "nytimes.com","washingtonpost.com","wsj.com","economist.com","hindustantimes.com","livemint.com",
    "ndtv.com","indiatoday.in","scroll.in"
}

LOW_CRED = {
    "beforeitsnews.com","yournewswire.com","naturalnews.com","infowars.com","thegatewaypundit.com"
}

PLATFORMS = (".blogspot.com",".substack.com",".wordpress.com",".medium.com")

SHORTENERS = {"t.co","bit.ly","tinyurl.com","goo.gl","ow.ly","is.gd","t.ly","cutt.ly","rb.gy"}

class SourceAnalyzer:
    def __init__(self):
        self.max_score = 40.0

    def score(self, url:str=None) -> SectionScore:
        if not url:
            return SectionScore(self.max_score*0.5, self.max_score, "No URL provided: neutral prior.")
        pu = urlparse(url)
        d = pu.netloc.lower().split(":")[0]
        https = (pu.scheme.lower() == "https")
        base = self.max_score * (0.6 if https else 0.5)
        notes = [f"Domain: {d}", "HTTPS" if https else "HTTP"]

        if d in SHORTENERS:
            notes.append("Shortener domain — credibility depends on target; try resolving.")
            base = self.max_score * (0.55 if https else 0.45)

        if any(d.endswith(p) for p in PLATFORMS):
            notes.append("Publisher platform; credibility varies widely.")
            return SectionScore(self.max_score * 0.55, self.max_score, "; ".join(notes))

        if d in LOW_CRED:
            notes.append("Domain in low-credibility list.")
            return SectionScore(self.max_score * 0.3, self.max_score, "; ".join(notes))

        for hc in HIGH_CRED:
            if d == hc or d.endswith("." + hc):
                notes.append("Matches high-credibility list.")
                return SectionScore(self.max_score * 0.9, self.max_score, "; ".join(notes))

        notes.append("Unknown domain; neutral leaning.")
        return SectionScore(base, self.max_score, "; ".join(notes))
