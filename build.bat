@echo off
setlocal

pyinstaller ^
  --noconfirm ^
  --noconsole ^
  --onefile ^
  --clean ^
  --name "Text Adventure" ^
  --icon "game_icon.ico" ^
  --add-data "game_icon.ico;." ^
  --add-data "sounds;sounds" ^
  --add-data "prompt_templates\default_rules.md;prompt_templates" ^
  main.py