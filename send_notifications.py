#!/usr/bin/env python3
"""
Standalone script to send weekly home check-in emails.
Run this via cron or a scheduler (e.g., Saturday mornings at 8am).

Example cron entry (every Saturday at 8am):
0 8 * * 6 cd /path/to/HomeList && /path/to/venv/bin/python send_notifications.py
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add current directory to path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import send_weekly_checkin

if __name__ == '__main__':
    print("Starting weekly home check-in job...")
    count = send_weekly_checkin()
    print(f"Job complete. Sent {count} notification(s).")
    sys.exit(0)
