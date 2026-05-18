"""Assign user-specified fonts to detected regions based on font size threshold."""
from dataclasses import dataclass
from typing import List


@dataclass
class FontSpec:
    title: str
    body: str
    title_min_px: int = 40


def assign_fonts(font_sizes_px: List[int], spec: FontSpec) -> List[str]:
    return [spec.title if s >= spec.title_min_px else spec.body for s in font_sizes_px]
