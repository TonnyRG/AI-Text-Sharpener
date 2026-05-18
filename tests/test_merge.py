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
    b = _r(320, 100, 100, 50, "World")  # gap = 20px, h=50, so gap < 2*h: merge
    out = merge_horizontal_neighbors([a, b])
    assert len(out) == 1
    assert out[0].text == "HelloWorld"
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
    a = _r(100, 100, 200, 80, "AAA")
    b = _r(320, 100, 200, 80, "BBB")  # gap=20 < 2*80
    c = _r(540, 100, 100, 80, "C")    # gap=20 < 2*80
    out = merge_horizontal_neighbors([a, b, c])
    assert len(out) == 1
    assert out[0].text == "AAABBBC"
