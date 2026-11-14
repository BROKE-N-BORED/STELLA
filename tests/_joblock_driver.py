"""Helper for the T29 cross-process lock test: holds the Stella job
lock for a home, so the test can prove a second CLI invocation
refuses with the running job named.

Usage: python tests/_joblock_driver.py <home-dir> <job-name>
Prints READY once the lock is held, then sleeps until killed.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from stella.job_lock import job_lock  # noqa: E402

home = Path(sys.argv[1])
name = sys.argv[2] if len(sys.argv) > 2 else "training p1/proj"
with job_lock(home, name):
    print("READY", flush=True)
    while True:
        time.sleep(0.5)
