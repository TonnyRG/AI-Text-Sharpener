from ai_text_sharpener.detect import TextRegion
from ai_text_sharpener.merge import merge_horizontal_neighbors


def _r(x, y, w, h, text, conf=0.99):
    return TextRegion(
        bbox=[[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
        text=text,
        confidence=conf,
    )


def test_merge_returns_list_of_regions():
    out = merge_horizontal_neighbors([_r(0, 0, 100, 50, "A")])
    assert isinstance(out, list)
    assert len(out) == 1


def test_merge_same_row_adjacent_bboxes_are_combined():
    """OCR may split a single line into two close bboxes; merge them."""
    a = _r(100, 100, 200, 50, "Hello")
    b = _r(320, 100, 100, 50, "World")  # gap = 20px, h=50
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].text == "Hello World"  # latin-latin boundary -> space
    # merged bbox spans both
    xs = [p[0] for p in out[0].bbox]
    ys = [p[1] for p in out[0].bbox]
    assert min(xs) == 100
    assert max(xs) == 420
    assert min(ys) == 100
    assert max(ys) == 150


def test_merge_keeps_separate_rows_separate():
    """Regions on different rows must not be merged."""
    top = _r(100, 100, 200, 50, "Title")
    bottom = _r(100, 300, 200, 50, "Body")  # y-center 125 vs 325, no overlap
    out = merge_horizontal_neighbors([top, bottom])
    assert len(out) == 2


def test_merge_keeps_far_apart_same_row_separate():
    """Same row but with a huge horizontal gap: keep separate."""
    a = _r(100, 100, 100, 50, "A")
    b = _r(2000, 100, 100, 50, "B")  # gap = 1800, way more than 2*h=100
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 2


def test_merge_uses_minimum_confidence():
    a = _r(100, 100, 100, 50, "Lo", conf=0.95)
    b = _r(210, 100, 100, 50, "Hi", conf=0.60)  # gap=10, merge
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].confidence == 0.60


def test_merge_three_consecutive_segments():
    """The image1 case: 'Shiny-preADME' / 'Shiny' / '的' on one row."""
    a = _r(100, 100, 200, 80, "Shiny-preADME：基于RS")
    b = _r(320, 100, 200, 80, "Shiny")
    c = _r(540, 100, 100, 80, "的")
    out = merge_horizontal_neighbors([a, b, c])
    assert len(out) == 1
    # Latin/Latin border gets a space; CJK boundary does not.
    assert out[0].text == "Shiny-preADME：基于RS Shiny的"


def test_merge_adds_space_between_latin_segments():
    a = _r(100, 100, 100, 50, "RS")
    b = _r(220, 100, 200, 50, "Shiny")  # gap=20, latin-latin boundary
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].text == "RS Shiny"


def test_merge_no_space_at_cjk_boundary():
    a = _r(100, 100, 100, 50, "基于")
    b = _r(220, 100, 200, 50, "测试")
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].text == "基于测试"


def test_merge_no_space_when_one_side_is_cjk():
    a = _r(100, 100, 100, 50, "Shiny")
    b = _r(220, 100, 100, 50, "的")  # latin-CJK, no space
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].text == "Shiny的"


def test_merge_does_not_combine_single_cjk_with_far_digits():
    """The image1 bottom case: ornament '画' should not merge with '2026年5月'."""
    a = _r(3438, 3345, 128, 112, "画")
    b = _r(3754, 3333, 344, 130, "2026")  # gap=188, height~120, ratio=1.57
    out = merge_horizontal_neighbors([a, b])
    # With gap_ratio=1.0, gap 188 > 1.0 * 112 = 112, must stay separate.
    assert len(out) == 2
