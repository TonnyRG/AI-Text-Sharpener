"""Review project manifests for multi-slide editing."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List


@dataclass
class ReviewProjectItem:
    id: str
    name: str
    image_path: str
    review_path: str
    output_png: str = ""
    output_svg: str = ""
    draft_png: str = ""
    draft_svg: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "image_path": self.image_path,
            "review_path": self.review_path,
            "output_png": self.output_png,
            "output_svg": self.output_svg,
            "draft_png": self.draft_png,
            "draft_svg": self.draft_svg,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewProjectItem":
        return cls(
            id=str(data["id"]),
            name=str(data.get("name", data["id"])),
            image_path=str(data["image_path"]),
            review_path=str(data["review_path"]),
            output_png=str(data.get("output_png", "")),
            output_svg=str(data.get("output_svg", "")),
            draft_png=str(data.get("draft_png", "")),
            draft_svg=str(data.get("draft_svg", "")),
        )


@dataclass
class ReviewProject:
    items: List[ReviewProjectItem]
    source_ppt: str = ""
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_ppt": self.source_ppt,
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewProject":
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            source_ppt=str(data.get("source_ppt", "")),
            items=[ReviewProjectItem.from_dict(item) for item in data.get("items", [])],
        )


def load_review_project(path: Path) -> ReviewProject:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return ReviewProject.from_dict(data)


def write_review_project(project: ReviewProject, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(project.to_dict(), ensure_ascii=False, indent=2)
    Path(path).write_text(text + "\n", encoding="utf-8")


def resolve_project_path(project_path: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return Path(project_path).parent / path


def project_relative_path(project_dir: Path, path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(project_dir).resolve()))
    except ValueError:
        return str(path)
