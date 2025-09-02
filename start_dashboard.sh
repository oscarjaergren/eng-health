#!/bin/bash
# Start Dashboard Script for Azure DevOps PR Analytics

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}🚀 Azure DevOps PR Analytics Dashboard Launcher${NC}"
echo -e "${BLUE}================================================${NC}"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating it...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    echo -e "${GREEN}✅ Activating virtual environment...${NC}"
    source venv/bin/activate
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  .env file not found. Please create it based on .env.example${NC}"
    echo -e "${YELLOW}   Copy .env.example to .env and configure your Azure DevOps credentials${NC}"
    exit 1
fi

# Check if data file exists
if [ ! -f "pr_data.xlsx" ]; then
    echo -e "${YELLOW}⚠️  No data file found. Running data extraction first...${NC}"
    python src/main.py
    if [ $? -ne 0 ]; then
        echo -e "${YELLOW}❌ Data extraction failed. Please check your configuration.${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✅ Starting Streamlit dashboard...${NC}"
echo -e "${BLUE}📊 Dashboard will be available at: http://localhost:8501${NC}"
echo -e "${YELLOW}💡 Press Ctrl+C to stop the dashboard${NC}"
echo

streamlit run dashboard.py
