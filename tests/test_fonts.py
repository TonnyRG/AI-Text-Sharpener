from ai_text_sharpener.fonts import assign_fonts, FontSpec


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
