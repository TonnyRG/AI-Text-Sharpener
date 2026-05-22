"""Tests for per-glyph position estimation."""
from __future__ import annotations

import numpy as np

from ai_text_sharpener.glyph_layout import (
    _find_ink_islands,
    _ink_projection,
    glyph_centers_from_projection,
    measure_glyph_centers,
)


def _bar_image(bar_x_ranges, height=40, width=400, ink_color=0, bg=255):
    """White image with black vertical bars at given x ranges."""
    img = np.full((height, width, 3), bg, dtype=np.uint8)
    for x0, x1 in bar_x_ranges:
        img[5:height - 5, x0:x1] = ink_color
    return img


def test_ink_projection_picks_up_dark_bars():
    img = _bar_image([(10, 20), (60, 70), (110, 120)])
    proj = _ink_projection(img)
    assert proj.shape == (img.shape[1],)
    # Columns inside the bars should have notably higher ink mass than gaps
    assert proj[15] > 50 * proj[40]


def test_find_ink_islands_returns_one_per_bar():
    img = _bar_image([(10, 20), (60, 70), (110, 120)])
    proj = _ink_projection(img)
    islands = _find_ink_islands(proj)
    assert len(islands) == 3
    starts = [s for s, _ in islands]
    assert starts[0] < starts[1] < starts[2]


def test_glyph_centers_match_bar_centers():
    bars = [(10, 30), (60, 80), (120, 140), (180, 200)]
    img = _bar_image(bars)
    centers = measure_glyph_centers(
        img,
        bbox_quad=[[0, 0], [img.shape[1], 0],
                   [img.shape[1], img.shape[0]], [0, img.shape[0]]],
        n_glyphs=len(bars),
    )
    assert len(centers) == len(bars)
    expected_centers = [(a + b) // 2 for a, b in bars]
    for got, want in zip(centers, expected_centers):
        assert abs(got - want) <= 2, f"center {got} not near {want}"


def test_glyph_centers_with_inter_word_gap():
    # "ABC DEF": 3 bars, big gap, 3 bars
    img = _bar_image([(10, 30), (50, 70), (90, 110),  # ABC
                      (200, 220), (240, 260), (280, 300)])  # DEF
    centers = measure_glyph_centers(
        img,
        bbox_quad=[[0, 0], [img.shape[1], 0],
                   [img.shape[1], img.shape[0]], [0, img.shape[0]]],
        n_glyphs=6,
    )
    assert len(centers) == 6
    # First three should be left of the gap, last three to the right
    assert max(centers[:3]) < min(centers[3:])
    # All centers should land inside their corresponding bars
    expected = [20, 60, 100, 210, 250, 290]
    for got, want in zip(centers, expected):
        assert abs(got - want) <= 3


def test_glyph_centers_empty_ink_falls_back_to_even_spacing():
    img = np.full((40, 200, 3), 255, dtype=np.uint8)  # all-white, no ink
    centers = measure_glyph_centers(
        img,
        bbox_quad=[[0, 0], [200, 0], [200, 40], [0, 40]],
        n_glyphs=4,
    )
    assert len(centers) == 4
    # Even spacing → centers at 25%, 50%, 75% etc. of bbox width
    assert centers == sorted(centers)
    assert centers[0] < 100  # left half
    assert centers[-1] > 100  # right half


def test_glyph_centers_island_count_mismatch_uses_equal_mass():
    """When islands count != n_glyphs, fall back to equal-mass split (still useful)."""
    bars = [(10, 30), (50, 70), (90, 110)]  # 3 ink islands
    img = _bar_image(bars)
    centers = measure_glyph_centers(
        img,
        bbox_quad=[[0, 0], [img.shape[1], 0],
                   [img.shape[1], img.shape[0]], [0, img.shape[0]]],
        n_glyphs=5,  # asked for 5, only 3 islands found
    )
    assert len(centers) == 5
    assert centers == sorted(centers)


def test_glyph_centers_from_projection_equal_mass():
    """Pure unit test on the equal-mass primitive (no image)."""
    # Mass concentrated at three positions
    proj = np.zeros(300, dtype=np.float32)
    proj[40:60] = 1.0
    proj[140:160] = 1.0
    proj[240:260] = 1.0
    centers = glyph_centers_from_projection(proj, n_glyphs=3)
    assert len(centers) == 3
    # Each center near each bar center (50, 150, 250) within 2px
    for got, want in zip(centers, [50, 150, 250]):
        assert abs(got - want) <= 2, f"{got} far from {want}"


def test_glyph_centers_absolute_coordinates():
    """Centers should be in absolute image x, not local to the bbox patch."""
    # Build a wide image but the bar is in a sub-region we'll bbox into
    img = np.full((40, 600, 3), 255, dtype=np.uint8)
    img[5:35, 220:240] = 0  # single bar at absolute x ~230
    centers = measure_glyph_centers(
        img,
        bbox_quad=[[200, 0], [260, 0], [260, 40], [200, 40]],
        n_glyphs=1,
    )
    assert len(centers) == 1
    assert 225 <= centers[0] <= 235  # absolute image coord, not local 0..60
