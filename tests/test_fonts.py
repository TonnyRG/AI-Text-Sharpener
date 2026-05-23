from ai_text_sharpener.fonts import assign_fonts, effective_title_min_px, FontSpec


def test_assign_fonts_uses_title_for_large_text():
    spec = FontSpec(title="Microsoft YaHei Bold", body="Microsoft YaHei", title_min_px=40)
    sizes = [60, 30, 80, 20]
    fonts = assign_fonts(sizes, spec)
    assert fonts == [
        "Microsoft YaHei Bold",
        "Microsoft YaHei",
        "Microsoft YaHei Bold",
        "Microsoft YaHei",
    ]


def test_assign_fonts_threshold_inclusive():
    spec = FontSpec(title="T", body="B", title_min_px=40)
    assert assign_fonts([40], spec) == ["T"]
    assert assign_fonts([39], spec) == ["B"]


def test_effective_title_min_px_scales_with_image_height():
    spec = FontSpec(title="T", body="B", title_min_px=40, title_min_ratio=0.035)
    assert effective_title_min_px(spec, image_height=4500) == 157


def test_effective_title_min_px_floors_at_absolute():
    spec = FontSpec(title="T", body="B", title_min_px=80, title_min_ratio=0.035)
    assert effective_title_min_px(spec, image_height=1000) == 80


def test_font_spec_default_ratio_is_set():
    spec = FontSpec(title="T", body="B")
    assert spec.title_min_ratio == 0.035
