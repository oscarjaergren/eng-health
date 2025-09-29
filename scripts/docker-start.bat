@echo off
REM Docker Quick Start Script for PR Analytics (Windows)
REM This script helps you get started with the Docker deployment

echo.
echo 🐳 PR Analytics - Docker Quick Start
echo ======================================
echo.

REM Check if Docker is installed
docker --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Error: Docker is not installed
    echo Please install Docker Desktop from: https://docs.docker.com/desktop/install/windows-install/
    exit /b 1
)

REM Check if Docker Compose is installed
docker-compose --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Error: Docker Compose is not installed
    echo Please install Docker Desktop which includes Docker Compose
    exit /b 1
)

echo ✅ Docker and Docker Compose are installed
echo.

REM Check if .env file exists
if not exist .env (
    echo ⚠️  Warning: .env file not found
    echo.
    echo Creating .env from .env.example...

    if exist .env.example (
        copy .env.example .env >nul
        echo ✅ .env file created
        echo.
        echo 📝 Please edit .env file with your credentials:
        echo    - Azure DevOps: AZURE_DEVOPS_ORGANIZATION and AZURE_DEVOPS_PAT
        echo    - GitHub: GITHUB_TOKEN, GITHUB_OWNER, and GITHUB_TYPE
        echo.
        pause
    ) else (
        echo ❌ Error: .env.example not found
        exit /b 1
    )
)

echo ✅ Configuration file found
echo.

REM Create data and cache directories
if not exist data mkdir data
if not exist cache mkdir cache
echo ✅ Created data and cache directories
echo.

REM Build Docker image
echo 🔨 Building Docker image...
docker-compose build

echo.
echo ✅ Docker image built successfully
echo.

REM Start dashboard
echo 🚀 Starting dashboard service...
docker-compose up -d dashboard

echo.
echo ✅ Dashboard started successfully
echo.

REM Wait for service to be ready
echo ⏳ Waiting for dashboard to be ready...
timeout /t 5 /nobreak >nul

REM Check if service is running
docker-compose ps | findstr /C:"dashboard" | findstr /C:"Up" >nul
if errorlevel 1 (
    echo ❌ Error: Dashboard failed to start
    echo Check logs with: docker-compose logs dashboard
    exit /b 1
)

echo.
echo ✅ Dashboard is running!
echo.
echo 🌐 Access the dashboard at: http://localhost:8501
echo.
echo 📊 To collect data, run:
echo    docker-compose run --rm cli
echo.
echo 📋 Useful commands:
echo    docker-compose logs -f dashboard  # View logs
echo    docker-compose ps                 # Check status
echo    docker-compose down               # Stop services
echo.

pause
