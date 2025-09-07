@echo off
REM Start Dashboard Script for Azure DevOps PR Analytics (Windows)

echo 🚀 Azure DevOps PR Analytics Dashboard Launcher
echo ================================================

REM Check if virtual environment exists
if not exist "venv" (
    echo ⚠️  Virtual environment not found. Creating it...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    echo ✅ Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Check if .env file exists
if not exist ".env" (
    echo ⚠️  .env file not found. Please create it based on .env.example
    echo    Copy .env.example to .env and configure your credentials
    exit /b 1
)

REM Check if data file exists
if not exist "pr_data.xlsx" (
    echo ⚠️  No data file found. Running data extraction first...
    python main.py
    if errorlevel 1 (
        echo ❌ Data extraction failed. Please check your configuration.
        exit /b 1
    )
)

echo ✅ Starting Streamlit dashboard...
echo 📊 Dashboard will be available at: http://localhost:8501
echo 💡 Press Ctrl+C to stop the dashboard
echo.

streamlit run dashboard_main.py
