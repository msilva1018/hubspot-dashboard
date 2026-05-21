"""
HubSpot API client for the KPI dashboard.

Wraps the marketing emails statistics endpoint and the CRM engagements
endpoints. Uses Streamlit's cache so repeated calls within a session
don't hammer HubSpot's rate limits.

Required private app scopes:
  - content
  - marketing-email
  - crm.objects.contacts.read
  - sales-email-read
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
import streamlit as st

BASE_URL = "https://api.hubapi.com"
DEFAULT_TIMEOUT = 30


class HubSpotError(Exception):
    """Raised when the HubSpot API returns a non-recoverable error."""


@dataclass
class HubSpotConfig:
    access_token: str
    portal_id: str | None = None


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _request(
    method: str,
    path: str,
    token: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    max_retries: int = 3,
) -> dict[str, Any]:
    """Make a request with simple exponential backoff on 429s."""
    url = f"{BASE_URL}{path}"
    attempt = 0
    while True:
        resp = requests.request(
            method,
            url,
            headers=_headers(token),
            params=params,
            json=json_body,
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code == 429 and attempt < max_retries:
            # rate limited — back off and retry
            wait = 2**attempt
            time.sleep(wait)
            attempt += 1
            continue
        if not resp.ok:
            raise HubSpotError(
                f"HubSpot API {resp.status_code} for {method} {path}: {resp.text[:300]}"
            )
        return resp.json() if resp.text else {}


# ---------------------------------------------------------------------------
# Marketing email statistics
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def get_email_statistics(
    token: str,
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """
    Aggregated marketing-email statistics over a time span.

    Endpoint: GET /marketing/v3/emails/statistics/list
    """
    params = {
        "startTimestamp": start.astimezone(timezone.utc).isoformat(),
        "endTimestamp": end.astimezone(timezone.utc).isoformat(),
    }
    return _request("GET", "/marketing/v3/emails/statistics/list", token, params=params)


@st.cache_data(ttl=600, show_spinner=False)
def get_email_statistics_intervals(
    token: str,
    start: datetime,
    end: datetime,
    interval: str = "DAY",
) -> dict[str, Any]:
    """
    Time-series email statistics broken into intervals.

    interval: one of MINUTE, HOUR, DAY, WEEK, MONTH, QUARTER, YEAR
    Endpoint: GET /marketing/v3/emails/statistics/histogram
    """
    params = {
        "startTimestamp": start.astimezone(timezone.utc).isoformat(),
        "endTimestamp": end.astimezone(timezone.utc).isoformat(),
        "interval": interval,
    }
    return _request(
        "GET", "/marketing/v3/emails/statistics/histogram", token, params=params
    )


# ---------------------------------------------------------------------------
# Engagements (email opens, document-attached emails, etc.)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def get_recent_email_engagements(
    token: str,
    since: datetime,
    limit_per_page: int = 100,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    """
    Pull recent EMAIL engagements created since `since`.

    Uses the legacy engagements v1 'recent/modified' endpoint, which
    returns activities across the portal sorted by lastUpdated desc.
    We filter to type == 'EMAIL' client-side because the legacy endpoint
    doesn't accept a type filter param.
    """
    since_ms = int(since.timestamp() * 1000)
    results: list[dict[str, Any]] = []
    offset: int | None = None

    for _ in range(max_pages):
        params: dict[str, Any] = {"count": limit_per_page, "since": since_ms}
        if offset is not None:
            params["offset"] = offset

        data = _request(
            "GET", "/engagements/v1/engagements/recent/modified", token, params=params
        )
        page = data.get("results", [])
        for item in page:
            eng = item.get("engagement", {})
            if eng.get("type") == "EMAIL":
                results.append(item)

        if not data.get("hasMore"):
            break
        offset = data.get("offset")

    return results


def summarize_engagements(engagements: list[dict[str, Any]]) -> dict[str, int]:
    """Quick rollup of engagement counts by status."""
    summary = {"total": 0, "opened": 0, "replied": 0, "with_attachment": 0}
    for item in engagements:
        eng = item.get("engagement", {})
        meta = item.get("metadata", {})
        attachments = item.get("attachments", []) or []

        summary["total"] += 1
        # The metadata for email engagements often carries opens/replies status
        if meta.get("emailStatus") == "OPENED" or meta.get("openCount", 0) > 0:
            summary["opened"] += 1
        if meta.get("replyCount", 0) > 0:
            summary["replied"] += 1
        if attachments:
            summary["with_attachment"] += 1
        _ = eng  # currently unused beyond filtering
    return summary


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------
def default_window(days: int = 30) -> tuple[datetime, datetime]:
    """Return (start, end) for the last `days` days, UTC."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    return start, end
