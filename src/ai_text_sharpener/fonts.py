"""Assign user-specified fonts to detected regions based on font size threshold."""
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class FontSpec:
    title: str
    body: str
    title_min_px: int = 40


def assign_fonts(font_sizes_px: List[int], spec: FontSpec) -> List[str]:
    return [spec.title if s >= spec.title_min_px else spec.body for s in font_sizes_px]


# Fonts that are pre-installed (or very likely installed) on modern Windows,
# grouped by primary language script.  Picking one here that's missing on the
# host machine just falls through to the next renderable font, so erring on the
# side of inclusion is fine.
COMMON_FONT_GROUPS: List[tuple[str, List[str]]] = [
    ("Chinese (Simplified)", [
        "Microsoft YaHei",
        "Microsoft YaHei UI",
        "Microsoft YaHei Light",
        "SimHei",
        "SimSun",
        "NSimSun",
        "KaiTi",
        "FangSong",
        "DengXian",
        "DengXian Light",
        "STKaiti",
        "STSong",
        "STFangsong",
        "STZhongsong",
        "STXihei",
        "STLiti",
        "STXingkai",
        "STXinwei",
        "STHupo",
        "STCaiyun",
    ]),
    ("Chinese (Traditional)", [
        "Microsoft JhengHei",
        "Microsoft JhengHei UI",
        "MingLiU",
        "PMingLiU",
        "DFKai-SB",
    ]),
    ("Japanese", [
        "Yu Gothic",
        "Yu Gothic UI",
        "Meiryo",
        "Meiryo UI",
        "MS Gothic",
        "MS Mincho",
    ]),
    ("Korean", [
        "Malgun Gothic",
        "Batang",
        "Gulim",
        "Dotum",
    ]),
    ("Latin (Sans)", [
        "Arial",
        "Arial Black",
        "Calibri",
        "Candara",
        "Corbel",
        "Segoe UI",
        "Segoe UI Light",
        "Tahoma",
        "Trebuchet MS",
        "Verdana",
    ]),
    ("Latin (Serif)", [
        "Cambria",
        "Constantia",
        "Georgia",
        "Palatino Linotype",
        "Times New Roman",
    ]),
    ("Latin (Mono / Display)", [
        "Consolas",
        "Courier New",
        "Lucida Console",
        "Lucida Sans Unicode",
        "Comic Sans MS",
        "Impact",
    ]),
]


# Flat list kept for compatibility / callers that just want the full name set.
COMMON_FONT_FAMILIES: List[str] = [name for _, names in COMMON_FONT_GROUPS for name in names]

_FONT_EXTENSIONS = ("*.ttf", "*.otf", "*.ttc")


def _extract_family(path: Path, index: int = 0) -> Optional[str]:
    """Return the family name at a given face index, or None on failure."""
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(str(path), size=12, index=index)
        return font.font.family
    except Exception:
        return None


def _iter_families_in_file(path: Path) -> List[str]:
    """All family names contained in a font file (TTC may pack several)."""
    families: List[str] = []
    seen = set()
    is_collection = str(path).lower().endswith(".ttc")
    for i in range(64):  # safety cap on collection size
        family = _extract_family(path, index=i)
        if family is None:
            break
        if family not in seen:
            seen.add(family)
            families.append(family)
        if not is_collection:
            break
    return families


def _system_font_dirs() -> List[Path]:
    dirs: List[Path] = []
    system = platform.system()
    if system == "Windows":
        dirs.append(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif system == "Darwin":
        dirs.extend([
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library" / "Fonts",
        ])
    else:
        dirs.extend([
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path.home() / ".fonts",
            Path.home() / ".local/share/fonts",
        ])
    return [d for d in dirs if d.exists()]


_INSTALLED_CACHE: Optional[List[str]] = None


def installed_font_families() -> List[str]:
    """Discover installed system font family names, deduped, sorted (cached)."""
    global _INSTALLED_CACHE
    if _INSTALLED_CACHE is not None:
        return list(_INSTALLED_CACHE)
    families: set = set()
    for d in _system_font_dirs():
        for pattern in _FONT_EXTENSIONS:
            for path in d.glob(pattern):
                try:
                    for fam in _iter_families_in_file(path):
                        families.add(fam)
                except Exception:
                    continue
    _INSTALLED_CACHE = sorted(families, key=str.lower)
    return list(_INSTALLED_CACHE)


def _categorize_font(family: str) -> str:
    """Classify a font into a language/script group based on its family name."""
    lf = family.lower()
    # Family contains CJK char → almost always Chinese (Simplified default).
    if any("一" <= c <= "鿿" for c in family):
        if any(t in family for t in ("繁", "正黑", "明體", "TC")):
            return "Chinese (Traditional)"
        return "Chinese (Simplified)"
    sc_prefixes = (
        "microsoft yahei", "simsun", "nsimsun", "simhei", "simli", "simfang",
        "simyou", "kaiti", "fangsong", "dengxian", "hyswlongfangsong",
        "source han sans sc", "source han serif sc", "noto sans sc",
        "noto serif sc", "noto sans cjk sc", "noto serif cjk sc", "pingfang sc",
        "hiragino sans gb",
    )
    if any(lf.startswith(p) for p in sc_prefixes):
        return "Chinese (Simplified)"
    if (len(family) >= 4 and family.startswith("ST") and family[2].isupper()
            and family[3].isalpha()):
        return "Chinese (Simplified)"
    tc_prefixes = (
        "microsoft jhenghei", "mingliu", "pmingliu", "dfkai", "mingti",
        "source han sans tc", "noto sans tc", "noto sans cjk tc", "pingfang tc",
    )
    if any(lf.startswith(p) for p in tc_prefixes):
        return "Chinese (Traditional)"
    jp_prefixes = (
        "yu gothic", "yu mincho", "ms gothic", "ms mincho", "ms pgothic",
        "ms pmincho", "meiryo", "hiragino", "source han sans jp",
        "noto sans jp", "noto sans cjk jp",
    )
    if any(lf.startswith(p) for p in jp_prefixes):
        return "Japanese"
    kr_prefixes = (
        "malgun gothic", "batang", "gulim", "dotum", "nanum",
        "source han sans kr", "noto sans kr", "noto sans cjk kr",
    )
    if any(lf.startswith(p) for p in kr_prefixes):
        return "Korean"
    if any(kw in lf for kw in ("mono", "console", "consolas", "courier", "menlo")):
        return "Latin (Mono / Display)"
    if "sans serif" in lf or "sans-serif" in lf or "sansserif" in lf:
        return "Latin (Sans)"
    if any(kw in lf for kw in (
        "serif", "times", "georgia", "cambria", "constantia", "garamond",
        "palatino", "book antiqua", "goudy", "baskerville",
    )):
        return "Latin (Serif)"
    if any(kw in lf for kw in (
        "impact", "comic sans", "jokerman", "chiller", "showcard", "curlz",
        "engravers", "papyrus", "bauhaus",
    )):
        return "Latin (Mono / Display)"
    return "Latin (Sans)"


_GROUP_ORDER = [
    "Chinese (Simplified)",
    "Chinese (Traditional)",
    "Japanese",
    "Korean",
    "Latin (Sans)",
    "Latin (Serif)",
    "Latin (Mono / Display)",
]


def discover_grouped_fonts() -> List[Tuple[str, List[str]]]:
    """Group installed fonts by detected language/script.

    Falls back to ``COMMON_FONT_GROUPS`` when system enumeration yields nothing
    (e.g. PIL/system fonts unavailable in a test environment).
    """
    families = installed_font_families()
    if not families:
        return [(label, list(names)) for label, names in COMMON_FONT_GROUPS]
    buckets: dict = {k: [] for k in _GROUP_ORDER}
    for family in families:
        cat = _categorize_font(family)
        buckets.setdefault(cat, []).append(family)
    result: List[Tuple[str, List[str]]] = []
    for k in _GROUP_ORDER:
        if buckets.get(k):
            result.append((k, sorted(buckets[k], key=str.lower)))
    return result


def list_user_fonts(fonts_dir: Optional[Path]) -> List[dict]:
    """Scan a directory for font files and return {family, filename, path}.

    The family is read from the font file's internal metadata so it matches what
    resvg sees.  Falls back to the file stem if extraction fails.
    """
    if not fonts_dir:
        return []
    fonts_dir = Path(fonts_dir)
    if not fonts_dir.exists() or not fonts_dir.is_dir():
        return []
    seen: set[str] = set()
    results: List[dict] = []
    for pattern in _FONT_EXTENSIONS:
        for path in sorted(fonts_dir.glob(pattern)):
            family = _extract_family(path) or path.stem
            key = family.lower()
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "family": family,
                "filename": path.name,
                "path": str(path),
            })
    return results
