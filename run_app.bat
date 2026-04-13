@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Streamlit 실행 중...
echo.
echo [같은 Wi-Fi의 폰/태블릿에서 접속 가능]
echo 실행 후 터미널에 나오는 "Network URL" 을 학생들에게 공유하세요.
echo.
".venv\Scripts\python.exe" -m streamlit run app.py

pause
