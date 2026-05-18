"""Process all 15 PPT images and produce side-by-side comparison."""
import shutil
import time
from pathlib import Path

from ai_text_sharpener.fonts import FontSpec
from ai_text_sharpener.pipeline import sharpen_image

SRC = Path(r"E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra")
DST = Path("examples/before_after")
DST.mkdir(parents=True, exist_ok=True)

spec = FontSpec(title="Microsoft YaHei Bold", body="Microsoft YaHei", title_min_px=40)

t_total_start = time.time()
results = []
for img_path in sorted(SRC.glob("*.jpg")):
    print(f"\nProcessing {img_path.name} ...", flush=True)
    out_png = DST / f"{img_path.stem}_sharpened.png"
    out_svg = DST / f"{img_path.stem}_sharpened.svg"
    shutil.copy(img_path, DST / f"{img_path.stem}_original.jpg")
    t0 = time.time()
    try:
        sharpen_image(img_path, out_png, out_svg, spec)
        dt = time.time() - t0
        print(f"  OK  ({dt:.1f}s)", flush=True)
        results.append((img_path.name, "OK", dt, None))
    except Exception as e:
        dt = time.time() - t0
        print(f"  FAILED ({dt:.1f}s): {e}", flush=True)
        results.append((img_path.name, "FAILED", dt, str(e)))

t_total = time.time() - t_total_start
print(f"\n=== Summary ===")
print(f"Total: {t_total:.1f}s ({t_total/60:.1f} min) for {len(results)} images")
ok = sum(1 for r in results if r[1] == "OK")
print(f"OK: {ok}/{len(results)}, Failed: {len(results)-ok}")
if results:
    avg = sum(r[2] for r in results) / len(results)
    print(f"Avg time/image: {avg:.1f}s")
