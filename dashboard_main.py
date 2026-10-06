"""Run with: streamlit run dashboard_main.py (plain `python dashboard_main.py` works too)."""

import subprocess
import sys

from streamlit import runtime

from pr_analytics.dashboard.app import main

if runtime.exists():
    main()
else:
    # Started with plain Python (e.g. an editor's Run button): Streamlit needs its own runner.
    sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", __file__, *sys.argv[1:]]))
