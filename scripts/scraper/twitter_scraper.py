#!/usr/bin/env python3
"""Scrape X/Twitter trending topics and search (no-login + cookie-based).

Modes:
  trending   — REST API, no login required (api.x.com/1.1/trends/place.json)
  search     — requires cookies from a logged-in browser session.
               Pass --cookies /path/to/twitter_cookies.json to use saved auth.

Usage:
    python twitter_scraper.py trending --count 20
    python twitter_scraper.py search --query "SFMCompile" --cookies cookies.json
    python twitter_scraper.py search --query "python" --user "karpathy" --cookies cookies.json
    python twitter_scraper.py trending --woeid 1 --output trends.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("twitter_scraper")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

_GUEST_TOKEN_CACHE: str | None = None


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Trend:
    name: str = ""
    post_count: int | None = None
    category: str = ""
    url: str = ""
    rank: int = 0
    query: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if isinstance(self.post_count, str):
            try:
                self.post_count = int(self.post_count) if self.post_count else None
            except ValueError:
                self.post_count = 0


@dataclass
class Tweet:
    id: str = ""
    author_name: str = ""
    author_handle: str = ""
    author_avatar: str = ""
    text: str = ""
    text_cleaned: str = ""
    timestamp: str = ""
    permalink: str = ""
    reply_count: int = 0
    retweet_count: int = 0
    like_count: int = 0
    view_count: int = 0
    is_verified: bool = False
    has_media: bool = False
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_guest_token(session: requests.Session) -> str:
    """Obtain a guest token for unauthenticated API access."""
    global _GUEST_TOKEN_CACHE
    if _GUEST_TOKEN_CACHE:
        return _GUEST_TOKEN_CACHE

    resp = session.post(
        "https://api.twitter.com/1.1/guest/activate.json",
        headers={"Authorization": f"Bearer {BEARER_TOKEN}"},
        timeout=15,
    )
    resp.raise_for_status()
    _GUEST_TOKEN_CACHE = resp.json()["guest_token"]
    return _GUEST_TOKEN_CACHE


def _auth_headers(session: requests.Session, guest_token: str | None = None) -> dict[str, str]:
    """Build auth headers for X.com API calls."""
    if guest_token is None:
        guest_token = _get_guest_token(session)
    headers: dict[str, str] = {
        "authorization": f"Bearer {BEARER_TOKEN}",
        "x-guest-token": guest_token,
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "content-type": "application/json",
        "origin": "https://x.com",
        "referer": "https://x.com/",
    }
    ct0 = session.cookies.get("ct0")
    if ct0:
        headers["x-csrf-token"] = ct0
    return headers


def _load_cookies(path: str) -> dict[str, str]:
    """Load a cookies JSON file (list of {name, value} dicts)."""
    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, list):
        return {c["name"]: c["value"] for c in data}
    if isinstance(data, dict):
        return data
    return {}


# ---------------------------------------------------------------------------
# Trending (REST API — no login required)
# ---------------------------------------------------------------------------

WOEID_MAP: dict[str, int] = {
    "worldwide": 1,
    "united_states": 23424977,
    "japan": 23424856,
    "india": 23424848,
    "united_kingdom": 23424975,
    "canada": 23424775,
    "australia": 23424748,
    "brazil": 23424768,
    "germany": 23424829,
    "france": 23424819,
    "russia": 23424936,
    "mexico": 23424900,
    "indonesia": 23424846,
    "turkey": 23424969,
    "italy": 23424853,
    "spain": 23424950,
}


def _parse_volume(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def fetch_trending(
    woeid: int = 1,
    max_count: int = 20,
) -> list[Trend]:
    """Fetch trending topics from X.com REST API (no login needed).

    WOEID 1 = worldwide. See WOEID_MAP for country codes.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    session.get("https://x.com/", timeout=15)

    gt = _get_guest_token(session)
    headers = _auth_headers(session, gt)

    resp = session.get(
        f"https://api.x.com/1.1/trends/place.json?id={woeid}",
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    trends: list[Trend] = []
    for rank, trend in enumerate(data[0].get("trends", []), 1):
        if len(trends) >= max_count:
            break
        name = trend.get("name", "")
        if not name:
            continue

        volume = _parse_volume(trend.get("tweet_volume"))
        query = trend.get("query", "")
        url = f"https://x.com/search?q={query}&src=trend_click" if query else ""

        trends.append(
            Trend(
                name=name,
                post_count=volume,
                category="Trending",
                url=url,
                rank=rank,
                query=query,
            )
        )

    return trends


# ---------------------------------------------------------------------------
# Search (requires authentication cookies)
# ---------------------------------------------------------------------------

SEARCH_QUERY_ID = "dsWn-Op2S0SmJjgY6Yvckg"  # SearchTimeline


def fetch_tweets(
    query: str,
    cookies: dict[str, str] | None = None,
    from_user: str = "",
    max_count: int = 20,
) -> list[Tweet]:
    """Search X for tweets — requires auth cookies from a logged-in session.

    Args:
        query: Search query string.
        cookies: Dict of cookies from an authenticated X.com session.
        from_user: Optional username filter (without @).
        max_count: Max tweets to return (max 50).
    """
    if not cookies:
        raise ValueError(
            "X.com search requires authentication cookies. "
            "Export cookies from a logged-in browser session."
        )

    session = requests.Session()
    session.headers.update({"User-Agent": _USER_AGENT})
    session.cookies.update(cookies)

    auth_token = cookies.get("auth_token") or session.cookies.get("auth_token")
    if not auth_token:
        raise ValueError("Cookies must contain 'auth_token' from a logged-in session")

    # Visit x.com to establish session
    session.get("https://x.com/", timeout=15)

    gt = _get_guest_token(session)
    headers = _auth_headers(session, gt)

    search_query = f"{query} from:{from_user}" if from_user else query
    max_count = min(max_count, 50)

    variables = {
        "rawQuery": search_query,
        "count": min(max_count, 20),
        "cursor": None,
        "querySource": "typed_query",
        "product": "Top",
    }
    features = {
        "rweb_video_screen_enabled": True,
        "rweb_cashtags_enabled": True,
        "profile_label_improvements_pcf_label_in_post_enabled": True,
        "responsive_web_profile_redirect_enabled": True,
        "rweb_tipjar_consumption_enabled": True,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "premium_content_api_read_enabled": True,
        "communities_web_enable_tweet_community_results_fetch": True,
        "c9s_tweet_anatomy_moderator_badge_enabled": True,
        "articles_preview_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "responsive_web_twitter_article_tweet_consumption_enabled": True,
        "tweet_awards_web_tipping_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_enhance_cards_enabled": False,
        "rweb_video_timestamps_enabled": True,
        "responsive_web_grok_analyze_button_fetch_trends_enabled": True,
    }

    resp = session.post(
        f"https://api.x.com/graphql/{SEARCH_QUERY_ID}/SearchTimeline",
        json={"variables": variables, "features": features},
        headers=headers,
        timeout=20,
    )

    if resp.status_code == 404:
        raise ValueError("GraphQL search returned 404. Cookies may be expired.")
    if resp.status_code in (401, 403):
        raise ValueError("Access forbidden. Cookies may be expired or blocked.")
    resp.raise_for_status()

    result = resp.json()
    tweets = _parse_tweets_from_timeline(result)
    return tweets[:max_count]


def _parse_tweets_from_timeline(data: dict) -> list[Tweet]:
    """Parse tweets from GraphQL SearchTimeline response."""
    tweets: list[Tweet] = []
    seen_ids: set[str] = set()

    instructions = (
        data.get("data", {})
        .get("search_by_raw_query", {})
        .get("search_timeline", {})
        .get("timeline", {})
        .get("instructions", [])
    )

    for instruction in instructions:
        entries = instruction.get("entries", [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_id = entry.get("entryId", "")
            if not entry_id or "tweet" not in entry_id:
                continue

            tweet_id = entry_id.removeprefix("tweet-").split("|")[0]
            if tweet_id in seen_ids:
                continue
            seen_ids.add(tweet_id)

            result = (
                entry.get("content", {})
                .get("itemContent", {})
                .get("tweetResult", {})
                .get("result", {})
            )
            if not result:
                continue

            legacy = result.get("legacy", {})
            user = result.get("core", {}).get("user_results", {}).get("result", {}).get("legacy", {})
            if not legacy:
                continue

            tweet = _parse_tweet_result(tweet_id, legacy, user)
            if tweet:
                tweets.append(tweet)

    return tweets


def _parse_tweet_result(tweet_id: str, legacy: dict, user: dict) -> Tweet | None:
    """Extract a Tweet dataclass from raw legacy + user objects."""
    text = legacy.get("full_text", "") or legacy.get("text", "")
    if not text:
        return None

    text_cleaned = re.sub(r"[\U0001F300-\U0010FFFF]", "", text)
    text_cleaned = re.sub(r"\s+", " ", text_cleaned).strip()

    permalink = f"https://x.com/{user.get('screen_name', '')}/status/{tweet_id}"

    reply_count = legacy.get("reply_count", 0) or 0
    retweet_count = legacy.get("retweet_count", 0) or 0
    like_count = legacy.get("favorite_count", 0) or 0

    # View count — may be in ext or as a separate field
    view_count = 0
    ext_views = legacy.get("ext", {}).get("views", {}).get("count", "")
    if ext_views:
        try:
            view_count = int(ext_views)
        except (ValueError, TypeError):
            view_count = 0

    media_entities = (
        legacy.get("entities", {}).get("media", [])
        or legacy.get("extended_entities", {}).get("media", [])
    )
    has_media = len(media_entities) > 0

    timestamp = ""
    created_at = legacy.get("created_at", "")
    if created_at:
        try:
            dt = datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y")
            timestamp = dt.isoformat()
        except ValueError:
            timestamp = created_at

    return Tweet(
        id=tweet_id,
        author_name=user.get("name", ""),
        author_handle=f"@{user.get('screen_name', '')}",
        author_avatar=user.get("profile_image_url_https", ""),
        text=text,
        text_cleaned=text_cleaned[:500],
        timestamp=timestamp,
        permalink=permalink,
        reply_count=reply_count,
        retweet_count=retweet_count,
        like_count=like_count,
        view_count=view_count,
        is_verified=user.get("verified", False),
        has_media=has_media,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape X/Twitter trending topics and search tweets",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    trend_p = sub.add_parser("trending", help="Scrape trending topics (no login)")
    trend_p.add_argument("--count", "-n", type=int, default=20, help="Max trends")
    trend_p.add_argument("--woeid", type=int, default=1,
                         help="WOEID location (1=worldwide). See WOEID_MAP for countries.")
    trend_p.add_argument("--location", type=str, default="",
                         help="Named location (e.g. 'united_states', 'japan')")
    trend_p.add_argument("--output", "-o", type=str, default="", help="Output JSON path")
    trend_p.add_argument("--verbose", "-v", action="store_true", help="Debug logging")

    search_p = sub.add_parser("search", help="Search for tweets (requires --cookies)")
    search_p.add_argument("--query", "-q", type=str, required=True, help="Search query")
    search_p.add_argument("--user", "-u", type=str, default="", help="Filter by user (no @)")
    search_p.add_argument("--count", "-n", type=int, default=20, help="Max tweets")
    search_p.add_argument("--cookies", "-c", type=str, required=True,
                          help="Path to auth cookies JSON file")
    search_p.add_argument("--output", "-o", type=str, default="", help="Output JSON path")
    search_p.add_argument("--verbose", "-v", action="store_true", help="Debug logging")

    return parser


def timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main() -> None:
    args = build_parser().parse_args()

    log_fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=log_fmt,
        datefmt="%H:%M:%S",
    )

    if args.command == "trending":
        woeid = args.woeid
        if args.location:
            woeid = WOEID_MAP.get(args.location, woeid)
            if args.verbose:
                logger.info("Location '%s' → WOEID %s", args.location, woeid)

        trends = fetch_trending(woeid=woeid, max_count=args.count)
        ts_str = timestamp_now()

        output_file = args.output or f"twitter_trends_{ts_str[:10]}.json"
        data = {"scraped_at": ts_str, "count": len(trends), "woeid": woeid,
                "trends": [asdict(t) for t in trends]}
        Path(output_file).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"\n{'─' * 60}")
        print(f"  {len(trends)} trending topics (WOEID {woeid})")
        print(f"  Output: {output_file}")
        print(f"{'─' * 60}")
        for t in trends[:15]:
            vol = f" — {t.post_count:,} posts" if t.post_count else ""
            print(f"  {t.rank:2d}. {t.name}{vol}")
        if len(trends) > 15:
            print(f"  … and {len(trends) - 15} more")

        if trends:
            ts_compact = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            print(f"\n### Trending — {ts_compact}")
            print()
            print("| # | Topic | Posts |")
            print("|---|-------|-------|")
            for t in trends[:25]:
                vol = str(t.post_count) if t.post_count else ""
                print(f"| {t.rank} | {t.name} | {vol} |")

    elif args.command == "search":
        cookies = _load_cookies(args.cookies)
        tweets = fetch_tweets(
            query=args.query,
            from_user=args.user,
            cookies=cookies,
            max_count=args.count,
        )
        ts_str = timestamp_now()
        output_file = args.output or f"twitter_search_{args.query.replace(' ', '_')}_{ts_str[:10]}.json"

        data = {"scraped_at": ts_str, "query": args.query, "from_user": args.user,
                "count": len(tweets), "tweets": [asdict(t) for t in tweets]}
        Path(output_file).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        print(f"\n{'─' * 60}")
        print(f"  {len(tweets)} tweets for '{args.query}'")
        print(f"  Output: {output_file}")
        print(f"{'─' * 60}")
        for tw in tweets[:15]:
            handle = tw.author_handle or "?"
            text_short = tw.text_cleaned[:80].replace("\n", " ")
            print(f"  • {handle}: {text_short}")
        if len(tweets) > 15:
            print(f"  … and {len(tweets) - 15} more")

        if tweets:
            ts_compact = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            print(f"\n### Tweets — {ts_compact}")
            print()
            print("| # | Author | Tweet | Likes | RTs | Replies |")
            print("|---|--------|-------|-------|-----|---------|")
            for i, tw in enumerate(tweets[:25], 1):
                text_short = tw.text_cleaned[:60].replace("\n", " ")
                print(f"| {i} | {tw.author_handle} | {text_short} | {tw.like_count} | {tw.retweet_count} | {tw.reply_count} |")


if __name__ == "__main__":
    main()