@echo off
setlocal

py -m pip install --upgrade pip | findstr /V /C:"Requirement already satisfied"
py -m pip install -r requirements.txt | findstr /V /C:"Requirement already satisfied"

py -m PyInstaller ^
  --log-level ERROR ^
  --noconfirm ^
  --noconsole ^
  --onefile ^
  --clean ^
  --name "Text Adventure" ^
  --icon "game_icon.ico" ^
  --collect-all "kokoro_onnx" ^
  --collect-all "phonemizer" ^
  --collect-all "segments" ^
  --collect-all "csvw" ^
  --collect-all "language_tags" ^
  --collect-all "espeakng_loader" ^
  --add-data "game_icon.ico;." ^
  --add-data "sounds;sounds" ^
  --add-data "models;models" ^
  --add-data "prompt_templates\default_rules.md;prompt_templates" ^
  --add-data "prompt_templates\creative_ideas.md;prompt_templates" ^
  main.py

if errorlevel 1 (
    echo.
    echo Build failed.
    exit /b 1
)

echo.
echo Build completed successfully.