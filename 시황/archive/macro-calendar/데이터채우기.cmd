@echo off
chcp 65001 >nul
REM 최신 지표와 발표 일정을 받아옵니다.
REM 서버(dev.cmd 또는 폰에서보기.cmd)가 켜져 있는 상태에서 실행하세요.
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "%~dp0"

echo.
echo   데이터를 갱신합니다. 1~3분 걸립니다.
echo.

node scripts\refresh.mjs %1

echo.
pause
