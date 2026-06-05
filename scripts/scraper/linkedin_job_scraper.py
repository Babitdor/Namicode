#!/usr/bin/env python3
"""LinkedIn job scraper — focused on AI Engineer roles.

Scrapes LinkedIn job search results without requiring a login.
Uses Playwright to handle JavaScript-rendered content.

Usage:
    python linkedin_job_scraper.py --keyword "AI Engineer" --location "United States" --pages 3
    python linkedin_job_scraper.py --keyword "Data Scientist" --location "Remote" --pages 1 --verbose

Outputs to linkedin_jobs_<keyword>_<timestamp>.json by default.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

logger = logging.getLogger("linkedin_scraper")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class JobPosting:
    title: str = ""
    company: str = ""
    company_url: str = ""
    location: str = ""
    url: str = ""
    posted_date: str = ""
    description_snippet: str = ""
    salary: str = ""
    employment_type: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class LinkedInJobScraper:
    """Scrape LinkedIn job listings using Playwright."""

    SEARCH_URL = "https://www.linkedin.com/jobs/search"

    def __init__(
        self,
        headless: bool = True,
        delay: float = 1.0,
        verbose: bool = False,
    ):
        self.headless = headless
        self.delay = delay
        self.verbose = verbose

    def search(
        self,
        keyword: str,
        location: str = "",
        max_pages: int = 1,
    ) -> list[JobPosting]:
        """Run the search across pages, return all job postings."""
        keyword_clean = keyword.strip()
        location_clean = location.strip()

        all_jobs: list[JobPosting] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()

            try:
                page_num = 0
                while page_num < max_pages:
                    start = page_num * 25
                    url = self._build_url(keyword_clean, location_clean, start)
                    logger.info(
                        "Page %s/%s — %s", page_num + 1, max_pages, url,
                    )

                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)

                    # Scroll to trigger lazy-loaded images / content
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)

                    # Wait for the results UL
                    try:
                        page.wait_for_selector("ul.jobs-search__results-list", timeout=10000)
                    except Exception:
                        logger.warning("No results <ul> found — may be blocked or no results")
                        break

                    # Extract cards
                    items = page.query_selector_all("ul.jobs-search__results-list > li")
                    logger.info("Found %s result cards", len(items))

                    if not items:
                        break

                    fresh = 0
                    for item in items:
                        job = self._extract_card(item)
                        if job and job.title:
                            all_jobs.append(job)
                            fresh += 1

                    logger.info("  → %s new jobs (total: %s)", fresh, len(all_jobs))

                    # If fewer than 25 results, we've exhausted results
                    if len(items) < 25:
                        break

                    page_num += 1
                    time.sleep(self.delay)

            finally:
                ctx.close()
                browser.close()

        return all_jobs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_url(self, keyword: str, location: str, start: int) -> str:
        kw = keyword.replace(" ", "%20")
        loc = location.replace(" ", "%20") if location else ""
        return f"{self.SEARCH_URL}?keywords={kw}&location={loc}&start={start}"

    def _extract_card(self, item) -> Optional[JobPosting]:
        """Pull title, company, location, date, URL from a single result card."""
        try:
            card = item.query_selector("div.base-card")
            if not card:
                return None

            title_el = card.query_selector("h3.base-search-card__title")
            company_el = card.query_selector("h4.base-search-card__subtitle a")
            location_el = card.query_selector("span.job-search-card__location")
            date_el = card.query_selector(
                "time.job-search-card__listdate--new, time.job-search-card__listdate",
            )
            link_el = card.query_selector("a.base-card__full-link")

            title = title_el.inner_text().strip() if title_el else ""
            company = company_el.inner_text().strip() if company_el else ""
            company_href = company_el.get_attribute("href") or "" if company_el else ""
            location = location_el.inner_text().strip() if location_el else ""

            # Date: prefer datetime attribute, fallback to text
            posted_date = date_el.get_attribute("datetime") if date_el else ""
            if not posted_date and date_el:
                posted_date = date_el.inner_text().strip()

            # URL: strip tracking params
            url = link_el.get_attribute("href") if link_el else ""
            if url:
                url = re.sub(r"\?.*", "", url)

            if not title:
                return None

            return JobPosting(
                title=title,
                company=company,
                company_url=company_href if company_href.startswith("http") else f"https://www.linkedin.com{company_href}" if company_href else "",
                location=location,
                url=url,
                posted_date=posted_date,
            )

        except Exception as exc:
            if self.verbose:
                logger.debug("Failed to extract card: %s", exc)
            return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape LinkedIn job postings for a keyword",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--keyword", "-k", default="AI Engineer", help="Job title / keyword")
    parser.add_argument("--location", "-l", default="United States", help="Location filter")
    parser.add_argument("--pages", "-p", type=int, default=1, help="Number of result pages (25 per page)")
    parser.add_argument("--delay", "-d", type=float, default=1.0, help="Delay between pages (seconds)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug-level logging")
    parser.add_argument("--output", "-o", type=str, default="", help="Output file path (auto-generated if empty)")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser headless")
    parser.add_argument("--no-headless", action="store_false", dest="headless", help="Show browser window")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    log_fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format=log_fmt,
        datefmt="%H:%M:%S",
    )

    logger.info(
        "Searching LinkedIn Jobs — keyword=%r location=%r pages=%s",
        args.keyword, args.location, args.pages,
    )

    scraper = LinkedInJobScraper(headless=args.headless, delay=args.delay, verbose=args.verbose)
    jobs = scraper.search(keyword=args.keyword, location=args.location, max_pages=args.pages)

    if not jobs:
        logger.warning("No jobs found.")
        return

    # Write JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    keyword_slug = args.keyword.replace(" ", "_").replace("/", "_")
    out_path = args.output or f"linkedin_jobs_{keyword_slug}_{timestamp}.json"

    Path(out_path).write_text(
        json.dumps([asdict(j) for j in jobs], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Print summary
    print()
    print("─" * 60)
    print(f"  {len(jobs)} jobs found for '{args.keyword}'")
    print(f"  Output: {out_path}")
    print("─" * 60)
    for j in jobs[:10]:
        print(f"  • {j.title} @ {j.company} — {j.location}")
    if len(jobs) > 10:
        print(f"  … and {len(jobs) - 10} more")

    # Print markdown table for top 25
    if jobs:
        print()
        print("### Top Jobs")
        print()
        print("| # | Title | Company | Location | Posted |")
        print("|---|-------|---------|----------|--------|")
        for i, j in enumerate(jobs[:25], 1):
            title_link = f"[{j.title}]({j.url})" if j.url else j.title
            print(f"| {i} | {title_link} | {j.company} | {j.location} | {j.posted_date} |")


if __name__ == "__main__":
    main()