"""Register a per-user launcher and an on-demand service (no login autostart)."""
import os
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
python = root / ".venv/bin/python"
if not python.exists():
    raise SystemExit("请先创建 .venv 并运行 pip install -e .")
bash = shutil.which("bash")
if not bash:
    raise SystemExit("未找到 Bash，无法安装启动入口。")
config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
data = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
service = config / "systemd/user/ai-text-sharpener.service"
service.parent.mkdir(parents=True, exist_ok=True)

def unit_quote(path):
    return '"' + str(path).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'

service.write_text(
    "[Unit]\nDescription=AI Text Sharpener local studio\nAfter=network.target\n\n"
    "[Service]\nType=simple\n"
    f"WorkingDirectory={str(root).replace('%', '%%')}\n"
    f"ExecStart={unit_quote(python)} -m ai_text_sharpener.studio --no-open\n"
    "Restart=on-failure\nRestartSec=3\nEnvironment=PYTHONUNBUFFERED=1\n"
    "Environment=OMP_NUM_THREADS=4\n",
    encoding="utf-8",
)
launcher = root / "scripts/launch-studio.sh"
launcher.chmod(0o755)
icon = data / "icons/hicolor/scalable/apps/ai-text-sharpener.svg"
icon.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(root / "src/ai_text_sharpener/web/icon.svg", icon)
desktop = data / "applications/ai-text-sharpener.desktop"
desktop.parent.mkdir(parents=True, exist_ok=True)
# GNOME drops entries whose Exec executable is absent at login. The project
# may live on a drive mounted later, so use the system shell as the executable
# and keep its icon on the user's local data volume.
desktop.write_text(
    "[Desktop Entry]\nType=Application\nVersion=1.0\n"
    "Name=文字重绘\nName[en]=AI Text Sharpener\n"
    "Keywords=文字重绘;文字;重绘;AI Text Sharpener;OCR;PPT;\n"
    "Comment=匹配原图字体与排版，在本机重绘清晰文字\n"
    f'Exec="{bash}" "{str(launcher).replace("%", "%%")}"\n'
    f"Icon={icon}\n"
    "Terminal=false\nCategories=Graphics;Office;\nStartupNotify=false\n",
    encoding="utf-8",
)
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
print(f"已安装应用入口：{desktop}")
print("应用菜单搜索：文字重绘")
print("仅按需启动，未设置开机自启。")
