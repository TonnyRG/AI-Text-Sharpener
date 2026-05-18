import shutil
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_IMAGES = Path(r"E:\Project\Shiny-PreADME项目辅助\PPT纯生图版_图片\v5_sharpened_extra")


@pytest.fixture(scope="session")
def sample_image_path():
    """Return path to a representative sample image (image1.jpg - cover page)."""
    src = SAMPLE_IMAGES / "image1.jpg"
    if not src.exists():
        pytest.skip(f"Sample image not found: {src}")
    return src


@pytest.fixture(scope="session")
def sample_image_chart():
    """Return path to a chart-containing image (image10.jpg)."""
    src = SAMPLE_IMAGES / "image10.jpg"
    if not src.exists():
        pytest.skip(f"Sample image not found: {src}")
    return src
