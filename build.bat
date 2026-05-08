@echo off
setlocal

py -m pip install --upgrade pip
py -m pip install --only-final :all: --no-warn-script-location -r requirements.txt

py -m PyInstaller ^
  --noconfirm ^
  --noconsole ^
  --onefile ^
  --clean ^
  --name "Text Adventure" ^
  --icon "game_icon.ico" ^
  --add-data "game_icon.ico;." ^
  --add-data "sounds;sounds" ^
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