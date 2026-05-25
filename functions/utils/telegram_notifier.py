"""
Telegram notification for nightly scraper runs.
Sends a summary to the tora_or_update channel after each scrape.
"""

import logging
import os
import requests

logger = logging.getLogger(__name__)

CHANNEL_ID = -1003941357070
MAX_MSG_LEN = 4000


def _send(token: str, text: str):
    """Send one message, splitting if over the limit."""
    chunks = [text[i:i + MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)]
    for chunk in chunks:
        try:
            r = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': CHANNEL_ID, 'text': chunk, 'parse_mode': 'HTML'},
                timeout=10,
            )
            if not r.ok:
                logger.warning(f'Telegram send failed: {r.text}')
        except Exception as e:
            logger.warning(f'Telegram send error: {e}')


def _fmt_duration(seconds: int) -> str:
    if not seconds:
        return ''
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m}:{s:02d}'


def notify_scrape_results(results: dict):
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.info('TELEGRAM_BOT_TOKEN not set — skipping notification')
        return

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    lines = [f'🕍 <b>ToraOr nightly scrape — {now}</b>']

    scrapers = results.get('results', {})
    total_new = 0

    # ── YouTube ──────────────────────────────────────────────────────────────
    yt = scrapers.get('youtube', {})
    if 'error' in yt:
        lines.append(f'\n📺 <b>YouTube</b>: ❌ {yt["error"]}')
    else:
        yt_total = yt.get('lessons_added', 0)
        total_new += yt_total
        channels = yt.get('channel_details', [])
        if channels:
            lines.append(f'\n📺 <b>YouTube — {yt_total} new lessons</b>')
            for ch in channels:
                lines.append(f'\n  📡 <b>{ch["label"]}</b>')
                for lesson in ch.get('lessons', []):
                    title = lesson.get('title', '')
                    serie = lesson.get('serie', '')
                    date = lesson.get('date', '')
                    dur = _fmt_duration(lesson.get('duration', 0))
                    detail = f'  • {title}'
                    if serie and serie != 'כללי':
                        detail += f'\n    📚 {serie}'
                    if date:
                        detail += f'  [{date}]'
                    if dur:
                        detail += f'  ⏱{dur}'
                    lines.append(detail)
        else:
            lines.append(f'\n📺 <b>YouTube</b>: no new lessons')

    # ── Bnei David ────────────────────────────────────────────────────────────
    bd = scrapers.get('bnei_david', {})
    if 'error' in bd:
        lines.append(f'\n🏛 <b>Bnei David</b>: ❌ {bd["error"]}')
    else:
        bd_new = bd.get('created', 0)
        bd_upd = bd.get('updated', 0)
        total_new += bd_new
        if bd_new > 0:
            lines.append(f'\n🏛 <b>Bnei David — {bd_new} new lessons</b>')
            for item in bd.get('sample_lessons', []):
                if item.get('action') != 'created':
                    continue
                title = item.get('title', '')
                lines.append(f'  • {title}')
            new_series = bd.get('new_series_created', [])
            for s in new_series:
                lines.append(f'  📚 New series: {s}')
        else:
            lines.append(f'\n🏛 <b>Bnei David</b>: no new lessons ({bd_upd} updated)')

    # ── Arutz Meir ────────────────────────────────────────────────────────────
    am = scrapers.get('arutz_meir', {})
    if 'error' in am:
        lines.append(f'\n📻 <b>Arutz Meir</b>: ❌ {am["error"]}')
    elif am:
        am_new = am.get('created', 0)
        am_upd = am.get('updated', 0)
        total_new += am_new
        if am_new > 0:
            lines.append(f'\n📻 <b>Arutz Meir — {am_new} new lessons</b>')
            for item in am.get('new_lesson_details', am.get('sample_lessons', [])):
                # support both new_lesson_details and legacy sample_lessons
                if isinstance(item, dict) and item.get('action') == 'updated':
                    continue
                title = item.get('title', '')
                date = item.get('date') or item.get('dateStr', '')
                vimeo = item.get('vimeoId')
                audio = item.get('siteAudioUrl')
                media = '🎥' if vimeo else ('🔊' if audio else '❓')
                detail = f'  {media} {title}'
                if date:
                    detail += f'  [{date}]'
                lines.append(detail)
        else:
            lines.append(f'\n📻 <b>Arutz Meir</b>: no new lessons ({am_upd} updated)')
    else:
        lines.append(f'\n📻 <b>Arutz Meir</b>: disabled')

    # ── Errors / warnings ────────────────────────────────────────────────────
    yt_errors = yt.get('errors', [])
    if yt_errors:
        lines.append(f'\n⚠️ YouTube errors ({len(yt_errors)}):')
        for e in yt_errors[:3]:
            lines.append(f'  • {e.get("label","")}: {str(e.get("error",""))[:80]}')

    # ── Footer ────────────────────────────────────────────────────────────────
    duration = results.get('duration_seconds', 0)
    lines.append(f'\n📊 <b>Total new: {total_new}</b>  ⏱ {int(duration)}s')

    _send(token, '\n'.join(lines))
