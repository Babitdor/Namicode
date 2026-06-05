#!/usr/bin/env python3
"""Scrape Hacker News front-page headlines and save to CSV (async)."""

import asyncio
import csv
import sys
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

HN_URL = "https://news.ycombinator.com/"
CSV_FILE = "hn_headlines.csv"


async def fetch_headlines(url: str = HN_URL) -> list[dict[str, str]]:
    """Parse Hacker News front page and return a list of headline dicts."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

    title_rows = soup.select("span.titleline > a")
    headlines: list[dict[str, str]] = []

    for a_tag in title_rows:
        title = a_tag.get_text(strip=True)
        link = a_tag.get("href", "")
        headlines.append({"title": title, "url": link})

    return headlines


def write_csv(headlines: list[dict[str, str]], path: str = CSV_FILE) -> None:
    """Write headlines to a CSV file with a timestamp column."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "title", "url"])
        writer.writeheader()
        for h in headlines:
            writer.writerow({"timestamp": ts, "title": h["title"], "url": h["url"]})


async def main() -> None:
    try:
        headlines = await fetch_headlines()
    except httpx.HTTPError as e:
        print(f"Failed to fetch {HN_URL}: {e}", file=sys.stderr)
        sys.exit(1)

    write_csv(headlines)
    print(f"Saved {len(headlines)} headlines to {CSV_FILE}")


if __name__ == "__main__":
    asyncio.run(main())