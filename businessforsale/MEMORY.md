# BusinessForSale.com.au Childcare Centre Scraper — Dev Log

## Environment
- Python: `/Users/zbowen/anaconda3/bin/python` (3.11.4)
- crawl4ai: 0.8.0
- Working dir: `/Users/zbowen/Crawler_dev/businessforsale/`

## Site Info
- **Category URL**: `https://www.businessforsale.com.au/for-sale/education/childcare-centre/`
- **Detail page URL**: `/australia/{ID}/{slug}`
- **Pagination**: `?page=N`
- **Per page**: 18 listings
- **Total (childcare-centre category)**: ~31 listings, 25 after filtering Franchise + WANTED
- **JS-rendered**: Yes — requires headless browser

## Confirmed CSS Selectors (Listing Page)
- Card container: `div.result.listing` (has `data-listing-id`, `data-position`)
- Title link: `div.title > a` (href contains `/australia/`)
- Location: `span.location` (e.g. "Perth WA")
- Price: `span.price[itemprop="price"]` (e.g. "$15,000 WIWO, EOI")
- Description: `div.description[itemprop="description"]`
- Category: `div.category` (e.g. "Education")
- Badges: `span.tag` with classes `.featured`, `.exclusive`, `.new`
- Results count: text "Showing 1 to 18 of 31 businesses"
- Pagination: `li > a[href*="page="]`

## Confirmed CSS Selectors (Detail Page)
- Title: `h1`
- Price: `strong.price` (inside `div.price`, prefixed by "Asking Price")
- Revenue: text label "Revenue $X" or "Revenue Ask the Seller"
- Profit: text label "Profit $X" or "Profit Ask the Seller"
- Client No: `div.client-info` → regex `Client No: (\S+)`
- Last Updated: `span.updated-text` → "Last Updated DD Mon YYYY" (e.g. "21 Feb 2026")
- Categories: `span.category` (multiple, e.g. Education, Childcare Centre)
- Location: `ul.breadcrumb` → links to `/for-sale/{state}/`, `/for-sale/{city}-{state}-{postcode}/`
- Description: full "About" section text (no specific class, use page text)

## Price Formats
- Dollar amount: "$1,490,000", "$15,000 WIWO, EOI", "$240,000 + SAV"
- With GST: "$1,190,000 + GST (if any)"
- Contact: "Contact Seller for Price"
- EOI: "Expressions of interest"
- Refer: "Refer to Broker"

## Listing Filters
- **Franchise**: Skipped — detected by `span.tag` text or title containing "Franchise"
- **WANTED**: Skipped — detected by price text "Wanted" or title containing "WANTED"
- **Category approach**: Uses `/for-sale/education/childcare-centre/` category instead of keyword search to ensure relevance

## Field Extraction Notes
- **Place**: Number of licensed places, extracted from description via regex `(\d+)\+?\s+(?:approved\s+)?places?`
- **Current Occupancy**: Percentage only (e.g. "61%"), NOT confused with places count
- **Location**: State from breadcrumb text labels; Suburb from breadcrumb URL patterns like `/for-sale/perth-wa-6000/`
- **Revenue/Profit**: First checks page-level labels, then falls back to description regex

## Scripts
- `01_fetch_html.py` — fetch raw HTML for analysis (completed, selectors verified)
- `02_crawl_all_listings.py` — collect listing URLs from childcare-centre category (Franchise + WANTED filtered)
- `03_extract_details.py` — extract 63 fields from detail pages (breadcrumb selector fixed to `ul.breadcrumb`)
- `04_export.py` — export JSON → CSV + Excel (blue header, alternating rows)
- `run_all.py` — one-click runner for steps 2→3→4

## Bug Fixes
- **Breadcrumb selector**: `[itemtype*="BreadcrumbList"]` → `ul.breadcrumb` (the site doesn't use schema.org markup for breadcrumbs)
- **Occupancy vs Places**: Separated extraction — occupancy is percentage only, places is count only
- **Keyword → Category**: Changed from multi-keyword search to `/for-sale/education/childcare-centre/` category for better relevance

## Data Quality (2026-03-15, 25 listings)
- State: 100%, Price: 100%, Suburb: 92%
- Leasehold/Freehold: 80%, Place: 60%
- Revenue: 16%, Occupancy: 16%, NQS: 12%, Daily Fee: 8%
