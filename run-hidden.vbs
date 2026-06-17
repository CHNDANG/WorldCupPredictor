Set shell = CreateObject("WScript.Shell")
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\WorldCupPredictor\watchdog.ps1"""
shell.Run command, 0, False
