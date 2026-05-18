from ai_text_sharpener.detect import detect_text, TextRegion


def test_detect_returns_list_of_regions(sample_image_path):
    regions = detect_text(str(sample_image_path))
    assert isinstance(regions, list)
    assert len(regions) > 0
    assert all(isinstance(r, TextRegion) for r in regions)


def test_text_region_has_required_fields(sample_image_path):
    regions = detect_text(str(sample_image_path))
    r = regions[0]
    assert hasattr(r, "bbox")
    assert hasattr(r, "text")
    assert hasattr(r, "confidence")
    assert len(r.bbox) == 4
    assert 0.0 <= r.confidence <= 1.0


def test_detect_finds_known_text_on_cover(sample_image_path):
    """image1.jpg 是封面页，应能识别出 'Shiny-preADME' 字样。"""
    regions = detect_text(str(sample_image_path))
    all_text = " ".join(r.text for r in regions)
    assert "Shiny" in all_text or "shiny" in all_text.lower()
    assert "ADME" in all_text.upper()
