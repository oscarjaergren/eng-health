"""Main entry point for the Streamlit dashboard."""

import sys
from pathlib import Path

# Add the azure_pr_analytics package to the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import and run the dashboard
from azure_pr_analytics.dashboard.dashboard import *

# This file serves as the entry point for running: streamlit run dashboard_main.py
