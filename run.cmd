@echo off
setlocal EnableExtensions DisableDelayedExpansion
pushd "%~dp0" || exit /b 1

set "RUN_PYTHON="
set "RUN_PYTHON_ARGS="
set "RUN_ENV=global Python"

rem Prefer a virtual environment inside this project.
for %%D in (.venv venv env virtualenv) do (
    if exist "%~dp0%%D\Scripts\python.exe" (
        set "RUN_PYTHON=%~dp0%%D\Scripts\python.exe"
        set "RUN_ENV=project virtual environment: %%D"
        goto :python_selected
    )
)

rem Also support an already activated venv or non-base Conda environment.
if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" (
    set "RUN_PYTHON=%VIRTUAL_ENV%\Scripts\python.exe"
    set "RUN_ENV=activated virtual environment"
    goto :python_selected
)
if defined CONDA_PREFIX if /i not "%CONDA_DEFAULT_ENV%"=="base" if exist "%CONDA_PREFIX%\python.exe" (
    set "RUN_PYTHON=%CONDA_PREFIX%\python.exe"
    set "RUN_ENV=activated Conda environment"
    goto :python_selected
)

python -c "import sys; assert sys.version_info.major == 3" >nul 2>&1
if not errorlevel 1 (
    set "RUN_PYTHON=python"
    goto :python_selected
)
py -3 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    set "RUN_PYTHON=py"
    set "RUN_PYTHON_ARGS=-3"
    goto :python_selected
)
echo [ERROR] Python 3 was not found. Install Python and add it to PATH.
set "RUN_EXIT=1"
goto :finish

:python_selected
echo [INFO] Using %RUN_ENV%
"%RUN_PYTHON%" %RUN_PYTHON_ARGS% -c "import sys; print('[INFO] Python: ' + sys.executable)"
if errorlevel 1 (
    echo [ERROR] The selected Python environment cannot run. Please repair it.
    set "RUN_EXIT=1"
    goto :finish
)
if /i "%~1"=="--check" (
    set "RUN_EXIT=0"
    goto :finish
)
"%RUN_PYTHON%" %RUN_PYTHON_ARGS% -c "import fastapi, uvicorn, pydantic, dotenv" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Required dependencies are missing in this environment.
    echo Install them with:
    echo "%RUN_PYTHON%" %RUN_PYTHON_ARGS% -m pip install -r requirements-vrm.txt
    set "RUN_EXIT=1"
    goto :finish
)
echo [INFO] Open http://localhost:8890/ after the server starts.
echo [INFO] Press Ctrl+C to stop the server.
"%RUN_PYTHON%" %RUN_PYTHON_ARGS% -B "%~dp0vrm_demo\vrm_server.py"
set "RUN_EXIT=%ERRORLEVEL%"

:finish
popd
if not "%RUN_EXIT%"=="0" if /i not "%~1"=="--check" pause
exit /b %RUN_EXIT%
