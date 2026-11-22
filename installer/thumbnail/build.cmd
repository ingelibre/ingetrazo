@echo off
rem Builds the .igz thumbnail handler: installer\thumbnail\build\ingetrazo-thumbnail.dll
rem
rem Needs MSVC (Visual Studio or its Build Tools, "Desktop development with
rem C++"). From a plain CMD it finds MSVC with vswhere; from a developer
rem prompt it uses the cl.exe already on the PATH. The CI runs the same file.
setlocal
set "HERE=%~dp0"
set "OUT=%HERE%build"

where cl >nul 2>nul
if not errorlevel 1 goto build

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto nomsvc
rem Through a file, not for /f: a quoted program path loses its quotes there.
set "VSFILE=%TEMP%\ingetrazo-vswhere-%RANDOM%.txt"
"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath > "%VSFILE%"
set "VS="
set /p VS=<"%VSFILE%"
del "%VSFILE%" >nul 2>nul
if not defined VS goto nomsvc
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 goto nomsvc

:build
if not exist "%OUT%" mkdir "%OUT%"
rem /MT: the static runtime. Explorer loads the handler in dllhost.exe,
rem which does not look in the IngeTrazo folder for the C++ runtime.
cl /nologo /O2 /W4 /WX /EHsc /std:c++17 /MT /GS /guard:cf /DUNICODE /D_UNICODE ^
   /LD "%HERE%thumbnail_provider.cpp" /Fo"%OUT%\\" /Fe"%OUT%\ingetrazo-thumbnail.dll" ^
   /link /DEF:"%HERE%thumbnail_provider.def" /guard:cf /DYNAMICBASE /NXCOMPAT
if errorlevel 1 exit /b 1
echo Built %OUT%\ingetrazo-thumbnail.dll
exit /b 0

:nomsvc
echo MSVC was not found: install Visual Studio Build Tools with "Desktop development with C++".
exit /b 1
