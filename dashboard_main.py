"""Main entry point for the Streamlit dashboard."""

import sys
from pathlib import Path

# Add the pr_analytics package to the Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import and run the dashboard
from pr_analytics.dashboard.dashboard import main

if __name__ == "__main__":
    main()
