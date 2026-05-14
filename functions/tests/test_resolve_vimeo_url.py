"""
Tests for the resolve_vimeo_url Cloud Function.

Covers:
  1. Cache hit — Firestore doc exists and not expired → return cached URL, no yt-dlp
  2. Cache expired — doc exists but expires_at is in the past → call yt-dlp
  3. Cache miss — no doc → call yt-dlp, store result
  4. Missing video_id param → HTTP 400
  5. Non-numeric video_id → HTTP 400
  6. yt-dlp failure → HTTP 500
  7. yt-dlp timeout → HTTP 500
  8. Cache read error is non-fatal (falls through to yt-dlp)
  9. Cache write error is non-fatal (still returns URL)
"""

import json
import time
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import the module under test.
# We patch firebase_admin and functions_framework so no real Firebase calls
# happen during import.
# ---------------------------------------------------------------------------

import sys
import os
import types

# Ensure the functions/ directory is on the path so `import main` works whether
# pytest is run from functions/ or from functions/tests/.
_FUNCTIONS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _FUNCTIONS_DIR not in sys.path:
    sys.path.insert(0, _FUNCTIONS_DIR)

# Stub out firebase_admin before importing main
_firebase_stub = types.ModuleType("firebase_admin")
_firebase_stub.get_app = MagicMock(return_value=MagicMock())
_firebase_stub.initialize_app = MagicMock(return_value=MagicMock())
_firestore_stub = types.ModuleType("firebase_admin.firestore")
_firestore_client_mock = MagicMock()
_firestore_stub.client = MagicMock(return_value=_firestore_client_mock)
_firebase_stub.firestore = _firestore_stub

# functions_framework is only needed for the decorator — stub it out
_ff_stub = types.ModuleType("functions_framework")
_ff_stub.http = lambda f: f  # decorator is a no-op
_ff_stub.cloud_event = lambda f: f

sys.modules["firebase_admin"] = _firebase_stub
sys.modules["firebase_admin.firestore"] = _firestore_stub
sys.modules["functions_framework"] = _ff_stub

# Stub out heavy scraper/utility imports
def _make_stub(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod

_youtube_stub = _make_stub("scrapers.youtube_scraper", scrape_youtube_channels=MagicMock(return_value={}))
_bd_stub = _make_stub("scrapers.bnei_david_scraper", scrape_bnei_david=MagicMock(return_value={}))
_am_stub = _make_stub("scrapers.arutz_meir_scraper", scrape_arutz_meir=MagicMock(return_value={}))
_scrapers_stub = _make_stub("scrapers")
_utils_fh_stub = _make_stub(
    "utils.firestore_helper",
    get_timestamp=lambda: int(time.time()),
    FirestoreConnection=MagicMock,
)
_utils_stub = _make_stub("utils")

for name, mod in [
    ("scrapers.youtube_scraper", _youtube_stub),
    ("scrapers.bnei_david_scraper", _bd_stub),
    ("scrapers.arutz_meir_scraper", _am_stub),
    ("scrapers", _scrapers_stub),
    ("utils.firestore_helper", _utils_fh_stub),
    ("utils", _utils_stub),
    ("pyluach", _make_stub("pyluach")),
    ("pyluach.dates", _make_stub("pyluach.dates", HebrewDate=MagicMock)),
    ("isodate", _make_stub("isodate")),
    ("googleapiclient", _make_stub("googleapiclient")),
    ("googleapiclient.discovery", _make_stub("googleapiclient.discovery")),
]:
    sys.modules[name] = mod

import importlib

# Remove cached main module so we import fresh with stubs in place
sys.modules.pop("main", None)
import main as cf  # noqa: E402  (imported after sys.modules patching)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(video_id=None):
    """Return a minimal Flask-like request mock."""
    req = MagicMock()
    req.args = {}
    if video_id is not None:
        req.args["video_id"] = video_id
    return req


def _parse_response(response):
    """Parse the (body_str, status_code, headers) tuple returned by the function."""
    if isinstance(response, tuple):
        body, status, *_ = response
    else:
        body = response
        status = 200
    return json.loads(body), status


def _make_cache_doc(url, expires_at):
    """Return a Firestore DocumentSnapshot-like mock."""
    doc = MagicMock()
    doc.exists = True
    doc.to_dict.return_value = {"url": url, "expires_at": expires_at, "video_id": "1234"}
    return doc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResolveVimeoUrl(unittest.TestCase):

    def setUp(self):
        """Reset Firestore client mock before each test."""
        _firestore_client_mock.reset_mock()

    # -----------------------------------------------------------------------
    # 1. Cache hit
    # -----------------------------------------------------------------------

    def test_cache_hit_returns_cached_url(self):
        """A fresh cache doc must be returned without invoking yt-dlp."""
        fake_url = "https://example.vimeocdn.com/cached.mp4"
        future_expires = time.time() + 3600  # 1 hour from now

        cache_collection_mock = MagicMock()
        doc_ref_mock = MagicMock()
        doc_ref_mock.get.return_value = _make_cache_doc(fake_url, future_expires)
        cache_collection_mock.document.return_value = doc_ref_mock
        _firestore_client_mock.collection.return_value = cache_collection_mock

        with patch.object(cf, "_resolve_via_ytdlp") as mock_ytdlp:
            body, status = _parse_response(cf.resolve_vimeo_url(_make_request("1234")))

        self.assertEqual(status, 200)
        self.assertEqual(body["url"], fake_url)
        self.assertTrue(body["cached"])
        self.assertGreater(body["expires_in_seconds"], 0)
        mock_ytdlp.assert_not_called()

    # -----------------------------------------------------------------------
    # 2. Cache expired
    # -----------------------------------------------------------------------

    def test_cache_expired_calls_ytdlp(self):
        """An expired cache doc must trigger yt-dlp and refresh the cache."""
        old_url = "https://old.example.com/old.mp4"
        new_url = "https://new.vimeocdn.com/fresh.mp4"
        past_expires = time.time() - 60  # expired 1 minute ago

        cache_collection_mock = MagicMock()
        doc_ref_mock = MagicMock()
        doc_ref_mock.get.return_value = _make_cache_doc(old_url, past_expires)
        cache_collection_mock.document.return_value = doc_ref_mock
        _firestore_client_mock.collection.return_value = cache_collection_mock

        with patch.object(cf, "_resolve_via_ytdlp", return_value=new_url) as mock_ytdlp:
            body, status = _parse_response(cf.resolve_vimeo_url(_make_request("1234")))

        self.assertEqual(status, 200)
        self.assertEqual(body["url"], new_url)
        self.assertFalse(body["cached"])
        mock_ytdlp.assert_called_once_with("1234")
        doc_ref_mock.set.assert_called_once()  # cache was written

    # -----------------------------------------------------------------------
    # 3. Cache miss
    # -----------------------------------------------------------------------

    def test_cache_miss_calls_ytdlp(self):
        """When no cache doc exists, yt-dlp must be called and the result cached."""
        new_url = "https://player.vimeo.com/progressive_redirect/playback/9999/x.mp4"

        no_doc = MagicMock()
        no_doc.exists = False

        cache_collection_mock = MagicMock()
        doc_ref_mock = MagicMock()
        doc_ref_mock.get.return_value = no_doc
        cache_collection_mock.document.return_value = doc_ref_mock
        _firestore_client_mock.collection.return_value = cache_collection_mock

        with patch.object(cf, "_resolve_via_ytdlp", return_value=new_url) as mock_ytdlp:
            body, status = _parse_response(cf.resolve_vimeo_url(_make_request("9999")))

        self.assertEqual(status, 200)
        self.assertEqual(body["url"], new_url)
        self.assertFalse(body["cached"])
        self.assertEqual(body["expires_in_seconds"], cf._CACHE_TTL_SECONDS)
        mock_ytdlp.assert_called_once_with("9999")

        # Verify the new URL was stored in Firestore
        doc_ref_mock.set.assert_called_once()
        stored = doc_ref_mock.set.call_args[0][0]
        self.assertEqual(stored["url"], new_url)
        self.assertIn("expires_at", stored)
        self.assertIn("resolved_at", stored)

    # -----------------------------------------------------------------------
    # 4. Missing video_id
    # -----------------------------------------------------------------------

    def test_missing_video_id_returns_400(self):
        """No video_id query param → HTTP 400."""
        body, status = _parse_response(cf.resolve_vimeo_url(_make_request()))
        self.assertEqual(status, 400)
        self.assertIn("error", body)
        self.assertIn("video_id", body["error"])

    # -----------------------------------------------------------------------
    # 5. Non-numeric video_id
    # -----------------------------------------------------------------------

    def test_non_numeric_video_id_returns_400(self):
        """A non-numeric video_id → HTTP 400."""
        body, status = _parse_response(cf.resolve_vimeo_url(_make_request("abc123")))
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    # -----------------------------------------------------------------------
    # 6. yt-dlp failure
    # -----------------------------------------------------------------------

    def test_ytdlp_failure_returns_500(self):
        """RuntimeError from yt-dlp → HTTP 500 with error message."""
        no_doc = MagicMock()
        no_doc.exists = False

        cache_collection_mock = MagicMock()
        doc_ref_mock = MagicMock()
        doc_ref_mock.get.return_value = no_doc
        cache_collection_mock.document.return_value = doc_ref_mock
        _firestore_client_mock.collection.return_value = cache_collection_mock

        with patch.object(cf, "_resolve_via_ytdlp", side_effect=RuntimeError("yt-dlp exited 1: ERROR")):
            body, status = _parse_response(cf.resolve_vimeo_url(_make_request("1234")))

        self.assertEqual(status, 500)
        self.assertIn("error", body)

    # -----------------------------------------------------------------------
    # 7. yt-dlp timeout
    # -----------------------------------------------------------------------

    def test_ytdlp_timeout_returns_500(self):
        """TimeoutExpired from yt-dlp subprocess → HTTP 500."""
        import subprocess

        no_doc = MagicMock()
        no_doc.exists = False

        cache_collection_mock = MagicMock()
        doc_ref_mock = MagicMock()
        doc_ref_mock.get.return_value = no_doc
        cache_collection_mock.document.return_value = doc_ref_mock
        _firestore_client_mock.collection.return_value = cache_collection_mock

        with patch.object(cf, "_resolve_via_ytdlp", side_effect=subprocess.TimeoutExpired("yt-dlp", 45)):
            body, status = _parse_response(cf.resolve_vimeo_url(_make_request("1234")))

        self.assertEqual(status, 500)
        self.assertIn("error", body)
        self.assertIn("timed out", body["error"].lower())

    # -----------------------------------------------------------------------
    # 8. Cache read error is non-fatal
    # -----------------------------------------------------------------------

    def test_cache_read_error_falls_through_to_ytdlp(self):
        """If Firestore throws on read, yt-dlp is called and URL is returned."""
        new_url = "https://player.vimeo.com/progressive_redirect/playback/5678/x.mp4"

        cache_collection_mock = MagicMock()
        doc_ref_mock = MagicMock()
        doc_ref_mock.get.side_effect = Exception("Firestore unavailable")
        cache_collection_mock.document.return_value = doc_ref_mock
        _firestore_client_mock.collection.return_value = cache_collection_mock

        with patch.object(cf, "_resolve_via_ytdlp", return_value=new_url) as mock_ytdlp:
            body, status = _parse_response(cf.resolve_vimeo_url(_make_request("5678")))

        self.assertEqual(status, 200)
        self.assertEqual(body["url"], new_url)
        mock_ytdlp.assert_called_once_with("5678")

    # -----------------------------------------------------------------------
    # 9. Cache write error is non-fatal
    # -----------------------------------------------------------------------

    def test_cache_write_error_still_returns_url(self):
        """If Firestore throws on write, the URL is still returned to the caller."""
        new_url = "https://player.vimeo.com/progressive_redirect/playback/7777/x.mp4"

        no_doc = MagicMock()
        no_doc.exists = False

        cache_collection_mock = MagicMock()
        doc_ref_mock = MagicMock()
        doc_ref_mock.get.return_value = no_doc
        doc_ref_mock.set.side_effect = Exception("Firestore write failed")
        cache_collection_mock.document.return_value = doc_ref_mock
        _firestore_client_mock.collection.return_value = cache_collection_mock

        with patch.object(cf, "_resolve_via_ytdlp", return_value=new_url):
            body, status = _parse_response(cf.resolve_vimeo_url(_make_request("7777")))

        self.assertEqual(status, 200)
        self.assertEqual(body["url"], new_url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
