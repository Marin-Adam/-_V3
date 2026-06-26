@echo off
chcp 65001 >nul
echo 正在停止所有服务...
taskkill /FI "WINDOWTITLE eq DataAgent*" /F 2>nul
taskkill /FI "WINDOWTITLE eq AnalyzeAgent*" /F 2>nul
taskkill /FI "WINDOWTITLE eq SentimentAgent*" /F 2>nul
taskkill /FI "WINDOWTITLE eq ReportAgent*" /F 2>nul
taskkill /FI "WINDOWTITLE eq Backend*" /F 2>nul
taskkill /FI "WINDOWTITLE eq Frontend*" /F 2>nul
echo 已停止
pause
