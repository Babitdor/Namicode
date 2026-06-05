#!/usr/bin/env python3
"""Scrape GitHub trending repositories and save to a markdown file."""

import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from requests.exceptions import ConnectionError, Timeout

TRENDING_URL = "https://github.com/trending"
MD_FILE = "github_trending.md"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class Retryable5xx(Exception):
    """Raised for 5xx HTTP responses that should be retried."""
    pass


def parse_stars(text: str) -> int:
    """Parse a star/fork count like '13,784' or '3,142 stars today'."""
    cleaned = re.sub(r"[^\d,]", "", text)
    return int(cleaned.replace(",", "")) if cleaned else 0


def fetch_trending(url: str = TRENDING_URL) -> list[dict]:
    """Parse GitHub trending page and return a list of repo dicts.

    Retries up to 3 times with exponential backoff on transient HTTP errors
    (timeouts, connection errors, 5xx).  Client errors (4xx) are not retried.
    """
    @retry(
        retry=retry_if_exception_type((Timeout, ConnectionError, Retryable5xx)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _do_request() -> requests.Response:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=15
        )
        if resp.status_code >= 500:
            raise Retryable5xx(resp.status_code)
        return resp

    resp = _do_request()

    soup = BeautifulSoup(resp.text, "html.parser")
    repos: list[dict] = []

    for article in soup.select("article.Box-row"):
        h2 = article.find("h2")
        if not h2:
            continue

        link = h2.find("a")
        if not link:
            continue

        # Owner/repo name from h2 text: "owner /\nrepo"
        full_name = h2.get_text(" ", strip=True).replace(" / ", "/")
        href = link.get("href", "").strip("/")

        # Description
        desc_p = article.find("p", class_="col-9")
        description = desc_p.get_text(strip=True) if desc_p else ""

        # Language
        lang_span = article.find("span", itemprop="programmingLanguage")
        language = lang_span.get_text(strip=True) if lang_span else "Unknown"

        # Stars (href ends with /stargazers)
        star_el = article.find("a", href=re.compile(r"/stargazers$"))
        stars = parse_stars(star_el.get_text(strip=True)) if star_el else 0

        # Forks (href ends with /forks)
        fork_el = article.find("a", href=re.compile(r"/forks$"))
        forks = parse_stars(fork_el.get_text(strip=True)) if fork_el else 0

        # Stars today
        today_el = article.find("span", class_="d-inline-block")
        # today_el might be the "3,142 stars today" span
        today_text = ""
        if today_el:
            txt = today_el.get_text(strip=True)
            if "stars today" in txt:
                today_text = txt

        repos.append(
            {
                "name": full_name,
                "url": f"https://github.com/{href}",
                "description": description,
                "language": language,
                "stars": stars,
                "forks": forks,
                "stars_today": today_text,
            }
        )

    return repos


def save_markdown(repos: list[dict], path: str = MD_FILE) -> None:
    """Write repos to a markdown file."""
    scraped_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# GitHub Trending Repositories",
        "",
        f"_Scraped at: {scraped_at}_  ",
        f"_Total: {len(repos)} repositories_",
        "",
        "---",
        "",
    ]

    for i, repo in enumerate(repos, 1):
        desc = (
            f"> {repo['description']}" if repo["description"] else ""
        )
        today = f" ⭐ **{repo['stars_today']}**" if repo["stars_today"] else ""
        lines.extend(
            [
                f"### {i}. [{repo['name']}]({repo['url']}){today}",
                "",
                f"| Language | Stars | Forks |",
                f"|----------|-------|-------|",
                f"| {repo['language']} | {repo['stars']:,} | {repo['forks']:,} |",
                "",
                desc,
                "",
                "---",
                "",
            ]
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    try:
        repos = fetch_trending()
    except requests.RequestException as e:
        print(f"Failed to fetch trending: {e}", file=sys.stderr)
        sys.exit(1)

    if not repos:
        print("No repos found — the page structure may have changed.", file=sys.stderr)
        sys.exit(1)

    save_markdown(repos)
    print(f"Saved {len(repos)} trending repos to {MD_FILE}")


if __name__ == "__main__":
    main()