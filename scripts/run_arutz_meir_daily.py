#!/usr/bin/env python3 -u
"""
Python launcher for the daily Arutz Meir scraper (replaces run_arutz_meir_daily.sh).
Used by launchd — avoids macOS 'Operation not permitted' on /bin/bash scripts.
"""

import os
import subprocess
import sys
import time
from datetime import datetime

FUNCTIONS_DIR = "/Users/yaakov/Documents/old_projects/GolandProjects/lesson_center_backend/functions"
LOG_FILE = "/tmp/arutz_meir_daily.log"
FS_PORT = 8191
FS_CONTAINER = "flaresolverr"
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

log_fh = open(LOG_FILE, "a")


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    # Write only to log file — stdout is already redirected to it by launchd/nohup,
    # so printing would cause duplicate lines.
    log_fh.write(line + "\n")
    log_fh.flush()


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ensure_flaresolverr():
    # Check if already running
    r = run(["docker", "ps", "--format", "{{.Names}}"])
    if FS_CONTAINER in r.stdout:
        log("FlareSolverr already running")
        return True

    # Start or create
    r2 = run(["docker", "ps", "-a", "--format", "{{.Names}}"])
    if FS_CONTAINER in r2.stdout:
        log("Starting existing FlareSolverr container...")
        run(["docker", "start", FS_CONTAINER])
    else:
        log("Creating and starting FlareSolverr container...")
        run([
            "docker", "run", "-d", "--name", FS_CONTAINER,
            "-p", f"{FS_PORT}:8191",
            "ghcr.io/flaresolverr/flaresolverr:latest",
        ])

    # Wait up to 60s for ready
    import urllib.request
    for i in range(12):
        time.sleep(5)
        try:
            urllib.request.urlopen(f"http://localhost:{FS_PORT}/", timeout=3)
            log(f"FlareSolverr ready after {(i+1)*5}s")
            return True
        except Exception:
            pass
    log("WARNING: FlareSolverr did not become ready — continuing anyway")
    return False


def main():
    log("========================================")
    log("Arutz Meir daily scraper starting (Python launcher)")
    log(f"DRY_RUN={DRY_RUN}")
    log(f"TELEGRAM={'set' if os.environ.get('TELEGRAM_BOT_TOKEN') else 'NOT SET'}")
    log("========================================")

    ensure_flaresolverr()

    log("Running Arutz Meir scraper (incremental)...")
    sys.path.insert(0, FUNCTIONS_DIR)
    os.chdir(FUNCTIONS_DIR)

    import logging
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)

    from scrapers.arutz_meir_scraper import scrape_arutz_meir
    from utils.telegram_notifier import notify_scrape_results

    result = scrape_arutz_meir(dry_run=DRY_RUN, flaresolverr_port=FS_PORT)
    log(f"Result: created={result['created']} updated={result['updated']} errors={result['errors']}")

    if not DRY_RUN:
        notify_scrape_results({
            'results': {'arutz_meir': result},
            'duration_seconds': result.get('pages_fetched', 0) * 30,
            'scrapers_run': 'arutz_meir',
        })
        log("Telegram notification sent")
    else:
        log("[DRY RUN] Skipping Telegram notification")

    log("Arutz Meir daily scraper done")
    log_fh.close()


if __name__ == "__main__":
    main()
