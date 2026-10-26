"""Render composed PPTX pages locally, with an isolated LibreOffice profile."""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

RENDER_LONG_SIDE = 3200


def _run(command, timeout, env=None):
    # Terminate the complete converter process group on timeout, including the
    # soffice.bin child of the launcher; never disturb a user's Office session.
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=env, start_new_session=os.name == "posix") as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                process.communicate()
                raise ValueError("PPT 页面转换超时，请拆分文件后重试。") from exc
            if process.returncode:
                raise ValueError("PPT 页面转换失败，请检查文件能否在 LibreOffice 中打开。")
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except OSError as exc:
        raise ValueError("无法启动 PPT 转换组件，请检查 LibreOffice 和 Poppler 的安装。") from exc


def render_pptx_pages(data: bytes, page_count: int, pages: list[int]) -> dict[int, Image.Image]:
    """Return selected 1-based pages; export hidden slides to preserve indexing."""
    office = shutil.which("libreoffice") or shutil.which("soffice")
    pdfinfo, raster = shutil.which("pdfinfo"), shutil.which("pdftoppm")
    if not office or not pdfinfo or not raster:
        raise ValueError("此 PPT 需要转换组件：请安装 LibreOffice Impress 和 Poppler 后重新导入。")
    with tempfile.TemporaryDirectory(prefix="sharpener-ppt-") as directory:
        root = Path(directory)
        source, pdf = root / "input.pptx", root / "input.pdf"
        source.write_bytes(data)
        profile = root / "profile"
        profile.mkdir()
        # Never reuse the desktop profile or enable document macros.
        user = profile / "user"
        user.mkdir()
        (user / "registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item></oor:items>', encoding="utf-8")
        env = dict(os.environ, SAL_USE_VCLPLUGIN="svp", LC_ALL="C.UTF-8")
        options = ('pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"},'
                   '"ExportNotesPages":{"type":"boolean","value":"false"},'
                   '"UseLosslessCompression":{"type":"boolean","value":"true"},'
                   '"ReduceImageResolution":{"type":"boolean","value":"false"}}')
        _run([office, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--nologo",
              "--nodefault", "--norestore", "--convert-to", options,
              "--outdir", str(root), str(source)], timeout=180, env=env)
        if not pdf.is_file():
            raise ValueError("PPT 转换未生成页面，请检查文件是否损坏或受密码保护。")
        info = _run([pdfinfo, str(pdf)], timeout=30, env=env)
        count = re.search(rb"^Pages:\s+(\d+)\s*$", info.stdout, re.MULTILINE)
        if not count or int(count[1]) != page_count:
            raise ValueError("PPT 转换后页数不一致，已停止导入。")
        result = {}
        for number in pages:
            prefix = root / f"page-{number}"
            _run([raster, "-f", str(number), "-l", str(number), "-singlefile", "-png",
                  "-scale-to", str(RENDER_LONG_SIDE), str(pdf), str(prefix)], timeout=60, env=env)
            path = prefix.with_suffix(".png")
            if not path.is_file():
                raise ValueError(f"第 {number} 页转换失败，已停止导入。")
            with Image.open(path) as image:
                if max(image.size) > RENDER_LONG_SIDE or min(image.size) < 1:
                    raise ValueError(f"第 {number} 页转换尺寸异常。")
                result[number] = image.convert("RGB")
            path.unlink()
        return result
