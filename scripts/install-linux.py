"""Register a per-user launcher and an on-demand service (no login autostart)."""
import os
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
python = root / ".venv/bin/python"
if not python.exists():
    raise SystemExit("请先创建 .venv 并运行 pip install -e .")
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
desktop = data / "applications/ai-text-sharpener.desktop"
desktop.parent.mkdir(parents=True, exist_ok=True)
desktop.write_text(
    "[Desktop Entry]\nType=Application\nVersion=1.0\n"
    "Name=文字重绘\nName[en]=AI Text Sharpener\n"
    "Comment=匹配原图字体与排版，在本机重绘清晰文字\n"
    f'Exec="{str(launcher).replace("%", "%%")}"\n'
    f"Icon={root / 'src/ai_text_sharpener/web/icon.svg'}\n"
    "Terminal=false\nCategories=Graphics;Office;\nStartupNotify=false\n",
    encoding="utf-8",
)
subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
print(f"已安装应用入口：{desktop}")
print("应用菜单搜索：文字重绘")
print("仅按需启动，未设置开机自启。")
