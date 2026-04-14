
from dataclasses import dataclass
import os, subprocess, json

@dataclass
class SectionScore:
    score: float
    max_score: float
    notes: str

class VideoAnalyzer:
    def __init__(self):
        self.max_score = 10.0

    def _ffprobe(self, path:str):
        try:
            out = subprocess.check_output(
                ["ffprobe","-v","error","-show_format","-show_streams","-print_format","json", path],
                stderr=subprocess.STDOUT, text=True
            )
            return json.loads(out)
        except Exception:
            return None

    def score(self, video_path:str=None) -> SectionScore:
        if not video_path or not os.path.exists(video_path):
            return SectionScore(0.0, self.max_score, "No video or path not found.")
        size_mb = os.path.getsize(video_path) / (1024*1024)
        meta = self._ffprobe(video_path)
        base = self.max_score * 0.6
        note = f"File size≈{size_mb:.1f}MB."
        if meta:
            try:
                streams = meta.get("streams", [])
                vstreams = [s for s in streams if s.get("codec_type")=="video"]
                fps_note = ""
                if vstreams:
                    st = vstreams[0]
                    width = st.get("width")
                    height = st.get("height")
                    r = st.get("r_frame_rate","0/0")
                    fps = 0.0
                    if "/" in r:
                        num, den = r.split("/")
                        den = float(den) if float(den)!=0 else 1.0
                        fps = float(num)/den
                    fps_note = f", {width}x{height}, fps≈{fps:.1f}"
                    if width and height and 2 <= fps <= 120:
                        base = self.max_score * 0.75
                note += f" ffprobe ok{fps_note}."
            except Exception:
                note += " ffprobe parse error."
        else:
            note += " ffprobe not found; using basic heuristics."
        return SectionScore(base, self.max_score, note)
