"""
Utility for fetching lesson duration from audio file or Vimeo.
Used by both the Arutz Meir scraper and the backfill script.

Priority:
  1. Audio file range request (128KB, reads MPEG Xing/LAME header)
  2. CBR fallback: file size / bitrate from Content-Range header
  3. Vimeo v2 data API (no auth needed)
"""

import io
import re

import requests

_RANGE_BYTES = 131072  # 128KB


def get_duration_from_audio_url(url: str, session: requests.Session | None = None) -> int | None:
    """Returns duration in seconds from audio file, or None on failure."""
    try:
        from mutagen.mp3 import MP3
        s = session or requests.Session()
        r = s.get(url, headers={"Range": f"bytes=0-{_RANGE_BYTES - 1}"}, timeout=15)
        if r.status_code not in (200, 206):
            return None
        audio = MP3(io.BytesIO(r.content))
        if audio.info.length > 0:
            return int(audio.info.length)
        if audio.info.bitrate > 0:
            m = re.search(r"/(\d+)$", r.headers.get("Content-Range", ""))
            if m:
                return int(int(m.group(1)) * 8 / audio.info.bitrate)
    except Exception:
        pass
    return None


def get_duration_from_vimeo(vimeo_id: str, session: requests.Session | None = None) -> int | None:
    """Returns duration in seconds from Vimeo v2 API, or None on failure."""
    try:
        s = session or requests.Session()
        r = s.get(f"https://vimeo.com/api/v2/video/{vimeo_id}.json", timeout=10)
        if r.status_code == 200:
            data = r.json()
            d = data[0] if isinstance(data, list) else data
            duration = d.get("duration")
            return int(duration) if duration else None
    except Exception:
        pass
    return None


def get_duration(site_audio_url: str | None = None,
                 vimeo_id: str | None = None,
                 session: requests.Session | None = None) -> int:
    """
    Try all sources in order, return duration in seconds (0 if nothing works).
      1. Audio file (site_audio_url)
      2. Vimeo API (vimeo_id)
    """
    if site_audio_url:
        d = get_duration_from_audio_url(site_audio_url, session)
        if d:
            return d
    if vimeo_id:
        d = get_duration_from_vimeo(vimeo_id, session)
        if d:
            return d
    return 0
