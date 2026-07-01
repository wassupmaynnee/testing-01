"""
OAuth publishing core (YouTube).

Frozen contract preserved exactly:
  * OAuth 2.0 ONLY. There is no password/browser-automation upload path.
  * Clips are uploaded at PRIVATE visibility, ALWAYS. `privacyStatus` is
    hard-coded to "private" in `video_insert_body()` and is not a caller
    parameter — there is no way to request public/unlisted from this module.
  * Nothing is ever auto-published: a clip only uploads in response to an
    explicit `publish_private()` call wired to a deliberate user action.
  * Tokens are stored ENCRYPTED at rest (saas/crypto.py); the Google client
    libraries are lazy-loaded ONLY when a client id is configured, so the app
    boots and every non-publishing path works with the libs absent.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from .config import get_settings
from .crypto import decrypt, encrypt

# Frozen visibility — uploads are private, full stop.
PRIVATE_VISIBILITY = "private"

# Scopes: upload to the user's own channel, read the channel title/stats to label
# and report on the connected account, and read the account's OWN analytics. No
# read of other people's data.
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    ANALYTICS_SCOPE,
]
PROVIDER_YOUTUBE = "youtube"


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    enabled: bool


def youtube_enabled() -> bool:
    s = get_settings()
    return bool(s.youtube_oauth_client_id and s.youtube_oauth_client_secret)


def providers() -> list[dict]:
    """Catalog of publishing destinations + whether each is configured."""
    return [Provider(PROVIDER_YOUTUBE, "YouTube", youtube_enabled()).__dict__]


# --------------------------------------------------------------------------- #
# CSRF state — bind the OAuth `state` to the signed-in user so a stray callback #
# cannot attach someone else's tokens to this account.                         #
# --------------------------------------------------------------------------- #
def make_state(user_id: str) -> str:
    secret = get_settings().app_secret.encode()
    sig = hmac.new(secret, user_id.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{user_id}.{sig}"


def verify_state(state: str, user_id: str) -> bool:
    expected = make_state(user_id)
    return hmac.compare_digest(state or "", expected)


# --------------------------------------------------------------------------- #
# Google OAuth flow (lazy-loaded).                                            #
# --------------------------------------------------------------------------- #
def _client_config() -> dict:
    s = get_settings()
    return {
        "web": {
            "client_id": s.youtube_oauth_client_id,
            "client_secret": s.youtube_oauth_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [s.youtube_oauth_redirect_uri],
        }
    }


def _flow(state: str | None = None):
    """Build a google-auth-oauthlib Flow. Imported lazily (env-gated path)."""
    from google_auth_oauthlib.flow import Flow  # noqa: PLC0415

    s = get_settings()
    flow = Flow.from_client_config(
        _client_config(),
        scopes=YOUTUBE_SCOPES,
        state=state,
    )
    flow.redirect_uri = s.youtube_oauth_redirect_uri
    return flow


def authorize_url(user_id: str) -> str:
    """Build the Google consent URL for the signed-in user (offline access)."""
    flow = _flow(state=make_state(user_id))
    url, _ = flow.authorization_url(
        access_type="offline",       # request a refresh token
        include_granted_scopes="true",
        prompt="consent",            # force refresh-token issuance on reconnect
    )
    return url


def _channel_title(credentials) -> str | None:
    """Best-effort label for the connected account (the channel title)."""
    try:
        from googleapiclient.discovery import build  # noqa: PLC0415

        yt = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        resp = yt.channels().list(part="snippet", mine=True).execute()
        items = resp.get("items") or []
        if items:
            return items[0]["snippet"]["title"]
    except Exception:  # noqa: BLE001 — labeling is cosmetic, never block connect
        return None
    return None


def _expiry_to_dt(credentials) -> datetime | None:
    exp = getattr(credentials, "expiry", None)
    if exp is None:
        return None
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp


def connect_account(db, user, code: str) -> dict:
    """Exchange an auth code for tokens and persist them ENCRYPTED (upsert)."""
    from .models import OAuthAccount

    flow = _flow(state=make_state(user.id))
    flow.fetch_token(code=code)
    creds = flow.credentials

    label = _channel_title(creds)
    account = (
        db.query(OAuthAccount)
        .filter(OAuthAccount.user_id == user.id, OAuthAccount.provider == PROVIDER_YOUTUBE)
        .one_or_none()
    )
    if account is None:
        account = OAuthAccount(user_id=user.id, provider=PROVIDER_YOUTUBE)
        db.add(account)

    account.access_token_enc = encrypt(creds.token or "")
    # Google only returns a refresh token on first consent; keep the existing one
    # if a re-consent omits it.
    if creds.refresh_token:
        account.refresh_token_enc = encrypt(creds.refresh_token)
    account.token_expiry = _expiry_to_dt(creds)
    account.scope = " ".join(creds.scopes or YOUTUBE_SCOPES)
    if label:
        account.account_label = label
    db.commit()

    return {
        "provider": PROVIDER_YOUTUBE,
        "accountLabel": account.account_label,
        "connectedAt": account.created_at.isoformat() if account.created_at else None,
    }


def connected_accounts(db, user) -> list[dict]:
    from .models import OAuthAccount

    rows = (
        db.query(OAuthAccount)
        .filter(OAuthAccount.user_id == user.id)
        .order_by(OAuthAccount.created_at.asc())
        .all()
    )
    return [
        {
            "provider": r.provider,
            "accountLabel": r.account_label,
            "scope": r.scope,
            "connectedAt": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def disconnect(db, user, provider: str) -> bool:
    from .models import OAuthAccount

    account = (
        db.query(OAuthAccount)
        .filter(OAuthAccount.user_id == user.id, OAuthAccount.provider == provider)
        .one_or_none()
    )
    if account is None:
        return False
    db.delete(account)
    db.commit()
    return True


# --------------------------------------------------------------------------- #
# Analytics — the connected channel's OWN metrics (read-only).                 #
#                                                                              #
# "Real-time" done honestly: results are cached for _ANALYTICS_TTL to respect  #
# YouTube's quotas, stamped with lastUpdated, and on any quota/rate-limit/      #
# network error we serve the last-known values marked stale instead of         #
# crashing. Only data for the user's OWN connected+authorized channel is ever  #
# surfaced (private-by-default respected).                                     #
# --------------------------------------------------------------------------- #
_ANALYTICS_TTL = 300  # seconds
_ANALYTICS_CACHE: dict[str, tuple[float, dict]] = {}


def _fetch_youtube_analytics(db, account) -> dict:
    from googleapiclient.discovery import build  # noqa: PLC0415

    creds = _credentials_for(db, account)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    ya = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    end = date.today()
    start = end - timedelta(days=28)
    channels = []
    for it in yt.channels().list(part="snippet,statistics", mine=True).execute().get("items", []):
        stats = it.get("statistics", {})
        row = {
            "channelId": it.get("id"),
            "title": it.get("snippet", {}).get("title"),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "totalViews": int(stats.get("viewCount", 0)),
            "videos": int(stats.get("videoCount", 0)),
            "last28": None,
        }
        try:
            rep = ya.reports().query(
                ids="channel==MINE",
                startDate=start.isoformat(),
                endDate=end.isoformat(),
                metrics="views,likes,estimatedMinutesWatched,subscribersGained",
            ).execute()
            totals = (rep.get("rows") or [[0, 0, 0, 0]])[0]
            row["last28"] = {
                "views": int(totals[0]), "likes": int(totals[1]),
                "minutesWatched": int(totals[2]), "subscribersGained": int(totals[3]),
            }
        except Exception:  # noqa: BLE001,S110 — analytics report can fail independently of channel stats
            pass
        channels.append(row)
    return {
        "connected": True, "needsReconnect": False, "channels": channels,
        "accountLabel": account.account_label,
        "lastUpdated": datetime.now(timezone.utc).isoformat(), "stale": False,
    }


def channel_analytics(db, user, force: bool = False) -> dict:
    """The user's connected-channel analytics with a lastUpdated stamp. Cached to
    respect quotas. Prompts reconnect (does NOT crash) when an older token lacks
    the analytics scope."""
    from .models import OAuthAccount

    account = (
        db.query(OAuthAccount)
        .filter(OAuthAccount.user_id == user.id, OAuthAccount.provider == PROVIDER_YOUTUBE)
        .one_or_none()
    )
    if account is None:
        return {"connected": False, "channels": [], "lastUpdated": None}

    if ANALYTICS_SCOPE not in (account.scope or "").split():
        return {
            "connected": True, "needsReconnect": True,
            "reason": "Reconnect YouTube to grant analytics access.",
            "accountLabel": account.account_label, "channels": [], "lastUpdated": None,
        }

    now = time.time()
    cached = _ANALYTICS_CACHE.get(user.id)
    if not force and cached and now - cached[0] < _ANALYTICS_TTL:
        return cached[1]
    try:
        data = _fetch_youtube_analytics(db, account)
    except Exception as exc:  # noqa: BLE001 — quota/rate-limit/network: serve last-known
        if cached:
            stale = dict(cached[1])
            stale.update(stale=True, error=str(exc))
            return stale
        return {
            "connected": True, "channels": [], "error": str(exc),
            "accountLabel": account.account_label, "lastUpdated": None, "stale": True,
        }
    _ANALYTICS_CACHE[user.id] = (now, data)
    return data


# --------------------------------------------------------------------------- #
# Upload — PRIVATE, always.                                                    #
# --------------------------------------------------------------------------- #
def video_insert_body(title: str, description: str, tags: list[str] | None = None) -> dict:
    """
    Build the YouTube `videos.insert` request body. PURE + deterministic so the
    private-default contract is unit-testable. `privacyStatus` is hard-coded to
    PRIVATE_VISIBILITY and is intentionally NOT a parameter.
    """
    return {
        "snippet": {
            "title": (title or "Clippify clip")[:100],
            "description": description or "Created with Clippify.",
            "tags": tags or ["clippify", "shorts"],
            "categoryId": "22",  # People & Blogs
        },
        "status": {
            "privacyStatus": PRIVATE_VISIBILITY,  # FROZEN: private, never public
            "selfDeclaredMadeForKids": False,
            "embeddable": True,
        },
    }


def _credentials_for(db, account):
    """Rebuild google Credentials from the encrypted store; refresh if expired."""
    from google.auth.transport.requests import Request  # noqa: PLC0415
    from google.oauth2.credentials import Credentials  # noqa: PLC0415

    s = get_settings()
    creds = Credentials(
        token=decrypt(account.access_token_enc) or None,
        refresh_token=decrypt(account.refresh_token_enc) if account.refresh_token_enc else None,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s.youtube_oauth_client_id,
        client_secret=s.youtube_oauth_client_secret,
        scopes=(account.scope or "").split() or YOUTUBE_SCOPES,
    )
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        account.access_token_enc = encrypt(creds.token or "")
        account.token_expiry = _expiry_to_dt(creds)
        db.commit()
    return creds


def publish_private(db, user, clip) -> dict:
    """
    Upload a finished clip to the user's YouTube channel at PRIVATE visibility.
    Explicit user action only — never called automatically by the pipeline.
    """
    from pathlib import Path

    from googleapiclient.discovery import build  # noqa: PLC0415
    from googleapiclient.http import MediaFileUpload  # noqa: PLC0415

    from .models import OAuthAccount

    account = (
        db.query(OAuthAccount)
        .filter(OAuthAccount.user_id == user.id, OAuthAccount.provider == PROVIDER_YOUTUBE)
        .one_or_none()
    )
    if account is None:
        raise LookupError("no_connected_account")

    if not Path(clip.file_path).exists():
        raise FileNotFoundError("clip_file_missing")

    creds = _credentials_for(db, account)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)

    body = video_insert_body(
        title=clip.title or "Clippify clip",
        description="Vertical highlight clip created with Clippify.",
    )
    media = MediaFileUpload(clip.file_path, mimetype="video/mp4", resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _status, response = request.next_chunk()

    video_id = response.get("id")
    return {
        "provider": PROVIDER_YOUTUBE,
        "videoId": video_id,
        "url": f"https://youtu.be/{video_id}" if video_id else None,
        "privacyStatus": PRIVATE_VISIBILITY,
        "accountLabel": account.account_label,
    }
