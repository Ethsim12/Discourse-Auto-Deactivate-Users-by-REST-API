#!/usr/bin/env python3
import os, sys, time, random, requests
from datetime import datetime, timedelta
from requests.exceptions import ConnectionError, Timeout

BASE_URL = os.environ["DISCOURSE_BASE_URL"].rstrip("/")
API_KEY = os.environ["DISCOURSE_API_KEY"]
API_USER = os.environ.get("DISCOURSE_API_USER", "system")

# --- knobs you can tweak ---
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
FILTER = os.environ.get("USER_FILTER", "active")
LAST_SEEN_BEFORE_DAYS = int(os.environ.get("LAST_SEEN_BEFORE_DAYS", "365"))
INCLUDE_TRUST_LEVELS = set(map(int, os.environ.get("INCLUDE_TL", "0,1,2,3,4").split(",")))
EXCLUDE_STAFF = os.environ.get("EXCLUDE_STAFF", "true").lower() == "true"

# Backoff settings
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "8"))
BASE_BACKOFF = float(os.environ.get("BASE_BACKOFF", "1.0"))   # seconds
MAX_BACKOFF = float(os.environ.get("MAX_BACKOFF", "60.0"))    # seconds
# --------------------------

S = requests.Session()
S.headers.update({
    "Api-Key": API_KEY,
    "Api-Username": API_USER,
    "Accept": "application/json"
})

def _sleep_with_jitter(seconds):
    # Full jitter: [0, seconds]
    time.sleep(random.uniform(0, max(0.0, seconds)))

def _compute_backoff(attempt):
    return min(MAX_BACKOFF, BASE_BACKOFF * (2 ** attempt))

def _respect_retry_after(resp):
    """Returns seconds to wait if Retry-After is present and valid, else None."""
    ra = resp.headers.get("Retry-After")
    if not ra:
        return None
    try:
        # Value can be seconds or HTTP-date; Discourse uses seconds.
        return max(0, int(ra))
    except ValueError:
        return None

def _request_with_backoff(method, url, **kwargs):
    attempt = 0
    while True:
        try:
            r = S.request(method, url, timeout=30, **kwargs)
        except (ConnectionError, Timeout) as e:
            if attempt >= MAX_RETRIES:
                raise
            wait = _compute_backoff(attempt)
            print(f"[BACKOFF] network error ({e.__class__.__name__}); retry {attempt+1}/{MAX_RETRIES} in ~{wait:.1f}s")
            _sleep_with_jitter(wait)
            attempt += 1
            continue

        # Success fast path
        if 200 <= r.status_code < 300:
            return r

        # Rate limit / overload handling
        if r.status_code in (429, 503):
            # Prefer server-provided hint
            ra = _respect_retry_after(r)
            if ra is not None:
                wait = ra
            else:
                wait = _compute_backoff(attempt)
            if attempt >= MAX_RETRIES:
                r.raise_for_status()
            print(f"[BACKOFF] {r.status_code} received; retry {attempt+1}/{MAX_RETRIES} in ~{wait:.1f}s")
            _sleep_with_jitter(wait)
            attempt += 1
            continue

        # Retry select 5xx
        if 500 <= r.status_code < 600:
            if attempt >= MAX_RETRIES:
                r.raise_for_status()
            wait = _compute_backoff(attempt)
            print(f"[BACKOFF] {r.status_code} server error; retry {attempt+1}/{MAX_RETRIES} in ~{wait:.1f}s")
            _sleep_with_jitter(wait)
            attempt += 1
            continue

        # Anything else: fail immediately
        r.raise_for_status()

def list_users(filter_name, page=0):
    url = f"{BASE_URL}/admin/users/list/{filter_name}.json?page={page}"
    r = _request_with_backoff("GET", url)
    return r.json()

def deactivate_user(user_id):
    url = f"{BASE_URL}/admin/users/{user_id}/deactivate.json"
    r = _request_with_backoff("PUT", url)
    # Treat any 2xx as success; _request_with_backoff already raised otherwise
    return True

# ... rest of the script (parse_dt, should_target, main) unchanged ...
