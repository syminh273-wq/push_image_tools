# PyInstaller spec — run from the project root:  pyinstaller packaging/gemini_video_tool.spec
# Builds a one-folder app in dist/GeminiVideoTool/. Build web/dist first (npm run build:desktop).
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, ROOT)

datas = [
    ("web/dist", "web/dist"),
    ("prompts/default.txt", "prompts"),
    ("prompts/tiktok_content.txt", "prompts"),
    ("data/prompts.json", "data"),
    ("data/system_rules.json", "data"),
]

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, src), dst) for src, dst in datas],
    hiddenimports=collect_submodules("app") + (["keyring.backends.Windows"] if sys.platform == "win32" else []),
)
pyz = PYZ(a.pure)
# No console window on Windows: the app opens in its own pywebview window.
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GeminiVideoTool", console=sys.platform != "win32")
coll = COLLECT(exe, a.binaries, a.datas, name="GeminiVideoTool")
