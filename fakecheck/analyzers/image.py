
from dataclasses import dataclass
from PIL import Image, ImageChops
import piexif, io, os

@dataclass
class SectionScore:
    score: float
    max_score: float
    notes: str

class ImageAnalyzer:
    def __init__(self):
        self.max_score = 20.0

    def _ela_score(self, img:Image.Image) -> float:
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=95)
        resaved = Image.open(io.BytesIO(buf.getvalue()))
        diff = ImageChops.difference(img.convert("RGB"), resaved.convert("RGB"))
        extrema = diff.getextrema()
        mx = sum([m[1] for m in extrema]) / (3*255.0)
        return max(0.0, min(mx, 1.0))

    def score(self, image_path:str=None) -> SectionScore:
        if not image_path or not os.path.exists(image_path):
            return SectionScore(0.0, self.max_score, "No image or path not found.")
        try:
            img = Image.open(image_path)
        except Exception as e:
            return SectionScore(0.0, self.max_score, f"Unable to open image: {e}")

        exif_note = "no EXIF"
        try:
            exif_raw = img.info.get("exif", b"")
            exif_dict = piexif.load(exif_raw) if exif_raw else {}
            if exif_dict and any(exif_dict.get(k) for k in exif_dict.keys()):
                exif_note = "EXIF present"
        except Exception:
            exif_note = "EXIF unreadable"

        ela_anom = self._ela_score(img)
        ela_component = (1.0 - ela_anom)
        exif_boost = 0.1 if exif_note == "EXIF present" else 0.0
        final = max(0.0, min(self.max_score * (0.6*ela_component + exif_boost), self.max_score))

        note = f"ELA anomaly={ela_anom:.2f}; {exif_note}."
        return SectionScore(final, self.max_score, note)
