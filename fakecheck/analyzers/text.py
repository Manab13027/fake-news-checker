
from dataclasses import dataclass
from ..utils import is_probably_sensational

@dataclass
class SectionScore:
    score: float
    max_score: float
    notes: str

class TextAnalyzer:
    def __init__(self):
        self.max_score = 30.0

    def score(self, text:str) -> SectionScore:
        if not text:
            return SectionScore(0.0, self.max_score, "No text provided.")
        sens = is_probably_sensational(text)
        s = self.max_score * (1.0 - sens)
        note = f"Sensationalism heuristic={sens:.2f}. Fewer exclamations/caps/sensational words increases credibility."
        return SectionScore(s, self.max_score, note)
