# Crawler Dev Project Memory

## Environment
- Python: `/Users/zbowen/anaconda3/bin/python` (3.11.4)
- crawl4ai: 0.8.0 installed via pip
- Working dir: `/Users/zbowen/Crawler_dev/`
- crawl4ai reference docs: `/Users/zbowen/Crawler_dev/crawl4ai/reference/`

## Anybusiness.com.au Childcare Scraper
- Project dir: `/Users/zbowen/Crawler_dev/anybusiness/`
- **Site tech**: Ruby on Rails + UIKit CSS + React components (server-rendered)
- **Active listings URL**: `https://www.anybusiness.com.au/child-care-for-sale` (133 listings, 6 pages)
- **Sold listings URL**: `https://www.anybusiness.com.au/child-care-for-sale?status=sold` (296 listings, 12 pages)
- **Pagination**: `?page=N` (max shown = 3, real count from "X of Y results" text → ceil(Y/25))
- **Detail page URL**: `/listings/{suburb}-{state}-{postcode}-{categories}-{id}`
- **Sold filter**: NOT a URL param — requires clicking checkbox + "Search now" button → changes URL to `?status=sold`

## Key CSS Selectors
- Listing cards: `.uk-card.uk-card-default`
- Title: `.srp-h2`
- Price: `div[style*="#E9FBF0"]`
- Location: `.location-wrapper > b`
- Detail URL link: `a[href^="/listings/"]`
- Business No: `[itemprop="serialNumber"]`
- Price (detail): `[itemprop="price"]`
- Status (active): `.current` → text "Active"
- Status (under offer): `.under-contract` → text "Under Offer" (color #11853e)
- Status (sold): text "SOLD" appears in description (no special class)
- Date updated: "Updated on: DD/MM/YYYY" in `[itemtype*="schema.org/Offer"]`
- Description: `[itemprop="description"]`

## Data Extraction Notes
- Most childcare-specific fields are in free-text description (regex parsing)
- Many fields (EBITDA breakdown, Supply Ratio, GRP, 30-39 Females) rarely present
- Revenue pattern: use `_find_money_near()` helper (searches ±60 chars around keyword)
- `$2.3M+` format: the `+` was breaking old regex patterns
- Occupancy: use `\d+\+?\s+(?:approved\s+)?places` to handle "25+ places"

## Scripts
- `01_fetch_html.py` — fetch raw HTML for analysis
- `02_crawl_all_listings.py` — collect all listing URLs (active + sold)
- `03_extract_details.py` — extract data from each detail page (3 concurrent, resumes on restart)
- `04_export.py` — export JSON → CSV + Excel (openpyxl, blue header, alternating rows)
- `run_all.py` — one-click runner for steps 2→3→4

## Data Quality (429 listings)
- Active: 133, Sold: 296
- Has Price: 389/429
- Real childcare centres (with key fields): ~161
- Revenue fill: ~59/429 (most listings don't disclose)
- Note: Category includes Mathnasium tutoring franchises — filter by title/description if needed
