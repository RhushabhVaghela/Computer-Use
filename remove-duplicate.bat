@echo off
setlocal

set "FolderA=D:\Agents-and-other-repos\Computer-Use"
set "FolderB=D:\Agents-and-other-repos\Computer-Use\moshi\bin"

for %%F in ("%FolderA%\*") do (
    if exist "%FolderB%\%%~nxF" (
        echo Deleting "%%~fF"
        del /q "%%~fF"
    )
)

echo Done.
pause