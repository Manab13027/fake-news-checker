from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
import os

from .analyzers.text import TextAnalyzer
from .analyzers.source import SourceAnalyzer
from .analyzers.image import ImageAnalyzer
from .analyzers.video import VideoAnalyzer
from .analyzers.social import SocialAnalyzer
from .net import fetch_text, resolve_url

# Optional: internet corroboration (SerpAPI/Bing + Google Fact Check)
# If the file isn't present or keys aren't set, OSINT gracefully disables itself.
try:
    from .online.corroborator import Corroborator  # noqa: F401
except Exception:  # pragma: no cover
    Corroborator = None


@dataclass
class SectionScore:
    score: float
    max_score: float
    notes: str


class FakeCheckPipeline:
    """
    Aggregates analyzers into a confidence score (0–100; higher = more credible).

    Key behaviors:
      - Normalizes only over sections actually present (source/text/image/video).
      - For URLs: fetches article text for NON-X/Twitter pages when user didn't paste text.
      - Social is applied as a ± adjustment AFTER normalization (and is also exposed in sections for template compatibility).
      - Optional OSINT internet scan can adjust score (±25 by default) with evidence links.

    Environment variables (PowerShell `set ...=...`):
      ONLINE_SCAN=1                # enable OSINT scan (default 1)
      OSINT_MAX_ADJ=25            # clamp for OSINT adjustment (default 25)
      SERPAPI_API_KEY=...         # OR BING_SUBSCRIPTION_KEY=...
      BING_SUBSCRIPTION_KEY=...   # (use one of the two search providers)
      GOOGLE_FACTCHECK_API_KEY=...# optional (Google Fact Check Tools API)
    """

    def __init__(self):
        self.text_an = TextAnalyzer()
        self.source_an = SourceAnalyzer()
        self.image_an = ImageAnalyzer()
        self.video_an = VideoAnalyzer()
        self.social_an = SocialAnalyzer()

        # Base weights for normalization (do NOT include social/osint here)
        self.weights = {
            "source": 40.0,
            "text": 30.0,
            "image": 20.0,
            "video": 10.0,
        }

        # Adjustments applied after normalization
        self.social_cap = 10.0
        try:
            self.osint_cap = float(os.getenv("OSINT_MAX_ADJ", "25"))
        except Exception:
            self.osint_cap = 25.0

        self.online_scan = os.getenv("ONLINE_SCAN", "1") != "0"

    # ---- helpers ----

    def _is_twitter(self, url: Optional[str]) -> bool:
        if not url:
            return False
        host = urlparse(url).netloc.lower().split(":")[0]
        return host in {"x.com", "twitter.com"}

    # ---- main ----

    def run(
        self,
        text: Optional[str] = None,
        url: Optional[str] = None,
        image_path: Optional[str] = None,
        video_path: Optional[str] = None,
    ) -> Dict[str, Any]:

        # Resolve redirects/shorteners if present
        resolved_url = resolve_url(url) if url else None

        # Fetch page text if needed (skip X/Twitter — login-walled)
        fetched_text = None
        if resolved_url and not (text and text.strip()) and not self._is_twitter(resolved_url):
            _, fetched = fetch_text(resolved_url)
            fetched_text = fetched or None

        # ----- Run analyzers -----
        sections: Dict[str, SectionScore] = {}

        # Source / domain
        sections["source"] = self.source_an.score(url=resolved_url)

        # Text: user-provided text has priority; else use fetched article text
        used_text = (text or "").strip() or (fetched_text or "")
        if used_text:
            sections["text"] = self.text_an.score(text=used_text)
        else:
            note_txt = "No usable text."
            if self._is_twitter(resolved_url):
                note_txt = "No usable text (tweet content needs API or paste the tweet text)."
            sections["text"] = SectionScore(0.0, 30.0, note_txt)

        # Image (optional)
        if image_path:
            sections["image"] = self.image_an.score(image_path=image_path)
        else:
            sections["image"] = SectionScore(0.0, 20.0, "No image provided.")

        # Video (optional)
        if video_path:
            sections["video"] = self.video_an.score(video_path=video_path)
        else:
            sections["video"] = SectionScore(0.0, 10.0, "No video provided.")

        # Social (applied later as ± adjustment)
        social_section = self.social_an.score(url=resolved_url)

        # IMPORTANT for template compatibility:
        # also expose Social inside 'sections' so Jinja can use result.sections.social.*
        sections["social"] = social_section

        # ----- Normalize over present sections only (source/text/image/video) -----
        present_sections: List[str] = []
        if resolved_url:
            present_sections.append("source")
        if used_text:
            present_sections.append("text")
        if image_path:
            present_sections.append("image")
        if video_path:
            present_sections.append("video")

        if not present_sections:
            # If nothing present (e.g., no URL/text/image/video), include 'source' as neutral prior.
            present_sections = ["source"]

        total_weight = sum(self.weights[k] for k in present_sections)
        raw = 0.0
        for k in present_sections:
            s = sections[k].score
            max_s = sections[k].max_score
            w = self.weights[k]
            raw += w * (s / max_s if max_s else 0.0)

        base_score = (raw / total_weight * 100.0) if total_weight else 0.0

        # ----- Optional OSINT corroboration (internet scan) -----
        osint_result = None
        osint_adj = 0.0
        if self.online_scan and Corroborator is not None:
            try:
                corr = Corroborator(
                    serpapi_key=os.getenv("SERPAPI_API_KEY"),
                    bing_key=os.getenv("BING_SUBSCRIPTION_KEY"),
                    factcheck_key=os.getenv("GOOGLE_FACTCHECK_API_KEY"),
                    osint_cap=self.osint_cap,
                )
                # Prefer the most informative string: claim text if present, else the URL
                query_text = used_text if used_text else (resolved_url or "")
                osint_result = corr.check(query_text=query_text, context_url=resolved_url)
                osint_adj = float(osint_result.get("adjustment", 0.0))
                osint_adj = max(min(osint_adj, self.osint_cap), -self.osint_cap)
            except Exception as e:  # non-fatal; keep app resilient
                osint_result = {"error": str(e), "adjustment": 0.0}

        # ----- Social adjustment -----
        social_adj = max(min(social_section.score, self.social_cap), -self.social_cap)

        # ----- Final score -----
        final_score = base_score + social_adj + osint_adj
        final_score = max(min(final_score, 100.0), 0.0)

        # Build markdown report
        md = self._markdown_report(
            sections=sections,
            final_score=final_score,
            url=resolved_url,
            social=social_section,
            osint=osint_result,
            present_sections=present_sections,
        )

        return {
            "inputs": {
                "text": text,
                "url": url,
                "resolved_url": resolved_url,
                "fetched_text_snippet": (used_text[:300] if used_text else None),
                "image_path": image_path,
                "video_path": video_path,
            },
            "sections": {k: asdict(v) for k, v in sections.items()},
            # convenience top-level keys (optional to use in templates)
            "social": asdict(social_section),
            "osint": osint_result,
            "final_confidence": round(final_score, 2),
            "confidence_scale": "0 (not credible) … 100 (highly credible)",
            "markdown_report": md,
        }

    def _markdown_report(
        self,
        sections: Dict[str, SectionScore],
        final_score: float,
        url: Optional[str] = None,
        social: Optional[SectionScore] = None,
        osint: Optional[Dict[str, Any]] = None,
        present_sections: Optional[List[str]] = None,
    ) -> str:
        def line(s: SectionScore, name: str, maxv: float) -> str:
            return f"- **{name}**: {s.score:.1f}/{maxv} — {s.notes}"

        evidence_md = ""
        if osint and isinstance(osint, dict):
            verdict = str(osint.get("verdict", "unknown")).capitalize()
            explanation = osint.get("explanation", "")
            hits = osint.get("evidence", []) or []
            if hits:
                bullets: List[str] = []
                for h in hits[:8]:
                    title = h.get("title") or h.get("url") or ""
                    src = h.get("source") or ""
                    stance = h.get("stance") or ""
                    url_ = h.get("url")
                    bullet = f"  - [{title}]({url_}) — {src}"
                    if stance:
                        bullet += f" · {stance}"
                    bullets.append(bullet)
                evidence_md = (
                    f"### Internet Scan (OSINT)\n"
                    f"**Verdict:** {verdict}\n\n"
                    f"{explanation}\n\n"
                    f"**Evidence:**\n" + "\n".join(bullets) + "\n"
                )
            elif osint.get("error"):
                evidence_md = f"### Internet Scan (OSINT)\n_Error: {osint['error']}_\n"

        present_str = ", ".join(present_sections or [])

        return f"""# Fake News Checker — Report

**Final Confidence:** **{final_score:.1f}/100** (higher means *more credible*).

**Inputs**: URL: `{url or '-'}`  
**Counted sections:** {present_str or '-'}

## Breakdown
{line(sections['source'], 'Source / Domain', 40)}
{line(sections['text'], 'Content / Text', 30)}
{line(sections['image'], 'Image Forensics', 20)}
{line(sections['video'], 'Video Heuristics', 10)}
- **Social Signals (±10)** — {social.notes if social else '-'}

---
{evidence_md if evidence_md else ''}"""
