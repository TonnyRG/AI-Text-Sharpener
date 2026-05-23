"""Text detection wrapper around PaddleOCR 3.x."""
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import List, Tuple


@dataclass
class TextRegion:
    bbox: list          # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]] in pixels
    text: str
    confidence: float


_PROFILE_MODELS = {
    "mobile": ("PP-OCRv5_mobile_det", "PP-OCRv5_mobile_rec"),
    "server": ("PP-OCRv5_server_det", "PP-OCRv5_server_rec"),
}


def _resolve_profile() -> Tuple[str, str]:
    """Return (det_model, rec_model) names for the active OCR profile.

    Controlled by ``ATS_OCR_PROFILE`` env var.  Defaults to ``mobile`` because
    the server profile peaks at ~3-4 GB of RSS on 4K slide images, which
    saturates an 8 GB CPU dev box.  Mobile is ~3-5× faster and uses a fraction
    of the memory at a modest accuracy cost.  Set ``ATS_OCR_PROFILE=server``
    for final renders on a GPU machine.
    """
    profile = os.environ.get("ATS_OCR_PROFILE", "mobile").strip().lower()
    if profile not in _PROFILE_MODELS:
        raise ValueError(
            f"Unknown ATS_OCR_PROFILE={profile!r}. "
            f"Expected one of: {sorted(_PROFILE_MODELS)}"
        )
    return _PROFILE_MODELS[profile]


@lru_cache(maxsize=2)
def _get_ocr(profile_key: Tuple[str, str]):
    """Lazy-init PaddleOCR (loads models on first call).

    PaddleOCR is imported here (not at module top) so the rest of the package
    can be loaded without PaddlePaddle installed — useful for CI on unit tests
    that don't touch detection.

    Notes:
    - mkldnn disabled to avoid a paddlepaddle-3.x Windows-CPU bug
      (NotImplementedError: ConvertPirAttribute2RuntimeAttribute)
    - doc preprocessing turned off; AI-generated images are already upright
    - cache keyed on the model tuple so switching profiles mid-process loads a
      second instance instead of reusing the wrong one.
    """
    from paddleocr import PaddleOCR
    det_model, rec_model = profile_key
    return PaddleOCR(
        text_detection_model_name=det_model,
        text_recognition_model_name=rec_model,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        lang="ch",
        enable_mkldnn=False,
    )


@lru_cache(maxsize=16)
def detect_text(image_path: str) -> List[TextRegion]:
    """Detect all text regions in image. Supports Chinese, English, digits, symbols."""
    ocr = _get_ocr(_resolve_profile())
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
