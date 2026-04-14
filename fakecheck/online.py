import os, time, json, re
from typing import Dict, Any, List, Optional
import requests
from urllib.parse import urlencode, urlparse

# Reputable source tiers (expand as you like):
HIGH_CRED = {
    "reuters.com","apnews.com","bbc.com","theguardian.com","nytimes.com","washingtonpost.com","wsj.com",
    "economist.com","aljazeera.com","hindustantimes.com","indianexpress.com","thehindu.com","livemint.com",
    "ndtv.com","indiatoday.in","scroll.in","altnews.in","boomlive.in","factcheck.org","politifact.com"
}
FACT_CHECK_HOSTS = {
    "altnews.in","boomlive.in","factcheck.org","politifact.com","poynter.org","snopes.com","afp.com",
    "piB.gov.in", "pib.gov.in"  # PIB Fact Check often publishes clarifications
}

NEG_WORDS = {"false","fake","fabricated","misleading","no,","not true","debunked","hoax"}
POS_WORDS = {"true","correct","accurate","confirmed","verified"}

def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split(":")[0]
    except Exception:
        return ""

def _stance_from_text(t: str) -> Optional[str]:
    """Very rough stance heuristic from snippets/titles."""
    tl = t.lower()
    if any(w in tl for w in NEG_WORDS):
        return "refuting"
    if any(w in tl for w in POS_WORDS):
        return "supporting"
    return None

class Corroborator:
    def __init__(self, serpapi_key: Optional[str], bing_key: Optional[str],
                 factcheck_key: Optional[str], osint_cap: float = 25.0):
        self.serpapi_key = serpapi_key
        self.bing_key = bing_key
        self.factcheck_key = factcheck_key
        self.cap = osint_cap
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 FakeNewsCheckerBot/1.0"})

    # ---- Web Search providers ----
    def _serpapi_search(self, q: str) -> List[Dict[str, Any]]:
        params = {"engine": "google", "q": q, "num": 10, "api_key": self.serpapi_key}
        r = self.session.get("https://serpapi.com/search", params=params, timeout=12)
        r.raise_for_status()
        data = r.json()
        out = []
        for it in (data.get("organic_results") or [])[:10]:
            out.append({
                "title": it.get("title"),
                "url": it.get("link"),
                "snippet": it.get("snippet"),
                "source": _host(it.get("link",""))
            })
        return out

    def _bing_search(self, q: str) -> List[Dict[str, Any]]:
        headers = {"Ocp-Apim-Subscription-Key": self.bing_key}
        params = {"q": q, "count": 10, "mkt": "en-IN"}
        r = self.session.get("https://api.bing.microsoft.com/v7.0/search", headers=headers, params=params, timeout=12)
        r.raise_for_status()
        data = r.json()
        out = []
        for it in (data.get("webPages", {}).get("value", []) or [])[:10]:
            out.append({
                "title": it.get("name"),
                "url": it.get("url"),
                "snippet": it.get("snippet"),
                "source": _host(it.get("url",""))
            })
        return out

    # ---- Fact Check API ----
    def _google_factcheck(self, q: str) -> List[Dict[str, Any]]:
        # https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search
        params = {"query": q, "key": self.factcheck_key, "pageSize": 10, "languageCode": "en"}
        r = self.session.get("https://factchecktools.googleapis.com/v1alpha1/claims:search", params=params, timeout=12)
        r.raise_for_status()
        data = r.json()
        out = []
        for cl in data.get("claims", [])[:10]:
            text = cl.get("text") or ""
            for rev in cl.get("claimReview", []) or []:
                publisher = (rev.get("publisher", {}) or {}).get("name") or _host(rev.get("url",""))
                rating = (rev.get("textualRating") or "").lower()
                url = rev.get("url")
                stance = "refuting" if any(w in rating for w in ["false","pants on fire","fake","misleading"]) else (
                         "supporting" if any(w in rating for w in ["true","correct","accurate"]) else "mixed")
                out.append({
                    "title": rev.get("title") or text,
                    "url": url,
                    "snippet": rating,
                    "source": publisher,
                    "stance": stance
                })
        return out

    # ---- Public interface ----
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
        evidence: List[Dict[str, Any]] = []
        verdict = "unknown"
        explanation = ""
        adj = 0.0

        # Gather evidence
        results: List[Dict[str, Any]] = []
        try:
            if self.serpapi_key:
                results = self._serpapi_search(query_text)
            elif self.bing_key:
                results = self._bing_search(query_text)
        except Exception as e:
            return {"adjustment": 0.0, "verdict": "unknown", "explanation": f"Search error: {e}", "evidence": []}

        # Try Fact Check API
        fc_hits: List[Dict[str, Any]] = []
        if self.factcheck_key:
            try:
                fc_hits = self._google_factcheck(query_text)
            except Exception:
                pass

        # Collate evidence
        for r in results:
            stance = _stance_from_text((r.get("title") or "") + " " + (r.get("snippet") or "")) or ""
            evidence.append({**r, "stance": stance})

        evidence.extend(fc_hits)

        # Scoring logic:
        #  - Strong refutes by fact-checkers dominate → negative adjustment
        #  - Multiple HIGH_CRED matching pages → positive adjustment
        #  - Mixed/conflicting → small positive or near zero
        refutes = sum(1 for e in evidence if e.get("stance") == "refuting" or e.get("source") in FACT_CHECK_HOSTS and "refut" in (e.get("stance") or ""))
        supports = sum(1 for e in evidence if e.get("stance") == "supporting")
        highcred_supports = sum(1 for e in evidence if e.get("source") in HIGH_CRED)

        if refutes >= 1 and refutes >= supports:
            verdict = "refuting"
            adj = -min(self.cap, 8.0 + 6.0 * (refutes - supports) + 4.0 * (1 if fc_hits else 0))
            explanation = "Multiple reputable sources/fact-checks indicate the claim is false or misleading."
        elif highcred_supports >= 2 or supports >= 3:
            verdict = "supporting"
            adj = min(self.cap, 6.0 + 3.0 * highcred_supports + 1.5 * supports)
            explanation = "Multiple reputable outlets report consistently on this claim."
        elif supports or refutes:
            verdict = "mixed"
            adj = max(min(supports - refutes, 2), -2)  # small swing
            explanation = "Some sources support the claim while others challenge it; treat with caution."
        else:
            verdict = "unknown"
            adj = 0.0
            explanation = "Could not find strong corroboration or refutation."

        return {
            "adjustment": float(adj),
            "verdict": verdict,
            "explanation": explanation,
            "evidence": evidence
        }
