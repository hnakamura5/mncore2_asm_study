@echo off
setlocal

set IMAGE_NAME=mncore-challenge

docker ps >nul 2>&1
if %errorlevel% neq 0 (
    echo Docker daemon is not running. Please start Docker and try again.
    exit /b 1
)

set "scriptDir=%~dp0"
set "scriptDir=%scriptDir:~0,-1%"

set "IMAGE_EXISTS="
for /f %%i in ('docker images -q %IMAGE_NAME%') do set IMAGE_EXISTS=%%i
if "%IMAGE_EXISTS%"=="" (
    echo Building docker image %IMAGE_NAME%...
    docker build --platform linux/amd64 -t %IMAGE_NAME% "%scriptDir%"
    if %errorlevel% neq 0 (
        echo Failed to build Docker image.
        exit /b 1
    )
    echo --------------------------------------
)

docker run --mount type=bind,src="%cd%",dst=/root -it --rm %IMAGE_NAME% python3 /judge-py/judge.py %*
if %errorlevel% neq 0 (
    echo Failed to run Docker container.
    exit /b 1
)
