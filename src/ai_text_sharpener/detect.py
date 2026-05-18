"""Text detection wrapper around PaddleOCR 3.x."""
from dataclasses import dataclass
from functools import lru_cache
from typing import List

from paddleocr import PaddleOCR


@dataclass
class TextRegion:
    bbox: list          # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] in pixels
    text: str
    confidence: float


@lru_cache(maxsize=1)
def _get_ocr() -> PaddleOCR:
    """Lazy-init PaddleOCR (loads ~500MB models on first call).

    Notes:
    - mkldnn disabled to avoid a paddlepaddle-3.x Windows-CPU bug
      (NotImplementedError: ConvertPirAttribute2RuntimeAttribute)
    - doc preprocessing turned off; AI-generated images are already upright
    """
    return PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        lang="ch",
        enable_mkldnn=False,
    )


@lru_cache(maxsize=16)
def detect_text(image_path: str) -> List[TextRegion]:
    """Detect all text regions in image. Supports Chinese, English, digits, symbols."""
    ocr = _get_ocr()
    result = ocr.predict(image_path)
    if not result:
        return []

    r0 = result[0]
    polys = r0.get("rec_polys") or r0.get("dt_polys") or []
    texts = r0.get("rec_texts") or []
    scores = r0.get("rec_scores") or []

    regions: List[TextRegion] = []
    for poly, text, score in zip(polys, texts, scores):
        bbox = poly.tolist() if hasattr(poly, "tolist") else list(poly)
        regions.append(TextRegion(bbox=bbox, text=text, confidence=float(score)))
    return regions
