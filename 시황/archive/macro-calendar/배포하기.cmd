@echo off
chcp 65001 >nul
REM Cloudflare 에 배포합니다. Cloudflare 가입을 먼저 마친 뒤 실행하세요.
REM 여러 번 실행해도 안전합니다 (이미 끝난 단계는 건너뜁니다).
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "%~dp0"

echo.
echo ============================================
echo   Cloudflare 배포
echo.
echo   * 처음 실행하면 브라우저가 열립니다
echo     -^> [Allow] 를 눌러 로그인해 주세요
echo   * 전체 3~5분 걸립니다
echo ============================================
echo.

node scripts\deploy.mjs

echo.
pause
