#!/usr/bin/env python3
"""
Step 1: Fetch raw HTML from sydneychildcaresales.com.au
Targets:
  - For-sale gallery page 1
  - Sold gallery page 1
  - Detail page (auto-detected from gallery links)

Output files:
  - html_output/forsale_page1.html
  - html_output/sold_page1.html
  - html_output/detail_page.html
  + corresponding .md, .png, _links.json
"""

import asyncio
import os
import json
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

OUTPUT_DIR = "html_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE = "https://www.sydneychildcaresales.com.au"
FORSALE_URL = f"{BASE}/for-sale-gallery/"
SOLD_URL    = f"{BASE}/sold-gallery/"

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
    wait_for="css:body",
    delay_before_return_html=5.0,
    remove_overlay_elements=True,
    screenshot=True,
)


async def fetch_and_save(crawler, url: str, name: str):
    """Crawl a URL and save HTML + markdown + screenshot + links."""
    print(f"\n  Fetching: {url}")
    result = await crawler.arun(url=url, config=CRAWLER_CFG)

    if result.success:
        html_path = os.path.join(OUTPUT_DIR, f"{name}.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(result.html)
        print(f"   HTML saved -> {html_path}  ({len(result.html):,} bytes)")

        md_path = os.path.join(OUTPUT_DIR, f"{name}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(str(result.markdown))
        print(f"   Markdown  -> {md_path}")

        if result.screenshot:
            import base64
            png_path = os.path.join(OUTPUT_DIR, f"{name}.png")
            with open(png_path, "wb") as f:
                f.write(base64.b64decode(result.screenshot))
            print(f"   Screenshot-> {png_path}")

        links_path = os.path.join(OUTPUT_DIR, f"{name}_links.json")
        with open(links_path, "w", encoding="utf-8") as f:
            json.dump(result.links, f, indent=2, ensure_ascii=False)
        print(f"   Links     -> {links_path}  "
              f"({len(result.links.get('internal', []))} internal)")

        return result
    else:
        print(f"   FAILED: {result.error_message}")
        return None


async def main():
    print("=" * 60)
    print("  SydneyChildcareSales.com.au - HTML Source Fetcher")
    print("=" * 60)

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:

        # 1. For-sale gallery
        result_forsale = await fetch_and_save(crawler, FORSALE_URL, "forsale_page1")

        # 2. Sold gallery
        result_sold = await fetch_and_save(crawler, SOLD_URL, "sold_page1")

        # 3. Auto-detect first detail page from gallery links
        source = result_forsale or result_sold
        if source and source.links:
            internal_links = source.links.get("internal", [])
            detail_urls = [
                lnk["href"] for lnk in internal_links
                if lnk.get("href") and "/portfolio/" in lnk["href"]
            ]
            seen = set()
            unique_details = []
            for u in detail_urls:
                if u not in seen:
                    seen.add(u)
                    unique_details.append(u)

            if unique_details:
                first_detail = unique_details[0]
                if not first_detail.startswith("http"):
                    first_detail = BASE + first_detail
                print(f"\n  Found {len(unique_details)} detail page URLs. Fetching first:")
                print(f"   {first_detail}")
                await fetch_and_save(crawler, first_detail, "detail_page")

                details_path = os.path.join(OUTPUT_DIR, "detected_detail_urls.json")
                with open(details_path, "w", encoding="utf-8") as f:
                    json.dump(unique_details, f, indent=2, ensure_ascii=False)
                print(f"\n   All {len(unique_details)} detail URLs -> {details_path}")
            else:
                print("\n  Could not auto-detect detail page URL.")
                print("    Check forsale_page1_links.json for listing URLs.")

    print("\n" + "=" * 60)
    print("  Done! Check html_output/ for results.")
    print("  Next steps:")
    print("    1. Review forsale_page1.html for CSS selectors")
    print("    2. Review detail_page.html for field extraction")
    print("    3. Check screenshots for visual verification")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
