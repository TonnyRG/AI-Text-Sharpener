#!/usr/bin/env bash
set -euo pipefail
studio_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -x "$studio_root/.venv/bin/python" ]]; then
  printf '%s\n' '请先运行安装步骤创建 .venv。' >&2
  exit 1
fi
systemctl --user start ai-text-sharpener.service
"$studio_root/.venv/bin/python" - <<'PY'
import time, urllib.request, webbrowser
for _ in range(60):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8766/api/boot', timeout=1):
            break
    except OSError:
        time.sleep(.25)
else:
    raise SystemExit('启动失败：请查看 journalctl --user -u ai-text-sharpener.service')
webbrowser.open('http://127.0.0.1:8766')
PY
