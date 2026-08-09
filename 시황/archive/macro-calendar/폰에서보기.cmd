@echo off
chcp 65001 >nul
REM 같은 와이파이의 폰에서 접속할 수 있게 서버를 엽니다.
REM (--ip 0.0.0.0 이 없으면 이 PC 에서만 접속됩니다)
set "PATH=C:\Program Files\nodejs;%PATH%"
cd /d "%~dp0"

echo.
echo ============================================
echo   폰 브라우저에서 아래 주소로 접속하세요
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
  for /f "tokens=1" %%b in ("%%a") do echo      http://%%b:8788
)
echo.
echo   * PC 와 폰이 같은 와이파이여야 합니다
echo   * 처음 실행 시 방화벽 허용 창이 뜨면 [허용] 을 누르세요
echo   * 이 창을 닫으면 서버가 꺼집니다
echo ============================================
echo.

call "C:\Program Files\nodejs\npm.cmd" run dev:lan
pause
