"""Fetch LigaInsider RSS news and match entries to Kickbase players."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import feedparser
import requests

LIGAINSIDER_RSS_URL = "https://www.ligainsider.de/rss/"
REQUEST_TIMEOUT_SECONDS = 10

POSITIVE_KEYWORDS = (
    "startelf",
    "fit",
    "trainingsrückkehr",
    "kader",
    "einsatzbereit",
    "startet",
    "mit dabei",
    "beschwerdefrei",
)

NEGATIVE_KEYWORDS = (
    "ausfall",
    "verletz",
    "fehlt",
    "gesperrt",
    "fraglich",
    "abbruch",
    "pause",
    "geschont",
    "ausgewechselt",
    "operiert",
)

NEGATIVE_SIGNAL = "🚨 NEGATIV (DROHENDER VERFALL)"
POSITIVE_SIGNAL = "🔥 POSITIV (STEIGERUNG ERWARTET)"


def _text(value: Any) -> str:
    """Return a safe string for values supplied by a feed or API response."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def fetch_latest_news() -> list[dict[str, str]]:
    """Load available LigaInsider RSS items; return an empty list on feed errors."""
    try:
        response = requests.get(
            LIGAINSIDER_RSS_URL,
            headers={"User-Agent": "KickbaseHero/1.0 (RSS news reader)"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except Exception:
        return []

    if getattr(feed, "bozo", False) and not getattr(feed, "entries", None):
        return []

    news: list[dict[str, str]] = []
    for entry in getattr(feed, "entries", []):
        if not isinstance(entry, Mapping):
            continue
        title = _text(entry.get("title"))
        link = _text(entry.get("link"))
        if not title or not link:
            continue
        news.append(
            {
                "title": title,
                "summary": _text(entry.get("summary")),
                "link": link,
                "published": _text(entry.get("published")),
            }
        )
    return news


def _player_name(player: Mapping[str, Any]) -> tuple[str, str]:
    first_name = _text(player.get("firstName"))
    last_name = _text(player.get("lastName"))
    return f"{first_name} {last_name}".strip(), last_name


def match_news_with_players(
    news_list: Sequence[Mapping[str, Any]],
    player_list: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Match each player to their first relevant news item and classify its signal.

    Last-name matching is retained for compatibility with the existing UI, but
    only applies to names longer than three characters to reduce false matches.
    A negative keyword takes precedence when an item contains both signal types.
    """
    alerts: list[dict[str, Any]] = []

    for player in player_list:
        if not isinstance(player, Mapping):
            continue

        full_name, last_name = _player_name(player)
        if not last_name:
            continue

        full_name_pattern = (
            re.compile(rf"\b{re.escape(full_name)}\b", re.IGNORECASE)
            if full_name
            else None
        )
        last_name_pattern = (
            re.compile(rf"\b{re.escape(last_name)}\b", re.IGNORECASE)
            if len(last_name) > 3
            else None
        )

        for item in news_list:
            if not isinstance(item, Mapping):
                continue
            title = _text(item.get("title"))
            summary = _text(item.get("summary"))
            body = f"{title} {summary}"
            if not title or not (
                (full_name_pattern and full_name_pattern.search(body))
                or (last_name_pattern and last_name_pattern.search(body))
            ):
                continue

            normalized = body.casefold()
            is_negative = any(keyword in normalized for keyword in NEGATIVE_KEYWORDS)
            is_positive = any(keyword in normalized for keyword in POSITIVE_KEYWORDS)
            signal = "NEUTRAL"
            if is_negative:
                signal = NEGATIVE_SIGNAL
            elif is_positive:
                signal = POSITIVE_SIGNAL

            alerts.append(
                {
                    "player_id": player.get("id"),
                    "player_name": full_name,
                    "signal": signal,
                    "news_title": title,
                    "link": _text(item.get("link")),
                    "published": _text(item.get("published")),
                }
            )
            break

    return alerts
