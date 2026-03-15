#!/usr/bin/env python3
"""
Step 1: Fetch raw HTML from Anybusiness.com.au
Targets:
  - Listing page: childcare businesses for sale / sold
  - Detail page: one sample listing

Output files:
  - html_output/listing_page.html   — search results page
  - html_output/listing_page2.html  — page 2 (pagination check)
  - html_output/detail_page.html    — first individual listing
  - html_output/sold_page.html      — sold listings (if separate URL)
"""

import asyncio
import os
import json
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

OUTPUT_DIR = "html_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Target URLs ──────────────────────────────────────────────────────────────
# Anybusiness.com.au search for childcare businesses
BASE_LISTING_URL = "https://www.anybusiness.com.au/businesses-for-sale?q=childcare&state=all"
LISTING_PAGE_2   = "https://www.anybusiness.com.au/businesses-for-sale?q=childcare&state=all&page=2"
SOLD_URL         = "https://www.anybusiness.com.au/businesses-for-sale?q=childcare&state=all&status=sold"

# ── Browser config (anti-detection) ──────────────────────────────────────────
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

# ── Crawler config ────────────────────────────────────────────────────────────
CRAWLER_CFG = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,
    page_timeout=60000,
    wait_for="css:body",                 # ensure body is loaded
    delay_before_return_html=3.0,        # wait for JS-rendered content
    remove_overlay_elements=True,
    screenshot=True,
)


async def fetch_and_save(crawler, url: str, name: str):
    """Crawl a URL and save HTML + screenshot."""
    print(f"\n🌐 Fetching: {url}")
    result = await crawler.arun(url=url, config=CRAWLER_CFG)

    if result.success:
        # Save raw HTML
        html_path = os.path.join(OUTPUT_DIR, f"{name}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(result.html)
        print(f"   ✅ HTML saved → {html_path}  ({len(result.html):,} bytes)")

        # Save markdown (easier to read for analysis)
        md_path = os.path.join(OUTPUT_DIR, f"{name}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(str(result.markdown))
        print(f"   📄 Markdown  → {md_path}")

        # Save screenshot
        if result.screenshot:
            import base64
            png_path = os.path.join(OUTPUT_DIR, f"{name}.png")
            with open(png_path, "wb") as f:
                f.write(base64.b64decode(result.screenshot))
            print(f"   📸 Screenshot→ {png_path}")

        # Save links (for finding detail page URLs)
        links_path = os.path.join(OUTPUT_DIR, f"{name}_links.json")
        with open(links_path, "w", encoding="utf-8") as f:
            json.dump(result.links, f, indent=2, ensure_ascii=False)
        print(f"   🔗 Links     → {links_path}  "
              f"({len(result.links.get('internal', []))} internal)")

        return result
    else:
        print(f"   ❌ Failed: {result.error_message}")
        return None


async def main():
    print("=" * 60)
    print("  Anybusiness.com.au — HTML Source Fetcher")
    print("=" * 60)

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:

        # 1. Listing page (active for sale)
        result_p1 = await fetch_and_save(crawler, BASE_LISTING_URL, "listing_page1")

        # 2. Listing page 2 (pagination)
        await fetch_and_save(crawler, LISTING_PAGE_2, "listing_page2")

        # 3. Sold listings page
        await fetch_and_save(crawler, SOLD_URL, "sold_page")

        # 4. Auto-detect first detail page from listing links
        if result_p1 and result_p1.links:
            internal_links = result_p1.links.get("internal", [])
            # Look for URLs that look like individual business listings
            # e.g. /buy-a-business/childcare-XXXXX or /listing/XXXXX
            detail_urls = [
                lnk["href"] for lnk in internal_links
                if lnk.get("href") and (
                    "/buy-a-business/" in lnk["href"] or
                    "/listing/" in lnk["href"] or
                    "/business-for-sale/" in lnk["href"]
                )
            ]
            if detail_urls:
                first_detail = detail_urls[0]
                if not first_detail.startswith("http"):
                    first_detail = "https://www.anybusiness.com.au" + first_detail
                print(f"\n🔍 Found detail page candidate: {first_detail}")
                await fetch_and_save(crawler, first_detail, "detail_page")
            else:
                print("\n⚠️  Could not auto-detect detail page URL.")
                print("    Check listing_page1_links.json to find listing URLs manually.")

    print("\n" + "=" * 60)
    print("  Done! Check html_output/ for results.")
    print("  Next: inspect the HTML to map CSS selectors.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
