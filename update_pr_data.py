#!/usr/bin/env python3
"""
Enhanced PR Data Update Script

This script regenerates the PR data with detailed review analytics including:
- PR comments and commenters
- Approval/rejection data  
- Review discussion threads
- Detailed reviewer information

Run this script to update your existing pr_data.xlsx with enhanced review metrics.
"""

import sys
import os
from pathlib import Path

# Add src directory to path
sys.path.append(str(Path(__file__).parent / 'src'))

from src.main import main

if __name__ == "__main__":
    print("🚀 Starting Enhanced PR Data Collection...")
    print("📊 This will collect detailed review analytics including:")
    print("   • PR comments and who made them")
    print("   • Approval/rejection data")
    print("   • Review discussion threads")
    print("   • Detailed reviewer votes")
    print()
    
    try:
        main()
        print()
        print("✅ Enhanced PR data collection completed!")
        print("🎯 You can now use the new 'Review Analytics' tab in the dashboard")
        print("🔄 Refresh your Streamlit dashboard to see the new features")
        
    except Exception as e:
        print(f"❌ Error during data collection: {e}")
        print("💡 Make sure your .env file is properly configured")
        sys.exit(1)
