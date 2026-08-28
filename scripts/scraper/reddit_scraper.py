#!/usr/bin/env python3
"""Scrape r/python hot posts from old.reddit.com HTML and save to JSON."""

import json
import re
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

JSON_FILE = "rpython_hot.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}
COOKIES = {"over18": "1"}


def parse_score(text: str | None) -> int | None:
    """Parse a score string like '242 points' or '•' into int or None."""
    if not text or text.strip() in ("•", ""):
        return None
    m = re.search(r"[\d,.]+", text.replace(",", ""))
    return int(m.group()) if m else None


def parse_comments(text: str | None) -> int | None:
    """Parse a comments string like '41 comments' or 'comment' into int."""
    if not text:
        return None
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else 0


def fetch_posts(url: str, max_pages: int = 1) -> list[dict]:
    """Fetch Reddit posts by scraping old.reddit.com HTML, paginating if needed."""
    all_posts: list[dict] = []
    seen_ids: set[str] = set()
    current_url: str | None = url

    for page in range(max_pages):
        if not current_url:
            break

        try:
            resp = requests.get(current_url, headers=HEADERS, cookies=COOKIES, timeout=15)
            resp.raise_for_status()
        except requests.Timeout:
            print(f"Request timed out after 15s: {current_url}", file=sys.stderr)
            if page == 0:
                raise
            break
        except (requests.ConnectionError, requests.HTTPError) as e:
            print(f"Failed to fetch {current_url}: {e}", file=sys.stderr)
            if page == 0:
                raise
            break

        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            print(f"Failed to parse HTML from {current_url}: {e}", file=sys.stderr)
            if page == 0:
                raise
            break

        page_posts: list[dict] = []

        for thing in soup.select("div[id^='thing_']"):
            title_link = thing.select_one("a.title")
            if not title_link:
                continue

            pid = thing.get("id", "").removeprefix("thing_")
            if pid in seen_ids:
                continue
            seen_ids.add(pid)

            author_el = thing.select_one("a.author")
            score_el = thing.select_one("div.score.unvoted")
            comments_el = thing.select_one("a.comments")

            try:
                score = parse_score(score_el.get_text(strip=True) if score_el else None)
                comments = parse_comments(comments_el.get_text(strip=True) if comments_el else None)
            except (ValueError, AttributeError):
                score = None
                comments = None

            entry = {
                "id": pid,
                "title": title_link.get_text(strip=True),
                "url": title_link.get("href", ""),
                "permalink": "",
                "author": author_el.get_text(strip=True) if author_el else None,
                "score": score,
                "num_comments": comments,
                "flair": "",
            }

            href = title_link.get("href", "")
            if href.startswith("/r/"):
                entry["permalink"] = f"https://reddit.com{href}"
            else:
                entry["permalink"] = href

            flair_el = thing.select_one("span.flair")
            if flair_el:
                entry["flair"] = flair_el.get_text(strip=True)

            page_posts.append(entry)

        all_posts.extend(page_posts)
        print(f"  Page {page + 1}: {len(page_posts)} posts", file=sys.stderr)

        # Find next page link
        next_el = soup.select_one("span.next-button a[rel='next']")
        current_url = next_el.get("href") if next_el else None

    return all_posts


def save_json(posts: list[dict], path: str, subreddit: str = "", feed: str = "") -> None:
    """Write posts to a JSON file with a scraped_at timestamp."""
    output = {
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "subreddit": subreddit,
        "feed": feed,
        "post_count": len(posts),
        "posts": posts,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"Failed to write {path}: {e}", file=sys.stderr)
        raise


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Scrape Reddit posts or user submissions")
    parser.add_argument("--subreddit", default="", help="Subreddit to scrape")
    parser.add_argument("--user", default="", help="Reddit user to scrape posts from")
    parser.add_argument("--search", default="", help="Search Reddit for keyword(s)")
    parser.add_argument("--feed", default="hot", choices=["hot", "new", "top", "submitted"])
    parser.add_argument("--keyword", nargs="*", help="Filter posts by keyword(s)")
    parser.add_argument("--author", nargs="*", help="Filter posts by author(s) (case-insensitive)")
    parser.add_argument("--output", default="", help="Output JSON path")
    parser.add_argument("--pages", type=int, default=1, help="Number of pages to scrape")
    parser.add_argument("--top", action="store_true", help="Scrape top posts of all time (highest score)")
    args = parser.parse_args()

    if args.search:
        query = "+".join(args.search.split())
        url = f"https://old.reddit.com/search?q={query}&restrict_sr=off&sort=new"
        output = args.output or f"reddit_search_{args.search.replace(' ', '_')}.json"
        subreddit_name = f"search:{args.search}"
    elif args.user:
        feed_path = "submitted" if not args.top else "top"
        url = f"https://old.reddit.com/user/{args.user}/{feed_path}/"
        output = args.output or f"reddit_user_{args.user}.json"
        subreddit_name = f"u/{args.user}"
    elif args.subreddit:
        url = f"https://old.reddit.com/r/{args.subreddit}/{args.feed}/"
        output = args.output or f"reddit_{args.subreddit}_{args.feed}.json"
        subreddit_name = args.subreddit
    else:
        parser.error("specify --subreddit, --user, or --search")

    try:
        posts = fetch_posts(url, max_pages=args.pages)
    except requests.RequestException as e:
        print(f"Aborting: {e}", file=sys.stderr)
        sys.exit(1)

    if not posts:
        print("No posts found.", file=sys.stderr)
        sys.exit(0)

    if args.keyword:
        pattern = "|".join(re.escape(kw) for kw in args.keyword)
        posts = [p for p in posts if re.search(pattern, p["title"], re.IGNORECASE)]

    if args.author:
        author_pattern = "|".join(re.escape(a) for a in args.author)
        posts = [p for p in posts if p["author"] and re.search(author_pattern, p["author"], re.IGNORECASE)]

    # Sort by score descending if --top (filter to highest-scored)
    if args.top:
        valid = [p for p in posts if p["score"] is not None]
        valid.sort(key=lambda p: p["score"], reverse=True)

    save_json(posts, output, subreddit=subreddit_name, feed=args.feed)

    for p in posts[:20]:
        score_str = f"{p['score']} pts" if p['score'] is not None else "?"
        comments_str = f"{p['num_comments']} comments" if p['num_comments'] is not None else "?"
        print(f"  {p['title'][:80]:80s} {score_str:>8s}  {comments_str:>12s}")

    print(f"\nTotal: {len(posts)} posts saved to {output}")


if __name__ == "__main__":
    main()