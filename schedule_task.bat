@echo off
schtasks /create /tn "TradingAssist_MorningAlert" /tr "\"C:\Users\DELL\Desktop\proyectos python\trading-assist\.venv\Scripts\python.exe\" \"C:\Users\DELL\Desktop\proyectos python\trading-assist\scripts\morning_alert.py\"" /sc weekly /d MON,TUE,WED,THU,FRI /st 10:35 /f
pause
