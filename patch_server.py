import sys

with open('src/ui/api/server.py', 'r') as f:
    content = f.read()

replacement = """from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timezone

# Global scheduler for desktop background tasks
scheduler = BackgroundScheduler()

# Global state for health reporting
system_health_state = {
    "last_poll_at": None,
}

from fastapi import FastAPI
"""

if "system_health_state =" not in content:
    content = content.replace("from fastapi import FastAPI", replacement)

with open('src/ui/api/server.py', 'w') as f:
    f.write(content)
