@echo off
REM Build dist\GeminiVideoTool\GeminiVideoTool.exe on a Windows machine (needs Python 3.12 + Node 20+).
cd /d "%~dp0\.."
pushd web && call npm ci && call npm run build:desktop && popd || exit /b 1
python -m pip install -r requirements.txt pyinstaller || exit /b 1
pyinstaller --noconfirm --distpath dist --workpath build packaging\gemini_video_tool.spec || exit /b 1
echo Done: dist\GeminiVideoTool\GeminiVideoTool.exe
