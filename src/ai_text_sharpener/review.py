"""Editable review documents for text replacement decisions."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple

from .detect import TextRegion
from .style import RegionStyle

RGB = Tuple[int, int, int]


@dataclass
class TextSpan:
    """One styled run within a text region.  None fields inherit from the parent region."""
    text: str
    color: Optional[RGB] = None
    font_size_px: Optional[int] = None
    font_family: Optional[str] = None
    font_weight: Optional[str] = None
    vertical_align: Optional[str] = None  # None | "super" | "sub"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"text": self.text}
        if self.color is not None:
            d["color"] = list(self.color)
        if self.font_size_px is not None:
            d["font_size_px"] = self.font_size_px
        if self.font_family is not None:
            d["font_family"] = self.font_family
        if self.font_weight is not None:
            d["font_weight"] = self.font_weight
        if self.vertical_align:
            d["vertical_align"] = self.vertical_align
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TextSpan":
        va = data.get("vertical_align")
        return cls(
            text=str(data.get("text", "")),
            color=_rgb(data["color"]) if data.get("color") is not None else None,
            font_size_px=int(data["font_size_px"]) if data.get("font_size_px") is not None else None,
            font_family=str(data["font_family"]) if data.get("font_family") else None,
            font_weight=str(data["font_weight"]) if data.get("font_weight") else None,
            vertical_align=str(va) if va in ("super", "sub") else None,
        )


@dataclass
class EditableRegion:
    id: str
    bbox: list
    original_text: str
    text: str
    confidence: float
    replace: bool
    x: int
    y: int
    font_family: str
    font_size_px: int
    font_weight: str
    color: RGB
    background: RGB
    letter_spacing_px: float = 0.0
    text_anchor: str = "center"  # "center" | "left" | "right"
    spans: List[TextSpan] = field(default_factory=list)

    def to_text_region(self) -> TextRegion:
        return TextRegion(
            bbox=self.bbox,
            text=self.original_text,
            confidence=self.confidence,
        )

    def to_region_style(self) -> RegionStyle:
        return RegionStyle(
            color=self.color,
            background=self.background,
            font_size_px=self.font_size_px,
        )

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "bbox": self.bbox,
            "original_text": self.original_text,
            "text": self.text,
            "confidence": self.confidence,
            "replace": self.replace,
            "x": self.x,
            "y": self.y,
            "font_family": self.font_family,
            "font_size_px": self.font_size_px,
            "font_weight": self.font_weight,
            "letter_spacing_px": self.letter_spacing_px,
            "color": list(self.color),
            "background": list(self.background),
        }
        if self.text_anchor and self.text_anchor != "center":
            d["text_anchor"] = self.text_anchor
        if self.spans:
            d["spans"] = [s.to_dict() for s in self.spans]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EditableRegion":
        raw_spans = data.get("spans") or []
        return cls(
            id=str(data["id"]),
            bbox=data["bbox"],
            original_text=str(data.get("original_text", data.get("text", ""))),
            text=str(data.get("text", "")),
            confidence=float(data.get("confidence", 0.0)),
            replace=bool(data.get("replace", True)),
            x=int(data["x"]),
            y=int(data["y"]),
            font_family=str(data["font_family"]),
            font_size_px=int(data["font_size_px"]),
            font_weight=str(data.get("font_weight", "normal")),
            letter_spacing_px=float(data.get("letter_spacing_px", 0.0)),
            text_anchor=str(data.get("text_anchor", "center")),
            color=_rgb(data.get("color", (0, 0, 0))),
            background=_rgb(data.get("background", (255, 255, 255))),
            spans=[TextSpan.from_dict(s) for s in raw_spans],
        )


@dataclass
class ReviewDocument:
    image_width: int
    image_height: int
    regions: List[EditableRegion]
    source_image: str = ""
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_image": self.source_image,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "regions": [region.to_dict() for region in self.regions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewDocument":
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            source_image=str(data.get("source_image", "")),
            image_width=int(data["image_width"]),
            image_height=int(data["image_height"]),
            regions=[EditableRegion.from_dict(r) for r in data.get("regions", [])],
        )


def load_review_document(path: Path) -> ReviewDocument:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return ReviewDocument.from_dict(data)


def write_review_document(review: ReviewDocument, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(review.to_dict(), ensure_ascii=False, indent=2)
    Path(path).write_text(text + "\n", encoding="utf-8")


def _rgb(value: Any) -> RGB:
    channels = list(value)
    if len(channels) != 3:
        raise ValueError(f"RGB value must have 3 channels: {value}")
    return tuple(int(c) for c in channels)
