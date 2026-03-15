#!/usr/bin/env python3
"""
Step 2: Crawl ALL childcare centre listing pages from BusinessForSale.com.au
Collect every detail-page URL and save to:
  data/listing_urls.json

Search strategy:
  - Use category URL: /for-sale/education/childcare-centre/
  - Pagination via ?page=N
  - Total count from "Showing X to Y of Z businesses"
  - Filter out Franchise and WANTED listings
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

BASE = "https://www.businessforsale.com.au"

# Category URL for childcare centre listings
CATEGORY_URL = f"{BASE}/for-sale/education/childcare-centre/"

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
    delay_before_return_html=5.0,
    remove_overlay_elements=True,
)

DELAY_BETWEEN_PAGES = 2.5  # seconds, be polite


def extract_listing_urls(html: str) -> list[dict]:
    """
    Extract listing URLs and basic info from a search results page.
    Filters out Franchise and WANTED listings.

    Confirmed CSS structure (from 01_fetch_html.py analysis):
      Card:     div.result.listing  (has data-listing-id, data-position)
      Title:    div.title > a[href*="/australia/"]
      Location: span.location
      Price:    span.price[itemprop="price"]
      Category: div.category
      Badge:    span.tag (.featured, .exclusive, .new)
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    listings = []
    skipped_franchise = 0
    skipped_wanted = 0

    cards = soup.select("div.result.listing")
    for card in cards:
        # Title & URL
        title_el = card.select_one("div.title a")
        if not title_el or not title_el.get("href"):
            continue

        href = title_el["href"]
        if "/australia/" not in href:
            continue

        # Normalise URL
        if href.startswith("/"):
            full_url = BASE + href
        elif href.startswith("http"):
            full_url = href
        else:
            continue

        if full_url in seen:
            continue
        seen.add(full_url)

        title = title_el.get_text(strip=True)

        # Price
        price_el = card.select_one('span.price[itemprop="price"]') or card.select_one("span.price")
        price = price_el.get_text(strip=True) if price_el else ""

        # Location
        loc_el = card.select_one("span.location")
        location = loc_el.get_text(strip=True) if loc_el else ""

        # Category
        cat_el = card.select_one("div.category")
        category = cat_el.get_text(strip=True) if cat_el else ""

        # Listing ID from data attribute
        listing_id = card.get("data-listing-id", "")

        # Badges (FEATURED, EXCLUSIVE, NEW)
        badges = [tag.get_text(strip=True) for tag in card.select("span.tag")]

        # --- Filter: skip Franchise listings ---
        card_text = card.get_text(" ", strip=True).lower()
        if "franchise" in category.lower() or "franchise" in card_text:
            skipped_franchise += 1
            continue

        # --- Filter: skip WANTED (buyer-seeking) listings ---
        if title.upper().startswith("WANTED") or price.lower() == "wanted":
            skipped_wanted += 1
            continue

        listings.append({
            "url": full_url,
            "title": title,
            "price": price,
            "location": location,
            "category": category,
            "listing_id": listing_id,
            "badges": badges,
        })

    if skipped_franchise:
        print(f"  ⏭ Skipped {skipped_franchise} Franchise listing(s)")
    if skipped_wanted:
        print(f"  ⏭ Skipped {skipped_wanted} WANTED listing(s)")

    return listings


def get_total_results(html: str) -> int:
    """
    Parse total results count from 'Showing X to Y of Z businesses' text.
    Returns total count Z, or 0 if not found.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # "Showing 1 to 20 of 85 businesses"
    m = re.search(r"Showing\s+\d+\s+to\s+\d+\s+of\s+(\d+)\s+business", text, re.IGNORECASE)
    if m:
        return int(m.group(1))

    # Fallback: "X results"
    m = re.search(r"(\d+)\s+results?", text, re.IGNORECASE)
    if m:
        return int(m.group(1))

    return 0


def get_per_page(html: str) -> int:
    """Detect results per page from 'Showing 1 to N' text."""
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    m = re.search(r"Showing\s+1\s+to\s+(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 20  # default assumption


def build_category_url(page: int = 1) -> str:
    """Build category URL with optional page number."""
    url = CATEGORY_URL
    if page > 1:
        url += f"?page={page}"
    return url


async def crawl_category(crawler) -> list[dict]:
    """Crawl all pages of the childcare-centre category."""
    all_listings = []

    # First page
    url_p1 = build_category_url(1)
    print(f"\n📄 Page 1: {url_p1}")
    result = await crawler.arun(url=url_p1, config=CRAWLER_CFG)

    if not result.success:
        print(f"  ❌ Failed: {result.error_message}")
        return all_listings

    total = get_total_results(result.html)
    per_page = get_per_page(result.html)
    total_pages = math.ceil(total / per_page) if total > 0 and per_page > 0 else 1

    listings_p1 = extract_listing_urls(result.html)
    print(f"  ✅ Found {len(listings_p1)} listings | Total: {total} | "
          f"Per page: {per_page} | Pages: {total_pages}")

    all_listings.extend(listings_p1)

    # Remaining pages
    for page in range(2, total_pages + 1):
        await asyncio.sleep(DELAY_BETWEEN_PAGES)
        url = build_category_url(page)
        print(f"📄 Page {page}/{total_pages}: {url}")
        r = await crawler.arun(url=url, config=CRAWLER_CFG)
        if r.success:
            listings = extract_listing_urls(r.html)
            all_listings.extend(listings)
            print(f"  ✅ +{len(listings)} listings (total so far: {len(all_listings)})")
        else:
            print(f"  ❌ Page {page} failed: {r.error_message}")

    return all_listings


async def main():
    print("=" * 65)
    print("  BusinessForSale.com.au — Collect Childcare Centre Listing URLs")
    print(f"  Category: {CATEGORY_URL}")
    print("=" * 65)

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:
        all_listings = await crawl_category(crawler)

    # Deduplicate by URL
    unique = {}
    for lst in all_listings:
        if lst["url"] not in unique:
            unique[lst["url"]] = lst
    result = list(unique.values())

    # Save
    output_path = "data/listing_urls.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 65)
    print(f"  DONE: {len(result)} unique listings saved → {output_path}")
    print(f"  Total found (before dedup): {len(all_listings)}")
    print(f"  Duplicates removed: {len(all_listings) - len(result)}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
