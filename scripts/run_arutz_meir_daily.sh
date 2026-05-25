#!/bin/bash
# Daily Arutz Meir scraper — run via macOS launchd Sunday–Friday at 01:00
# Requires: Docker Desktop running (starts FlareSolverr automatically)
#
# Manual run:   bash scripts/run_arutz_meir_daily.sh
# Manual test:  DRY_RUN=1 bash scripts/run_arutz_meir_daily.sh

set -euo pipefail

FUNCTIONS_DIR="/Users/yaakov/Documents/old_projects/GolandProjects/lesson_center_backend/functions"
PYTHON="/Users/yaakov/.pyenv/versions/3.13.3/bin/python3"
LOG_FILE="/tmp/arutz_meir_daily.log"
FS_PORT=8191
FS_CONTAINER="flaresolverr"
DRY_RUN="${DRY_RUN:-0}"

GCLOUD="/opt/homebrew/bin/gcloud"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

log "========================================"
log "Arutz Meir daily scraper starting"
log "DRY_RUN=$DRY_RUN"
log "========================================"

# ── Fetch Telegram token from GCP Secret Manager ──────────────────────────
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
    log "Fetching TELEGRAM_BOT_TOKEN from Secret Manager..."
    export TELEGRAM_BOT_TOKEN=$("$GCLOUD" secrets versions access latest \
        --secret=telegram-bot-token --project=tora-or 2>/dev/null) || true
    if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then
        log "WARNING: Could not fetch TELEGRAM_BOT_TOKEN — Telegram notifications disabled"
    else
        log "TELEGRAM_BOT_TOKEN loaded"
    fi
fi

# ── Start FlareSolverr if not already running ─────────────────────────────
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${FS_CONTAINER}$"; then
    log "FlareSolverr already running"
else
    log "Starting FlareSolverr..."
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^${FS_CONTAINER}$"; then
        docker start "$FS_CONTAINER" >> "$LOG_FILE" 2>&1
        log "FlareSolverr container restarted"
    else
        docker run -d --name "$FS_CONTAINER" -p "${FS_PORT}:8191" \
            ghcr.io/flaresolverr/flaresolverr:latest >> "$LOG_FILE" 2>&1
        log "FlareSolverr container created and started"
    fi
    # Wait for it to be ready
    for i in $(seq 1 12); do
        if curl -sf "http://localhost:${FS_PORT}/" > /dev/null 2>&1; then
            log "FlareSolverr ready after ${i}×5s"
            break
        fi
        sleep 5
    done
fi

# ── Run scraper ───────────────────────────────────────────────────────────
log "Running Arutz Meir scraper (incremental)..."
cd "$FUNCTIONS_DIR"

"$PYTHON" -c "
import sys, logging
sys.path.insert(0, '.')
logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)

from scrapers.arutz_meir_scraper import scrape_arutz_meir
from utils.telegram_notifier import notify_scrape_results
from datetime import datetime
import os

dry_run = os.environ.get('DRY_RUN', '0') == '1'
print(f'[{datetime.now().strftime(\"%H:%M:%S\")}] dry_run={dry_run}', flush=True)

result = scrape_arutz_meir(dry_run=dry_run, flaresolverr_port=${FS_PORT})

print(f'Result: created={result[\"created\"]} updated={result[\"updated\"]} errors={result[\"errors\"]}', flush=True)

if not dry_run:
    notify_scrape_results({
        'results': {'arutz_meir': result},
        'duration_seconds': result.get('pages_fetched', 0) * 30,
        'scrapers_run': 'arutz_meir',
    })
    print('Telegram notification sent', flush=True)
else:
    print('[DRY RUN] Skipping Telegram notification', flush=True)
" 2>&1 | tee -a "$LOG_FILE"

log "Arutz Meir daily scraper done"
