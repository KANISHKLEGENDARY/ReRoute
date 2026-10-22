"""
Root proxy to backend/scripts/seed_demo.py
"""

import asyncio
import os
import sys

# Ensure backend root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from scripts.seed_demo import seed_demo

if __name__ == "__main__":
    asyncio.run(seed_demo())
