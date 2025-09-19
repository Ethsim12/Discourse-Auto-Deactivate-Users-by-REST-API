#!/usr/bin/env python3
import os, sys, time, random, requests
from datetime import datetime, timedelta, timezone
from requests.exceptions import ConnectionError, Timeout

# --- required env ---
BASE_URL = os.environ["DISCOURSE_BASE_URL"].rstrip("/")
API_KEY  = os.environ["DISCOURSE_API_KEY"]
API_USER = os.environ.get("DISCOURSE_API_USER", "system")

# --- knobs you can tweak (via env) ---
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() == "true"
FILTER = os.environ.get("USER_FILTER", "active")  # e.g. active|new|trust_level_0
LAST_SEEN_BEFORE_DAYS = int(os.environ.get("LAST_SEEN_BEFORE_DAYS", "365"))
INCLUDE_TRUST_LEVELS = set(map(int, os.environ.get("INCLUDE_TL", "0,1,2,3,4").split(",")))
EXCLUDE_STAFF = os.environ.get("EXCLUDE_STAFF", "true").lower() == "true"
MAX_PAGES = int(os.environ.get("MAX_PAGES", "100"))  # safety cap for pagination

# Backoff settings
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "8"))
BASE_BACKOFF = float(os.environ.get("BASE_BACKOFF", "1.0"))   # seconds
MAX_BACKOFF = float(os.environ.get("MAX_BACKOFF", "60.0"))    # seconds
# -------------------------------------

S = requests.Session()
S.headers.update({
    "Api-Key": API_KEY,
    "Api-Username": API_USER,
    "Accept": "application/json"
})

def _sleep_with_jitter(seconds: float):
    # Full jitter in [0, seconds]
    time.sleep(random.uniform(0, max(0.0, seconds)))

def _compute_backoff(attempt: int) -> float:
    return min(MAX_BACKOFF, BASE_BACKOFF * (2 ** attempt))

def _respect_retry_after(resp) -> int | None:
    """Return seconds to wait if Retry-After present and numeric, else None."""
    ra = resp.headers.get("Retry-After")
    if not ra:
        return None
    try:
        return max(0, int(ra))
    except ValueError:
        return None

def _request_with_backoff(method: str, url: str, **kwargs) -> requests.Response:
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

        if 200 <= r.status_code < 300:
            return r

        if r.status_code in (429, 503):
            ra = _respect_retry_after(r)
            wait = ra if ra is not None else _compute_backoff(attempt)
            if attempt >= MAX_RETRIES:
                r.raise_for_status()
            print(f"[BACKOFF] {r.status_code} received; retry {attempt+1}/{MAX_RETRIES} in ~{wait:.1f}s")
            _sleep_with_jitter(wait)
            attempt += 1
            continue

        if 500 <= r.status_code < 600:
            if attempt >= MAX_RETRIES:
                r.raise_for_status()
            wait = _compute_backoff(attempt)
            print(f"[BACKOFF] {r.status_code} server error; retry {attempt+1}/{MAX_RETRIES} in ~{wait:.1f}s")
            _sleep_with_jitter(wait)
            attempt += 1
            continue

        # Other 4xx etc.: fail immediately (bad auth, permissions, etc.)
        r.raise_for_status()

def list_users(filter_name: str, page: int = 0):
    url = f"{BASE_URL}/admin/users/list/{filter_name}.json?page={page}"
    r = _request_with_backoff("GET", url)
    return r.json()

def deactivate_user(user_id: int) -> bool:
    url = f"{BASE_URL}/admin/users/{user_id}/deactivate.json"
    _request_with_backoff("PUT", url)
    return True

def parse_dt(s: str | None) -> datetime | None:
    """
    Discourse returns ISO8601 strings; sometimes 'Z' suffix.
    Return timezone-aware datetime (UTC if no tz given).
    """
    if not s:
        return None
    # Normalize 'Z' → '+00:00'
    iso = s.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt

def should_target(u: dict) -> bool:
    """
    Decide if user should be deactivated (forced to reverify on next login).
    Rules:
      - must be active
      - skip staged/suspended
      - skip staff (admin/mod) if EXCLUDE_STAFF
      - trust_level must be in INCLUDE_TRUST_LEVELS
      - last_seen_at older than cutoff (or never seen)
    """
    if not u.get("active"):
        return False
    if u.get("staged") or u.get("suspended"):
        return False
    if EXCLUDE_STAFF and (u.get("admin") or u.get("moderator")):
        return False

    tl = u.get("trust_level")
    try:
        tl = int(tl) if tl is not None else None
    except (TypeError, ValueError):
        tl = None
    if tl is None or tl not in INCLUDE_TRUST_LEVELS:
        return False

    last_seen = parse_dt(u.get("last_seen_at"))
    if last_seen is None:
        return True  # never seen → include

    # Compute cutoff in the same tz as last_seen
    now = datetime.now(tz=last_seen.tzinfo or timezone.utc)
    cutoff = now - timedelta(days=LAST_SEEN_BEFORE_DAYS)
    return last_seen < cutoff

def main():
    # sanity check env
    missing = [k for k in ("DISCOURSE_BASE_URL","DISCOURSE_API_KEY") if k not in os.environ]
    if missing:
        print("Missing required env: " + ", ".join(missing), file=sys.stderr)
        sys.exit(2)

    page = 0
    to_act: list[dict] = []

    while page < MAX_PAGES:
        batch = list_users(FILTER, page=page)
        if not batch:
            break
        for u in batch:
            if should_target(u):
                to_act.append(u)
        page += 1

    print(f"Found {len(to_act)} user(s) to deactivate (DRY_RUN={DRY_RUN}).", flush=True)

    failures = 0
    acted = 0
    for u in to_act:
        uid = u.get("id")
        uname = u.get("username") or "unknown"
        email = u.get("email") or ""  # email visible to admins; may be absent
        try:
            if DRY_RUN:
                print(f"[DRY] would deactivate id={uid} @{uname} {email}")
            else:
                deactivate_user(uid)
                print(f"[OK ] deactivated id={uid} @{uname} {email}")
                acted += 1
        except Exception as e:
            failures += 1
            print(f"[ERR] id={uid} @{uname}: {e}", file=sys.stderr)

    print(f"Summary: acted={acted}, failures={failures}, evaluated={len(to_act)} (pages scanned={page})")
    if failures:
        sys.exit(1)

if __name__ == "__main__":
    main()