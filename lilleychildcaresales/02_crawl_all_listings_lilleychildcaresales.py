#!/usr/bin/env python3
"""
Step 2: Crawl all listings from lilleyccs.com
  - Properties page: https://www.lilleyccs.com/properties/
    → Active (.listing.active), Under Offer (.listing.offer),
      Under Contract (.listing.contract)
    → EXCLUDES DA Site listings
  - Sold page: https://www.lilleyccs.com/sold
    → Only current financial year data is server-rendered
    → Year filter is client-side only (no other years available)

Uses crawl4ai for browser-based rendering.

HTML structure:
  Properties: .col.mix > .card.listing.[active|offer|contract]
    - .listing-number → CODE: XXXX (or "Under Offer" / "Under Contract")
    - .listing-info > .listing-location → location
    - .listing-info text → places, sale type, price (separated by <br>)
  Sold: .col.mix > .card.listing.sold
    - .listing-info > h5.listing-location → location
    - .listing-info text → places, sale type

Output: data/listing_urls_lilleychildcaresales.json
"""

import asyncio
import json
import os
import re
import sys
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dedup import DedupChecker
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

os.makedirs("data", exist_ok=True)

BASE = "https://www.lilleyccs.com"
PROPERTIES_URL = f"{BASE}/properties/"
SOLD_URL       = f"{BASE}/sold"

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
    wait_for="css:.filter-results-container",
    delay_before_return_html=5.0,
    remove_overlay_elements=True,
)


def parse_listing_info(info_div) -> dict:
    """Extract fields from a .listing-info div."""
    data = {}

    # Location: from <span> or <h5> with class listing-location
    loc_el = info_div.select_one(".listing-location")
    if loc_el:
        data["location"] = loc_el.get_text(strip=True)

    # Remaining text after location: split by <br> tags
    # Get all text segments separated by <br>
    parts = []
    for child in info_div.children:
        if child.name == "br":
            continue
        elif child.name == "span" or child.name == "h5":
            continue  # Already extracted as location
        elif hasattr(child, "get_text"):
            t = child.get_text(strip=True)
            if t:
                parts.append(t)
        elif isinstance(child, str):
            t = child.strip()
            if t:
                parts.append(t)

    # Parse parts for places, sale type, price
    raw_text = " | ".join(parts)
    data["raw_parts"] = parts

    # Places
    for part in parts:
        m = re.search(r"(\d+)\+?\s*[Pp]laces?", part)
        if m:
            data["places"] = m.group(1)
            break

    # Sale type
    full_text = " ".join(parts)
    if "Business and Freehold" in full_text or "Business & Freehold" in full_text:
        data["sale_type"] = "Business and Freehold"
    elif "Freehold Only" in full_text:
        data["sale_type"] = "Freehold Only"
    elif "Business Only" in full_text:
        data["sale_type"] = "Business Only"
    elif "DA Site" in full_text:
        data["sale_type"] = "DA Site"

    # Price — from parts (typically the last part for active listings)
    for part in parts:
        part_stripped = part.strip()
        # Skip known non-price patterns
        if re.match(r"^\d+\+?\s*[Pp]laces?", part_stripped):
            continue
        if part_stripped in ("Business Only", "Business and Freehold",
                             "Freehold Only", "DA Site",
                             "Under Offer", "UNDER OFFER",
                             "Under Contract", "UNDER Contract", "Unde Offer"):
            continue

        # Price patterns
        price_match = re.search(r"\$([\d,]+(?:\.\d+)?)", part_stripped)
        if price_match:
            data["price"] = "$" + price_match.group(1)
            break
        if re.search(r"^EOI", part_stripped, re.IGNORECASE):
            data["price"] = part_stripped
            break
        if re.search(r"^Offers$", part_stripped, re.IGNORECASE):
            data["price"] = "Offers"
            break
        if re.search(r"^Vendor will pay", part_stripped, re.IGNORECASE):
            data["price"] = part_stripped
            break

    return data


def parse_properties_page(html: str) -> list[dict]:
    """Parse the for-sale properties page using CSS selectors."""
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    # Status mapping from card CSS class
    STATUS_MAP = {
        "active": "Active",
        "offer": "Under Offer",
        "contract": "Under Contract",
        "sold": "Sold",
    }

    # Find all listing cards
    cards = soup.select(".col.mix")

    for col in cards:
        card = col.select_one(".card.listing")
        if not card:
            continue

        # Determine status from card CSS classes
        status = "Active"
        card_classes = card.get("class", [])
        for cls, status_name in STATUS_MAP.items():
            if cls in card_classes:
                status = status_name
                break

        # Get code from .listing-number
        code = ""
        code_div = col.select_one(".listing-number")
        if code_div:
            code_text = code_div.get_text(strip=True)
            m = re.search(r"CODE:\s*(\d+)", code_text)
            if m:
                code = m.group(1)

        # Get listing info
        info_div = col.select_one(".listing-info")
        if not info_div:
            continue

        data = parse_listing_info(info_div)

        # Skip DA Site listings
        if data.get("sale_type") == "DA Site":
            continue

        # Also check if listing text contains "DA Site" or "DA Turnkey"
        full_text = info_div.get_text(" ", strip=True)
        if "DA Site" in full_text or "DA Turnkey" in full_text:
            continue

        # Get data-publish timestamp
        publish_ts = col.get("data-publish", "")

        listing = {
            "code": code,
            "source": "for-sale",
            "status": status,
            "location": data.get("location", ""),
            "places": data.get("places", ""),
            "sale_type": data.get("sale_type", ""),
            "price": data.get("price", ""),
            "publish_timestamp": publish_ts,
            "raw_text": f"CODE: {code} | {data.get('location', '')} | "
                        + " | ".join(data.get("raw_parts", [])),
        }

        listings.append(listing)

    return listings


def parse_sold_page(html: str) -> list[dict]:
    """Parse the sold listings page using CSS selectors."""
    soup = BeautifulSoup(html, "html.parser")
    listings = []

    # Get financial year from heading
    h1 = soup.select_one("h1")
    financial_year = ""
    if h1:
        m = re.search(r"(\d{4})\s*[-–]\s*(\d{4})", h1.get_text())
        if m:
            financial_year = f"{m.group(1)}-{m.group(2)}"

    # Find all sold listing cards
    cards = soup.select(".col.mix")

    for col in cards:
        card = col.select_one(".card.listing.sold")
        if not card:
            continue

        info_div = col.select_one(".listing-info")
        if not info_div:
            continue

        data = parse_listing_info(info_div)

        # Skip DA Site
        if data.get("sale_type") == "DA Site":
            continue
        full_text = info_div.get_text(" ", strip=True)
        if "DA Site" in full_text or "DA Turnkey" in full_text:
            continue

        # Get data-publish date and financial year
        publish_date = col.get("data-publish", "")
        fy = col.get("data-financialyear", financial_year)

        listing = {
            "code": "",
            "source": "sold",
            "status": "Sold",
            "location": data.get("location", ""),
            "places": data.get("places", ""),
            "sale_type": data.get("sale_type", ""),
            "price": "",
            "financial_year": f"{fy}-{int(fy)+1}" if fy and fy.isdigit() else financial_year,
            "publish_date": publish_date,
            "raw_text": f"{data.get('location', '')} | "
                        + " | ".join(data.get("raw_parts", [])),
        }

        listings.append(listing)

    return listings


async def main():
    print("=" * 65)
    print("  LilleyCCS.com - Collect All Listings")
    print("=" * 65)

    all_listings = []

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:

        # 1. Properties page (for-sale, under offer, under contract)
        print("\n--- FOR-SALE PROPERTIES ---")
        result = await crawler.arun(url=PROPERTIES_URL, config=CRAWLER_CFG)
        if result.success:
            props = parse_properties_page(result.html)
            all_listings.extend(props)
            print(f"  Found {len(props)} listings on properties page")

            # Count by status
            for status in sorted(set(p["status"] for p in props)):
                count = sum(1 for p in props if p["status"] == status)
                print(f"    {status}: {count}")
        else:
            print(f"  FAILED: {result.error_message}")

        # 2. Sold page (current financial year only — server-side rendered)
        print("\n--- SOLD LISTINGS ---")
        result = await crawler.arun(url=SOLD_URL, config=CRAWLER_CFG)
        if result.success:
            sold = parse_sold_page(result.html)
            all_listings.extend(sold)
            print(f"  Found {len(sold)} sold listings")

            # Count by year
            years = {}
            for s in sold:
                yr = s.get("financial_year", "unknown")
                years[yr] = years.get(yr, 0) + 1
            for yr, cnt in sorted(years.items(), reverse=True):
                print(f"    {yr}: {cnt}")
        else:
            print(f"  FAILED: {result.error_message}")

    # Dedup against master database (lilley has no URLs — match by code)
    checker = DedupChecker()
    all_listings = checker.filter_listings(
        all_listings, source="lilleychildcaresales",
        code_key="code", log_dir="data"
    )

    # Save
    output_path = "data/listing_urls_lilleychildcaresales.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_listings, f, indent=2, ensure_ascii=False)

    active_count = sum(1 for r in all_listings if r.get("status") == "Active")
    offer_count  = sum(1 for r in all_listings if r.get("status") == "Under Offer")
    contract_count = sum(1 for r in all_listings if r.get("status") == "Under Contract")
    sold_count   = sum(1 for r in all_listings if r.get("status") == "Sold")

    print("\n" + "=" * 65)
    print(f"  DONE: {len(all_listings)} listings saved -> {output_path}")
    print(f"    Active:         {active_count}")
    print(f"    Under Offer:    {offer_count}")
    print(f"    Under Contract: {contract_count}")
    print(f"    Sold:           {sold_count}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
