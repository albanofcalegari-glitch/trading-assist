@echo off
cd /d "C:\Users\DELL\Desktop\proyectos python\trading-assist"
".venv\Scripts\python.exe" "scripts\morning_alert.py" >> "logs\morning_alert.log" 2>&1
