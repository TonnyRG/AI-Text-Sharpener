"""Quick visual sanity check for detect + style + soft_erase on the cover page."""
from pathlib import Path

import numpy as np
from PIL import Image

from ai_text_sharpener.detect import detect_text
from ai_text_sharpener.erase import soft_erase
from ai_text_sharpener.style import extract_style

IMG = r"E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra\image1.jpg"
OUT = Path(__file__).parent / "debug_erased.png"

regions = detect_text(IMG)
print(f"Detected {len(regions)} text regions:\n")
for i, r in enumerate(regions):
    print(f"  [{i:2d}] conf={r.confidence:.2f}  text={r.text!r}")

img = np.array(Image.open(IMG).convert("RGB"))
styled = [(r, extract_style(img, r)) for r in regions]
erased = soft_erase(img, styled)
Image.fromarray(erased).save(OUT)
print(f"\nErased image saved to: {OUT}")
