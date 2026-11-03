"""Erasure should recover known backgrounds when moved text exposes its old place."""
from copy import deepcopy

import cv2
import numpy as np
import pytest

from ai_text_sharpener.fidelity import crop_evidence, erase_regions
from ai_text_sharpener.typography import candidate_fonts, font_catalog, render_mask


@pytest.fixture(scope='module')
def face():
    return next((f['id'] for f in font_catalog().values()
                 if f['family'] == 'Liberation Sans' and f['style'] == 'Regular'),
                candidate_fonts('Sample text 123', 1)[0])


def scene(face, size=44, blur=2.5, background='flat', text='Sample text 123'):
    glyph, _ = render_mask(face, text, size, 0, 0)
    h, w = glyph.shape
    height, width = 150, max(600, w+100)
    x, y = 48, 50
    yy, xx = np.mgrid[:height, :width]
    if background == 'linear':
        clean = np.stack((225+xx*.02+yy*.02, 232+xx*.015-yy*.02,
                          222+xx*.025+yy*.03), axis=-1)
    elif background == 'noise':
        clean = 218+np.random.default_rng(42).integers(-30, 31, (height, width, 3))
    elif isinstance(background, float):
        clean = np.repeat(np.clip(228+background*(yy-(y+h/2))**2, 0, 255)[..., None], 3, axis=2)
    else:
        clean = np.full((height, width, 3), 240.)
    clean = np.rint(clean).astype(np.uint8)
    alpha = np.zeros((height, width), np.float32)
    alpha[y:y+h, x:x+w] = glyph
    alpha = cv2.GaussianBlur(alpha, (0, 0), blur)
    image = np.rint(clean*(1-alpha[..., None])+30*alpha[..., None]).astype(np.uint8)
    region = dict(id='sample', text=text, original_text=text,
                  bbox=[x-8, y-8, w+16, h+16], enabled=True, x=x, y=y,
                  rotation=0, source_rotation=0, font_id=face, font_size=size,
                  letter_spacing=0, stroke_width=0, erase_mode='gradient')
    return image, clean, region, alpha


@pytest.mark.parametrize('weight', ['Regular', 'Bold'])
def test_short_blurred_caption_has_enough_room_for_fringe_to_fade(face, weight):
    face = next((f['id'] for f in font_catalog().values()
                 if f['family'] == 'Liberation Sans' and f['style'] == weight), face)
    image, clean, region, _ = scene(face, size=42, text='Blur test')
    erased = erase_regions(image, [region])
    assert np.abs(erased.astype(float)-clean).max() <= 3


@pytest.mark.parametrize('size', [42, 44])
@pytest.mark.parametrize('blur', [.65, 1.8, 2.5])
@pytest.mark.parametrize('background', ['flat', 'linear'])
def test_blurred_text_erases_to_known_flat_or_linear_background(face, size, blur, background):
    image, clean, region, _ = scene(face, size, blur, background)
    erased = erase_regions(image, [region])
    x, y, w, h = region['bbox']
    error = np.abs(erased[y:y+h, x:x+w].astype(float)-clean[y:y+h, x:x+w]).max(axis=2)
    assert error.max() <= 3
    assert np.count_nonzero(error > 5) == 0
    outside = np.ones(image.shape[:2], bool)
    outside[y:y+h, x:x+w] = False
    assert np.array_equal(erased[outside], image[outside])


@pytest.mark.parametrize('mode', ['gradient', 'inpaint'])
def test_moving_rotating_or_clearing_redrawn_text_keeps_source_erasure_identical(face, mode):
    image, _, region, _ = scene(face)
    region['erase_mode'] = mode
    moved = dict(region, x=320, y=100, rotation=37, text='')
    before = deepcopy(moved)
    assert np.array_equal(erase_regions(image, [moved]), erase_regions(image, [region]))
    assert moved == before


def test_cleanup_does_not_touch_disconnected_neighbor_or_decoration(face):
    image, _, region, _ = scene(face)
    # Enlarge only the top of the crop to include a clipped neighboring line.
    region['bbox'][1] -= 15
    region['bbox'][3] += 15
    y = region['bbox'][1]
    image[y:y+2, 150:160] = 40
    image[y+2:y+4, 150:160] = 230
    image[35:95, 20:28] = (190, 30, 45)  # Adjacent red decoration outside OCR.
    erased = erase_regions(image, [region])
    assert np.array_equal(erased[y:y+4, 150:160], image[y:y+4, 150:160])
    assert np.array_equal(erased[35:95, 20:28], image[35:95, 20:28])


@pytest.mark.parametrize('background', ['noise', .01, .06])
def test_cleanup_does_not_add_flat_patches_over_nontext_background(face, background):
    image, clean, region, alpha = scene(face, background=background)
    ev = crop_evidence(image, region['bbox'], single_line=True)
    radius = max(1, round(ev['binary'].shape[0]*.045))
    # Existing erasure is the compatibility boundary. Additional cleanup must
    # not flatten untouched texture or a curved gradient beside the glyphs.
    old_mask = cv2.dilate(ev['binary'], np.ones((radius*2+1, radius*2+1), np.uint8)) > 0
    erased = erase_regions(image, [region])
    x, y, w, h = region['bbox']
    unchanged_background = (alpha[y:y+h, x:x+w] < .005) & ~old_mask
    assert unchanged_background.any()
    before = image[y:y+h, x:x+w][unchanged_background]
    after = erased[y:y+h, x:x+w][unchanged_background]
    assert np.max(np.abs(after.astype(float)-before)) <= 3

