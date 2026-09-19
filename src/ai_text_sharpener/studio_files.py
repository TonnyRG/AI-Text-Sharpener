"""Local directory selection and explicit, non-overwriting export copies."""
import errno
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def default_export_directory(root):
    try:
        saved = json.loads((root / "preferences.json").read_text())["export_directory"]
        if Path(saved).is_dir():
            return str(Path(saved))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        selected = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True,
                                  text=True, timeout=2, check=True).stdout.strip()
        if selected and Path(selected).is_dir():
            return selected
    except (OSError, subprocess.SubprocessError):
        pass
    return str(next((p for p in [Path.home()/"下载", Path.home()/"Downloads"] if p.is_dir()), Path.home()))


def directory_contents(path):
    try:
        directory = Path(path).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("文件夹不存在，请检查路径。") from exc
    if not directory.is_dir():
        raise ValueError("请选择文件夹。")
    folders = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.name.startswith(".") and entry.is_dir():
                folders.append(entry.name)
    return {"path": str(directory), "parent": str(directory.parent), "home": str(Path.home()),
            "folders": sorted(folders, key=str.casefold)}


def export_destination(data, extension, protected_root):
    if not isinstance(data, dict) or not isinstance(data.get("directory"), str):
        raise ValueError("请选择保存文件夹。")
    directory = Path(data["directory"]).expanduser()
    if not directory.is_absolute():
        raise ValueError("保存文件夹需要使用完整路径。")
    try:
        directory = directory.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError("保存文件夹不存在，请重新选择。") from exc
    if not directory.is_dir():
        raise ValueError("保存位置不是文件夹。")
    if directory.is_relative_to(protected_root.resolve()):
        raise ValueError("请选择工作区数据目录以外的文件夹。")
    name = data.get("filename", "")
    if (not isinstance(name, str) or not name.strip() or name in {".", ".."}
            or any(c in name for c in '/\\\x00\r\n') or len(name.encode()) > 200):
        raise ValueError("文件名不能为空、超过 200 字节或包含路径分隔符。")
    if not name.lower().endswith("." + extension):
        raise ValueError(f"文件名需要以 .{extension} 结尾。")
    return directory / name


def save_export(source, requested, progress=None):
    """Publish a complete copy, adding a number rather than replacing any file."""
    fd, temp = tempfile.mkstemp(prefix=".sharpener-", suffix=".tmp", dir=requested.parent)
    temp = Path(temp)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
        if progress:
            progress("正在保存导出文件…", 99)
        for number in range(10000):
            candidate = requested if number == 0 else requested.with_name(f"{requested.stem} ({number}){requested.suffix}")
            try:
                # Atomic no-clobber publication on the same filesystem.
                os.link(temp, candidate)
                return candidate
            except FileExistsError:
                continue
            except OSError as exc:
                if exc.errno not in {errno.EPERM, errno.EOPNOTSUPP, errno.EXDEV, errno.ENOSYS}:
                    raise
                # FAT/exFAT volumes do not offer hard links. Exclusive creation
                # still prevents overwrites; remove an incomplete copy on error.
                try:
                    output = candidate.open("xb")
                except FileExistsError:
                    continue
                try:
                    with output, temp.open("rb") as input_file:
                        shutil.copyfileobj(input_file, output)
                    return candidate
                except BaseException:
                    candidate.unlink(missing_ok=True)
                    raise
        raise ValueError("同名文件过多，请更改文件名。")
    finally:
        temp.unlink(missing_ok=True)


def remember_directory(root, directory):
    fd, temp = tempfile.mkstemp(dir=root, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump({"export_directory": str(directory)}, output, ensure_ascii=False)
        os.replace(temp, root / "preferences.json")
    finally:
        Path(temp).unlink(missing_ok=True)
