#!/usr/bin/env python3
"""
Step 2: Crawl ALL listing pages from sydneychildcaresales.com.au
Collect every detail-page URL from both galleries:
  - For-sale: /for-sale-gallery/
  - Sold:     /sold-gallery/

Output: data/listing_urls.json

Pagination: /page/N/ suffix (WordPress default)
"""

import asyncio
import os
import json
import re
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from bs4 import BeautifulSoup

os.makedirs("data", exist_ok=True)

BASE = "https://www.sydneychildcaresales.com.au"
FORSALE_GALLERY = f"{BASE}/for-sale-gallery/"
SOLD_GALLERY    = f"{BASE}/sold-gallery/"

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
    delay_before_return_html=10.0,
    remove_overlay_elements=False,
    js_code="""
    // Wait for masonry grid items to be rendered by JS
    await new Promise(r => setTimeout(r, 5000));
    """,
)

DELAY_BETWEEN_PAGES = 2.5


def extract_listing_urls(html: str) -> list[dict]:
    """
    Extract portfolio listing URLs and titles from a gallery page.

    Site structure (WordPress + Elementor):
      - Each listing is an <a> containing <img> + <h3>
      - URLs: /portfolio/{slug}/
      - Status hint: image filename contains 'sold-', 'under-offer-', 'under-contract-', etc.
    """
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    listings = []

    # Actual structure (JS-rendered):
    #   div.masonry-item.project
    #     div.project__container.post-XXXX.portfolio
    #       div.project__img-holder > a[href="/portfolio/..."] > img
    #       div.project__description > h3.project__title > a[href] (title text)
    # Find portfolio items via masonry grid or fallback to links
    items = soup.select(".masonry-item.project")
    if items:
        for item in items:
            link = item.select_one("a[href*='/portfolio/']")
            if not link:
                continue
            href = link["href"]

            if href.startswith("/"):
                full_url = BASE + href
            elif href.startswith("http"):
                full_url = href
            else:
                continue
            full_url = full_url.rstrip("/") + "/"
            if full_url in seen:
                continue
            seen.add(full_url)

            # Title from .project__title or h3
            title_el = item.select_one(".project__title") or item.select_one("h3")
            title = title_el.get_text(strip=True) if title_el else ""

            # Status from image filename
            img = item.select_one("img.project__img") or item.select_one("img")
            img_src = img.get("src", "") if img else ""
            img_name = img_src.split("/")[-1].lower() if img_src else ""

            status_hint = "Active"
            if "sold" in img_name:
                status_hint = "Sold"
            elif "under-offer" in img_name:
                status_hint = "Under Offer"
            elif "under-contract" in img_name:
                status_hint = "Under Contract"

            # Also check categories from container classes
            container = item.select_one(".project__container")
            if container:
                cls = " ".join(container.get("class", []))
                if "offer-contract" in cls:
                    status_hint = "Under Offer"

            slug = href.rstrip("/").split("/")[-1]
            listings.append({
                "url": full_url,
                "title": title,
                "slug": slug,
                "status_hint": status_hint,
                "img_src": img_src,
            })
    else:
        # Fallback: find all links to /portfolio/ pages
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "/portfolio/" not in href:
                continue
            if href.startswith("/"):
                full_url = BASE + href
            elif href.startswith("http"):
                full_url = href
            else:
                continue
            full_url = full_url.rstrip("/") + "/"
            if full_url in seen:
                continue
            seen.add(full_url)

            h3 = link.find("h3")
            title = h3.get_text(strip=True) if h3 else ""
            img = link.find("img")
            img_src = img.get("src", "") if img else ""
            img_name = img_src.split("/")[-1].lower() if img_src else ""

            status_hint = "Active"
            if "sold" in img_name:
                status_hint = "Sold"
            elif "under-offer" in img_name:
                status_hint = "Under Offer"
            elif "under-contract" in img_name:
                status_hint = "Under Contract"

            slug = href.rstrip("/").split("/")[-1]
            listings.append({
                "url": full_url,
                "title": title,
                "slug": slug,
                "status_hint": status_hint,
                "img_src": img_src,
            })

    return listings


def get_max_page(html: str) -> int:
    """
    Detect maximum page number from pagination links.
    WordPress pagination uses .page-numbers class and /page/N/ links.
    """
    soup = BeautifulSoup(html, "html.parser")

    max_page = 1

    # Check .page-numbers elements (both links and spans)
    for el in soup.select(".page-numbers"):
        text = el.get_text(strip=True)
        if text.isdigit():
            page_num = int(text)
            if page_num > max_page:
                max_page = page_num

    # Also check href patterns
    for link in soup.find_all("a", href=True):
        m = re.search(r"/page/(\d+)/?", link["href"])
        if m:
            page_num = int(m.group(1))
            if page_num > max_page:
                max_page = page_num

    return max_page


def build_page_url(gallery_url: str, page: int) -> str:
    """Build gallery page URL with WordPress pagination."""
    if page <= 1:
        return gallery_url
    # WordPress: /for-sale-gallery/page/2/
    return gallery_url.rstrip("/") + f"/page/{page}/"


async def crawl_gallery(crawler, gallery_url: str, source_type: str) -> list[dict]:
    """Crawl all pages of a gallery and collect listing URLs."""
    all_listings = []

    # First page
    url_p1 = build_page_url(gallery_url, 1)
    print(f"\n  Page 1: {url_p1}")
    result = await crawler.arun(url=url_p1, config=CRAWLER_CFG)

    if not result.success:
        print(f"  FAILED: {result.error_message}")
        return all_listings

    total_pages = get_max_page(result.html)
    listings_p1 = extract_listing_urls(result.html)

    # Tag source type
    for lst in listings_p1:
        lst["source_type"] = source_type

    print(f"  Found {len(listings_p1)} listings | Pages: {total_pages}")
    all_listings.extend(listings_p1)

    # Remaining pages
    for page in range(2, total_pages + 1):
        await asyncio.sleep(DELAY_BETWEEN_PAGES)
        url = build_page_url(gallery_url, page)
        print(f"  Page {page}/{total_pages}: {url}")
        r = await crawler.arun(url=url, config=CRAWLER_CFG)
        if r.success:
            # Check if this page reveals more pages
            new_max = get_max_page(r.html)
            if new_max > total_pages:
                total_pages = new_max
                print(f"    Updated max pages to {total_pages}")

            listings = extract_listing_urls(r.html)
            for lst in listings:
                lst["source_type"] = source_type
            all_listings.extend(listings)
            print(f"    +{len(listings)} listings (total so far: {len(all_listings)})")
        else:
            print(f"    Page {page} failed: {r.error_message}")

    return all_listings


async def main():
    print("=" * 65)
    print("  SydneyChildcareSales.com.au - Collect Listing URLs")
    print("=" * 65)

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:
        # 1. For-sale gallery
        print("\n--- FOR SALE GALLERY ---")
        forsale = await crawl_gallery(crawler, FORSALE_GALLERY, "for-sale")

        await asyncio.sleep(DELAY_BETWEEN_PAGES)

        # 2. Sold gallery
        print("\n--- SOLD GALLERY ---")
        sold = await crawl_gallery(crawler, SOLD_GALLERY, "sold")

    all_listings = forsale + sold

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

    forsale_count = sum(1 for r in result if r["source_type"] == "for-sale")
    sold_count    = sum(1 for r in result if r["source_type"] == "sold")

    print("\n" + "=" * 65)
    print(f"  DONE: {len(result)} unique listings saved -> {output_path}")
    print(f"    For-sale: {forsale_count}")
    print(f"    Sold:     {sold_count}")
    print(f"    Total found (before dedup): {len(all_listings)}")
    print(f"    Duplicates removed: {len(all_listings) - len(result)}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
