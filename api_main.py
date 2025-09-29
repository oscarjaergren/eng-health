"""
Main entry point for the PR Analytics API.

This script starts the FastAPI server for the PR Analytics API.
"""

import os
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv

    # Load environment variables
    load_dotenv()

    # Get configuration from environment
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = os.getenv("API_RELOAD", "false").lower() == "true"

    print(f"🚀 Starting PR Analytics API on http://{host}:{port}")
    print(f"📚 API Documentation: http://{host}:{port}/docs")
    print(f"📖 ReDoc Documentation: http://{host}:{port}/redoc")
    print("-" * 60)

    # Start the API server
    uvicorn.run(
        "azure_pr_analytics.api.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
