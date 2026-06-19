@echo off
echo ============================================
echo  FB Scraper Backend - uvicorn
echo  Entry: backend/main.py
echo  Config: backend/.env
echo ============================================
cd /d "%~dp0"
call venv\Scripts\activate
cd backend
python main.py
pause
