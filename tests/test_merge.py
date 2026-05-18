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
    assert out[0].text == "HelloWorld"  # no automatic spacing
    xs = [p[0] for p in out[0].bbox]
    ys = [p[1] for p in out[0].bbox]
    assert min(xs) == 100
    assert max(xs) == 420
    assert min(ys) == 100
    assert max(ys) == 150


def test_merge_keeps_separate_rows_separate():
    top = _r(100, 100, 200, 50, "Title")
    bottom = _r(100, 300, 200, 50, "Body")
    out = merge_horizontal_neighbors([top, bottom])
    assert len(out) == 2


def test_merge_keeps_far_apart_same_row_separate():
    a = _r(100, 100, 100, 50, "A")
    b = _r(2000, 100, 100, 50, "B")
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 2


def test_merge_uses_minimum_confidence():
    a = _r(100, 100, 100, 50, "Lo", conf=0.95)
    b = _r(210, 100, 100, 50, "Hi", conf=0.60)
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].confidence == 0.60


def test_merge_three_consecutive_segments():
    """OCR splits one visual line into three; merge them verbatim."""
    a = _r(100, 100, 200, 80, "Shiny-preADME：基于RS")
    b = _r(320, 100, 200, 80, "Shiny")
    c = _r(540, 100, 100, 80, "的")
    out = merge_horizontal_neighbors([a, b, c])
    assert len(out) == 1
    # Pure concatenation — text remains OCR-faithful, including any errors.
    assert out[0].text == "Shiny-preADME：基于RSShiny的"


def test_merge_no_space_at_cjk_boundary():
    a = _r(100, 100, 100, 50, "基于")
    b = _r(220, 100, 200, 50, "测试")
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].text == "基于测试"


def test_merge_normalizes_halfwidth_colon_before_cjk():
    """'作者:' + '李南樽' should become '作者：李南樽' to match the rendered
    spacing of OCR-given full-width colons like '专业：制药工程'."""
    a = _r(100, 100, 200, 50, "作者:")
    b = _r(310, 100, 300, 50, "李南樽")
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].text == "作者：李南樽"


def test_merge_keeps_halfwidth_colon_when_next_is_latin():
    """URLs and other latin contexts keep half-width colons untouched."""
    a = _r(100, 100, 100, 50, "http:")
    b = _r(210, 100, 200, 50, "//x")  # latin neighbour
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].text == "http://x"


def test_merge_does_not_combine_single_cjk_with_far_digits():
    """Bottom ornament '画' should not merge with '2026年5月'."""
    a = _r(3438, 3345, 128, 112, "画")
    b = _r(3754, 3333, 344, 130, "2026")
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 2
