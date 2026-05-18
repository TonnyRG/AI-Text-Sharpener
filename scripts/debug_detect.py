"""Quick visual sanity check for detect_text() on the cover page."""
from ai_text_sharpener.detect import detect_text

IMG = r"E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra\image1.jpg"

regions = detect_text(IMG)
print(f"Detected {len(regions)} text regions:\n")
for i, r in enumerate(regions):
    print(f"  [{i:2d}] conf={r.confidence:.2f}  text={r.text!r}")
