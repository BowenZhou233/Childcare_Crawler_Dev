#!/usr/bin/env python3
"""
Step 2: Crawl ALL childcare listing pages (active + sold)
Collect every detail-page URL and save to:
  data/listing_urls.json

Stats:
  Active: /child-care-for-sale          → ~133 listings, 25/page
  Sold:   /child-care-for-sale?status=sold → ~296 listings, 25/page
"""

import asyncio
import os
import json
import re
import math
import time
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from bs4 import BeautifulSoup

os.makedirs("data", exist_ok=True)

BASE = "https://www.anybusiness.com.au"
ACTIVE_BASE = f"{BASE}/child-care-for-sale"
SOLD_BASE   = f"{BASE}/child-care-for-sale?status=sold"

BROWSER_CFG = BrowserConfig(
    headless=True,
    viewport_width=1920,
    viewport_height=1080,
    user_agent=(
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
)

CRAWLER_CFG = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    page_timeout=60000,
    delay_before_return_html=2.5,
    remove_overlay_elements=True,
)

DELAY_BETWEEN_PAGES = 2.0  # seconds, be polite


def extract_listing_urls(html: str) -> list[dict]:
    """Extract unique listing URLs and basic info from a listing page."""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    listings = []

    cards = soup.select(".uk-card.uk-card-default")
    for card in cards:
        link_el = card.select_one('a[href^="/listings/"]')
        if not link_el:
            continue
        href = link_el.get("href", "")
        if href in seen:
            continue
        seen.add(href)

        title_el = card.select_one(".srp-h2")
        title = title_el.get_text(strip=True) if title_el else ""

        price_el = card.select_one('div[style*="#E9FBF0"]')
        price = price_el.get_text(strip=True) if price_el else ""

        loc_el = card.select_one(".location-wrapper > b")
        location = loc_el.get_text(strip=True) if loc_el else ""

        listings.append({
            "url": BASE + href,
            "title": title,
            "price": price,
            "location": location,
        })

    return listings


def get_total_pages(html: str, per_page: int = 25) -> int:
    """
    Parse total results count from '1 - 25 of 133 results' text,
    then compute ceil(total / per_page).
    Falls back to pagination link max if count not found.
    """
    import math
    soup = BeautifulSoup(html, "html.parser")

    # Try to parse "X of Y results"
    for el in soup.find_all(string=True):
        text = el.strip()
        m = re.search(r"of\s+([\d,]+)\s+result", text, re.IGNORECASE)
        if m:
            total = int(m.group(1).replace(",", ""))
            return math.ceil(total / per_page)

    # Fallback: max page number in pagination links
    pag_links = soup.select(".uk-pagination a")
    max_page = 1
    for a in pag_links:
        text = a.get_text(strip=True)
        if text.isdigit():
            max_page = max(max_page, int(text))
    return max_page


def build_page_url(base_url: str, page: int) -> str:
    """Build page URL. Page 1 has no page param."""
    if page == 1:
        return base_url
    if "?" in base_url:
        return f"{base_url}&page={page}"
    return f"{base_url}?page={page}"


async def crawl_all_pages(crawler, base_url: str, source_type: str) -> list[dict]:
    """Crawl all pages of a listing section and collect URLs."""
    all_listings = []

    # First page to determine total pages
    url_p1 = build_page_url(base_url, 1)
    print(f"\n📄 [{source_type}] Page 1: {url_p1}")
    result = await crawler.arun(url=url_p1, config=CRAWLER_CFG)

    if not result.success:
        print(f"  ❌ Failed: {result.error_message}")
        return all_listings

    total_pages = get_total_pages(result.html)
    listings_p1 = extract_listing_urls(result.html)

    # Count result total from page
    soup = BeautifulSoup(result.html, "html.parser")
    count_text = next(
        (t.strip() for t in soup.find_all(text=lambda t: t and "result" in t.lower() and len(t.strip()) < 60)
        if t.strip()), "?"
    )
    print(f"  ✅ Found {len(listings_p1)} listings | Total: {count_text} | Pages: {total_pages}")

    for lst in listings_p1:
        lst["source_type"] = source_type
    all_listings.extend(listings_p1)

    # Remaining pages
    for page in range(2, total_pages + 1):
        await asyncio.sleep(DELAY_BETWEEN_PAGES)
        url = build_page_url(base_url, page)
        print(f"📄 [{source_type}] Page {page}/{total_pages}: {url}")
        r = await crawler.arun(url=url, config=CRAWLER_CFG)
        if r.success:
            listings = extract_listing_urls(r.html)
            for lst in listings:
                lst["source_type"] = source_type
            all_listings.extend(listings)
            print(f"  ✅ +{len(listings)} listings (total so far: {len(all_listings)})")
        else:
            print(f"  ❌ Page {page} failed: {r.error_message}")

    return all_listings


async def main():
    print("=" * 65)
    print("  Anybusiness Childcare — Collect ALL Listing URLs")
    print("=" * 65)

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:
        # Active listings
        active_listings = await crawl_all_pages(crawler, ACTIVE_BASE, "active")
        await asyncio.sleep(DELAY_BETWEEN_PAGES)

        # Sold listings
        sold_listings = await crawl_all_pages(crawler, SOLD_BASE, "sold")

    # Merge & deduplicate by URL
    all_listings = active_listings + sold_listings
    unique = {lst["url"]: lst for lst in all_listings}
    result = list(unique.values())

    # Save
    output_path = "data/listing_urls.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 65)
    print(f"  DONE: {len(result)} unique listings saved → {output_path}")
    print(f"  Active: {len(active_listings)}  |  Sold: {len(sold_listings)}")
    print(f"  Duplicates removed: {len(all_listings) - len(result)}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
