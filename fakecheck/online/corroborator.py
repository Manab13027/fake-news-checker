import os
import re
import requests
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

# --- Configurable constants -------------------------------------------------

# A compact list of reputable outlets (extend as you need)
HIGH_CRED = {
    "reuters.com","apnews.com","bbc.com","theguardian.com","nytimes.com",
    "washingtonpost.com","wsj.com","economist.com","aljazeera.com",
    "hindustantimes.com","indianexpress.com","thehindu.com","livemint.com",
    "ndtv.com","indiatoday.in","scroll.in",
    "altnews.in","boomlive.in","factcheck.org","politifact.com",
}

# Outlets that frequently publish fact-checks (not exhaustive)
FACT_CHECK_HOSTS = {
    "altnews.in","boomlive.in","factcheck.org","politifact.com","poynter.org",
    "snopes.com","afp.com","fullfact.org","pib.gov.in"
}

# Keywords to infer stance from titles/snippets (VERY rough heuristic)
NEG_WORDS = {"false","fake","fabricated","misleading","debunked","hoax","bogus","scam","rumor"}
POS_WORDS = {"true","correct","accurate","confirmed","verified"}


# --- Helpers ----------------------------------------------------------------

def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""

def _stance_from_text(text: str) -> Optional[str]:
    tl = (text or "").lower()
    if any(w in tl for w in NEG_WORDS):
        return "refuting"
    if any(w in tl for w in POS_WORDS):
        return "supporting"
    return None


# --- Main class --------------------------------------------------------------

class Corroborator:
    """
    Lightweight OSINT helper:
      - Uses SerpAPI *or* Bing Web Search (set one key)
      - Optionally queries Google Fact Check Tools API
      - Returns: score adjustment (−cap…+cap), verdict, explanation, evidence list
    """

    def __init__(
        self,
        serpapi_key: Optional[str],
        bing_key: Optional[str],
        factcheck_key: Optional[str],
        osint_cap: float = 25.0,
        mkt: str = "en-IN",
        results: int = 10,
        timeout: int = 12,
    ):
        if not serpapi_key and not bing_key:
            raise RuntimeError("Corroborator requires SERPAPI_API_KEY or BING_SUBSCRIPTION_KEY.")
        self.serpapi_key = serpapi_key
        self.bing_key = bing_key
        self.factcheck_key = factcheck_key
        self.cap = float(osint_cap)
        self.mkt = mkt
        self.results = max(1, min(int(results), 20))
        self.timeout = timeout

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 FakeNewsCheckerBot/1.0"})

    # -- Web search providers --

    def _serpapi_search(self, q: str) -> List[Dict[str, Any]]:
        params = {"engine": "google", "q": q, "num": self.results, "api_key": self.serpapi_key}
        r = self.session.get("https://serpapi.com/search", params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        out = []
        for it in (data.get("organic_results") or [])[: self.results]:
            out.append({
                "title": it.get("title"),
                "url": it.get("link"),
                "snippet": it.get("snippet"),
                "source": _host(it.get("link",""))
            })
        return out

    def _bing_search(self, q: str) -> List[Dict[str, Any]]:
        headers = {"Ocp-Apim-Subscription-Key": self.bing_key}
        params = {"q": q, "count": self.results, "mkt": self.mkt}
        r = self.session.get("https://api.bing.microsoft.com/v7.0/search", headers=headers, params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        out = []
        for it in (data.get("webPages", {}).get("value", []) or [])[: self.results]:
            out.append({
                "title": it.get("name"),
                "url": it.get("url"),
                "snippet": it.get("snippet"),
                "source": _host(it.get("url",""))
            })
        return out

    # -- Google Fact Check Tools API --
    # Doc: https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search
    def _google_factcheck(self, q: str) -> List[Dict[str, Any]]:
        params = {"query": q, "pageSize": self.results, "languageCode": "en", "key": self.factcheck_key}
        r = self.session.get("https://factchecktools.googleapis.com/v1alpha1/claims:search", params=params, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        out = []
        for cl in data.get("claims", [])[: self.results]:
            base_text = cl.get("text") or ""
            for rev in (cl.get("claimReview") or [])[: self.results]:
                pub = (rev.get("publisher", {}) or {}).get("name") or _host(rev.get("url",""))
                rating = (rev.get("textualRating") or "").lower()
                url = rev.get("url")
                # map rating to stance
                if any(w in rating for w in ["false","incorrect","pants on fire","fake","misleading"]):
                    stance = "refuting"
                elif any(w in rating for w in ["true","correct","accurate"]):
                    stance = "supporting"
                else:
                    stance = "mixed"
                out.append({
                    "title": rev.get("title") or base_text,
                    "url": url,
                    "snippet": rating,
                    "source": pub,
                    "stance": stance
                })
        return out

    # -- Public API --

    def check(self, query_text: str, context_url: Optional[str]) -> Dict[str, Any]:
        """
        Returns:
          {
            'adjustment': -cap..+cap,
            'verdict': 'refuting'|'supporting'|'mixed'|'unknown',
            'explanation': str,
            'evidence': [{title,url,snippet,source,stance?}, ...]
          }
        """
        q = (query_text or "").strip()
        if not q:
            return {"adjustment": 0.0, "verdict": "unknown", "explanation": "No query to search.", "evidence": []}

        evidence: List[Dict[str, Any]] = []

        # 1) Web search
        try:
            if self.serpapi_key:
                web_hits = self._serpapi_search(q)
            else:
                web_hits = self._bing_search(q)
        except Exception as e:
            return {"adjustment": 0.0, "verdict": "unknown", "explanation": f"Search error: {e}", "evidence": []}

        for r in web_hits:
            stance = _stance_from_text((r.get("title") or "") + " " + (r.get("snippet") or "")) or ""
            evidence.append({**r, "stance": stance})

        # 2) Fact check API (optional)
        fc_hits: List[Dict[str, Any]] = []
        if self.factcheck_key:
            try:
                fc_hits = self._google_factcheck(q)
                evidence.extend(fc_hits)
            except Exception:
                pass  # non-fatal

        # 3) Collapse to verdict/adjustment
        refutes = sum(1 for e in evidence if e.get("stance") == "refuting" or e.get("source") in FACT_CHECK_HOSTS and (e.get("stance") or "").startswith("refut"))
        supports = sum(1 for e in evidence if e.get("stance") == "supporting")
        highcred_supports = sum(1 for e in evidence if e.get("source") in HIGH_CRED)

        if refutes >= 1 and refutes >= supports:
            verdict = "refuting"
            adj = -min(self.cap, 8.0 + 5.0 * (refutes - supports) + (4.0 if fc_hits else 0.0))
            explanation = "Multiple reputable sources/fact-checks indicate the claim is false or misleading."
        elif highcred_supports >= 2 or supports >= 3:
            verdict = "supporting"
            adj = min(self.cap, 6.0 + 3.0 * highcred_supports + 1.5 * supports)
            explanation = "Multiple reputable outlets report consistently on this claim."
        elif supports or refutes:
            verdict = "mixed"
            adj = max(min(supports - refutes, 2), -2)  # small swing near zero
            explanation = "Some sources support the claim while others challenge it; treat with caution."
        else:
            verdict = "unknown"
            adj = 0.0
            explanation = "Could not find strong corroboration or refutation."

        return {
            "adjustment": float(adj),
            "verdict": verdict,
            "explanation": explanation,
            "evidence": evidence[: 12],  # trim long lists
        }
