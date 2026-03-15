#!/usr/bin/env python3
"""
Step 1: Fetch raw HTML from lilleyccs.com for analysis.
Targets:
  - Properties (for-sale) page: https://www.lilleyccs.com/properties/
  - Sold page: https://www.lilleyccs.com/sold

Output files:
  - html_output/properties_page.html / .md / .png / _links.json
  - html_output/sold_page.html / .md / .png / _links.json
"""

import asyncio
import os
import json
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

OUTPUT_DIR = "html_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
    print("  LilleyCCS.com - HTML Source Fetcher")
    print("=" * 60)

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:

        # 1. Properties (for-sale) page
        await fetch_and_save(crawler, PROPERTIES_URL, "properties_page")

        # 2. Sold page (default year view)
        await fetch_and_save(crawler, SOLD_URL, "sold_page")

    print("\n" + "=" * 60)
    print("  Done! Check html_output/ for results.")
    print("  Next steps:")
    print("    1. Review properties_page.html for listing card structure")
    print("    2. Review sold_page.html for sold listing structure")
    print("    3. Check screenshots for visual verification")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
