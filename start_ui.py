import webbrowser
import threading
import time
import subprocess
import sys
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent
_VENV_PY = BASE / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
PY = _VENV_PY if _VENV_PY.exists() else Path(sys.executable)
PORT = 8000

if not _VENV_PY.exists():
    print("未找到 .venv，改用当前 Python 解释器启动（建议先按 README 创建虚拟环境）")

url = f"http://127.0.0.1:{PORT}"
print(f"学术社会地图 UI: {url}")
webbrowser.open(url, new=2)

proc = subprocess.Popen(
    [str(PY), "-X", "utf8", "-m", "uvicorn", "server:app", "--port", str(PORT), "--reload"],
    cwd=str(BASE),
)
try:
    proc.wait()
except KeyboardInterrupt:
    proc.terminate()
