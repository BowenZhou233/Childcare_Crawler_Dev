#!/usr/bin/env python3
"""
Step 2: Collect ALL listing URLs from perituschildcare.com.au
Uses the WordPress REST API to reliably fetch all listings.

Categories:
  - 68: Current Listing
  - 72: Under Contract
  - 73: Sold Listings

Output: data/listing_urls.json
"""

import json
import os
import time
import requests

os.makedirs("data", exist_ok=True)

BASE = "https://perituschildcare.com.au"
API_URL = f"{BASE}/wp-json/wp/v2/posts"

# Category IDs
CATEGORIES = {
    68: "current",
    72: "under-contract",
    73: "sold",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

DELAY_BETWEEN_REQUESTS = 1.0


def fetch_posts_by_category(cat_id: int, source_type: str) -> list[dict]:
    """Fetch all posts in a category via WP REST API with pagination."""
    all_posts = []
    page = 1

    while True:
        params = {
            "categories": cat_id,
            "per_page": 100,
            "page": page,
            "_fields": "id,title,slug,link,date,modified,categories,content",
        }
        print(f"  API request: category={cat_id} ({source_type}), page={page}")
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)

        if resp.status_code == 400:
            # No more pages
            break
        resp.raise_for_status()

        posts = resp.json()
        if not posts:
            break

        for post in posts:
            title = post["title"]["rendered"]
            all_posts.append({
                "id": post["id"],
                "url": post["link"],
                "title": title,
                "slug": post["slug"],
                "date": post["date"],
                "modified": post.get("modified", ""),
                "source_type": source_type,
                "categories": post.get("categories", []),
            })

        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        total_posts = int(resp.headers.get("X-WP-Total", len(posts)))
        print(f"    Got {len(posts)} posts (total: {total_posts}, pages: {total_pages})")

        if page >= total_pages:
            break
        page += 1
        time.sleep(DELAY_BETWEEN_REQUESTS)

    return all_posts


def main():
    print("=" * 65)
    print("  PeritusChildcare.com.au - Collect Listing URLs")
    print("=" * 65)

    all_listings = []

    for cat_id, source_type in CATEGORIES.items():
        print(f"\n--- {source_type.upper()} (category {cat_id}) ---")
        posts = fetch_posts_by_category(cat_id, source_type)
        all_listings.extend(posts)
        time.sleep(DELAY_BETWEEN_REQUESTS)

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

    current_count = sum(1 for r in result if r["source_type"] == "current")
    under_count   = sum(1 for r in result if r["source_type"] == "under-contract")
    sold_count    = sum(1 for r in result if r["source_type"] == "sold")

    print("\n" + "=" * 65)
    print(f"  DONE: {len(result)} unique listings saved -> {output_path}")
    print(f"    Current:        {current_count}")
    print(f"    Under Contract: {under_count}")
    print(f"    Sold:           {sold_count}")
    print(f"    Total found (before dedup): {len(all_listings)}")
    print(f"    Duplicates removed: {len(all_listings) - len(result)}")
    print("=" * 65)


if __name__ == "__main__":
    main()
