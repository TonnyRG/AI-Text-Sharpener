import os
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"

SAMPLE_IMAGE_CANDIDATES = [
    Path(os.environ["ATS_PPT_SRC"]) if os.environ.get("ATS_PPT_SRC") else None,
    Path(r"E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra"),
    Path(r"F:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra"),
    Path(r"D:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra"),
]


def _sample_images_dir() -> Path:
    for candidate in SAMPLE_IMAGE_CANDIDATES:
        if candidate and candidate.exists():
            return candidate
    pytest.skip("Sample image directory not found; set ATS_PPT_SRC to run image tests")


@pytest.fixture(scope="session")
def sample_image_path():
    """Return path to a representative sample image (image1.jpg - cover page)."""
    src = _sample_images_dir() / "image1.jpg"
    if not src.exists():
        pytest.skip(f"Sample image not found: {src}")
    return src


@pytest.fixture(scope="session")
def sample_image_chart():
    """Return path to a chart-containing image (image10.jpg)."""
    src = _sample_images_dir() / "image10.jpg"
    if not src.exists():
        pytest.skip(f"Sample image not found: {src}")
    return src
