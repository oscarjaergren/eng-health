"""Main entry point for the Azure DevOps PR Analytics application."""

import sys
from pathlib import Path

# Add the pr_analytics package to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from pr_analytics.core.main import main

if __name__ == "__main__":
    main()
