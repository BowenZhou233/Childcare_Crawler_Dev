#!/usr/bin/env python3
"""
Step 1: Fetch raw HTML from perituschildcare.com.au
Targets:
  - Current listings page 1
  - Under contract listings page 1
  - Sold listings page 1
  - Detail page (auto-detected from links)

Output files:
  - html_output/current_page1.html
  - html_output/under_contract_page1.html
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

BASE = "https://perituschildcare.com.au"
CURRENT_URL       = f"{BASE}/current-listings/"
UNDER_CONTRACT_URL = f"{BASE}/under-contract-listings/"
SOLD_URL          = f"{BASE}/sold/"

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
    delay_before_return_html=3.0,
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
    print("  PeritusChildcare.com.au - HTML Source Fetcher")
    print("=" * 60)

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:

        # 1. Current listings
        result_current = await fetch_and_save(crawler, CURRENT_URL, "current_page1")

        # 2. Under contract listings
        result_under = await fetch_and_save(crawler, UNDER_CONTRACT_URL, "under_contract_page1")

        # 3. Sold listings
        result_sold = await fetch_and_save(crawler, SOLD_URL, "sold_page1")

        # 4. Auto-detect first detail page from links
        source = result_current or result_under or result_sold
        if source and source.links:
            internal_links = source.links.get("internal", [])
            # Detail pages are direct slugs under the domain
            # Exclude known non-detail paths
            EXCLUDE_PATHS = {
                "/current-listings/", "/under-contract-listings/", "/sold/",
                "/about/", "/contact/", "/privacy-policy/", "/terms/",
                "/", "/blog/", "/news/", "/team/", "/services/",
            }
            detail_urls = []
            seen = set()
            for lnk in internal_links:
                href = lnk.get("href", "")
                if not href:
                    continue
                # Normalize
                if href.startswith("/"):
                    full_url = BASE + href
                elif href.startswith(BASE):
                    full_url = href
                else:
                    continue

                path = full_url.replace(BASE, "")
                if not path.startswith("/"):
                    path = "/" + path

                # Skip known section pages, pages with /page/, wp-content, etc.
                if path in EXCLUDE_PATHS:
                    continue
                if "/page/" in path or "wp-" in path or "#" in path:
                    continue
                if path.count("/") > 2:
                    continue  # Too deep, likely not a listing

                if full_url not in seen:
                    seen.add(full_url)
                    detail_urls.append(full_url)

            if detail_urls:
                first_detail = detail_urls[0]
                print(f"\n  Found {len(detail_urls)} potential detail URLs. Fetching first:")
                print(f"   {first_detail}")
                await fetch_and_save(crawler, first_detail, "detail_page")

                details_path = os.path.join(OUTPUT_DIR, "detected_detail_urls.json")
                with open(details_path, "w", encoding="utf-8") as f:
                    json.dump(detail_urls, f, indent=2, ensure_ascii=False)
                print(f"\n   All {len(detail_urls)} detail URLs -> {details_path}")
            else:
                print("\n  Could not auto-detect detail page URL.")
                print("    Check current_page1_links.json for listing URLs.")

    print("\n" + "=" * 60)
    print("  Done! Check html_output/ for results.")
    print("  Next steps:")
    print("    1. Review current_page1.html for CSS selectors")
    print("    2. Review detail_page.html for field extraction")
    print("    3. Check screenshots for visual verification")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
