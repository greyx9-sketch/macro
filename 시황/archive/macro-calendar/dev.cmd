@echo off
chcp 65001 >nul
REM 이 PC 에서만 접속하는 개발 서버 (http://localhost:8788)
REM Node 설치 직후에는 PATH 가 갱신되기 전이라 여기서 직접 잡아줍니다.
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "%~dp0"

echo.
echo ============================================
echo   매크로 캘린더 서버
echo.
echo      http://localhost:8788
echo.
echo   * 이 창을 닫으면 서버가 꺼집니다
echo ============================================
echo.

REM 화면에도 보여주고 dev.log 에도 남깁니다.
REM 창이 갑자기 닫혀도 dev.log 를 열면 원인을 볼 수 있습니다.
call "C:\Program Files\nodejs\npm.cmd" run dev 2>&1 | "C:\Program Files\nodejs\node.exe" -e "const fs=require('fs');const w=fs.createWriteStream('dev.log');process.stdin.on('data',d=>{process.stdout.write(d);w.write(d);});"

echo.
echo ============================================
echo   서버가 종료됐습니다.
echo   오류가 있었다면 이 폴더의 dev.log 파일에 남아 있습니다.
echo ============================================
echo.
pause
