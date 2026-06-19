@echo off
cd /d "C:\Users\USER\fb-scrapper\backend"
call venv\Scripts\activate.bat
python fb_debug_dom.py bemui > debug_dom_output.txt 2>&1
echo Done - check debug_dom_output.txt