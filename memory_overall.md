# Crawler Dev — Project Memory Overview

> Last updated: 2026-03-15

---

## 1. Environment

- **Python**: `/Users/zbowen/anaconda3/bin/python` (3.11.4)
- **crawl4ai**: v0.8.0 (pip install)
- **Working directory**: `/Users/zbowen/Crawler_dev/`
- **crawl4ai reference docs**: `/Users/zbowen/Crawler_dev/crawl4ai/reference/`
- **Master database**: `0.final data leasehold & freehold.xlsx` (1280 records, 10 data sources)

---

## 2. Pipeline Architecture

Every scraper follows the same 4-step pipeline:

| Step | Script | Input | Output | Description |
|------|--------|-------|--------|-------------|
| 1 | `01_fetch_html.py` | Website URL | `html_output/*.json` | Fetch raw HTML for selector analysis (dev only) |
| 2 | `02_crawl_all_listings.py` | Site URL | `data/listing_urls.json` | Collect all detail-page URLs + **dedup filter** |
| 3 | `03_extract_details.py` | `listing_urls.json` | `data/childcare_raw.json` | Extract 63 fields per listing + **dedup filter** |
| 4 | `04_export.py` | `childcare_raw.json` | CSV + Excel | Format data for export |

- **Runner**: `python run_all.py` (steps 2→3→4) or `python run_all.py --step=N`
- **Concurrency**: 3 parallel crawls per batch, 1.5s delay between batches
- **Resume**: Step 3 tracks `done_urls` and skips already-processed listings on restart

---

## 3. Target Sites (5 Crawlers)

### 3.1 Anybusiness.com.au

- **Project dir**: `/Users/zbowen/Crawler_dev/anybusiness/`
- **Site tech**: Ruby on Rails + UIKit CSS + React components (server-rendered)
- **Active listings**: `https://www.anybusiness.com.au/child-care-for-sale` (133 listings, 6 pages)
- **Sold listings**: `https://www.anybusiness.com.au/child-care-for-sale?status=sold` (296 listings, 12 pages)
- **Pagination**: `?page=N` (25 items/page, real count from "X of Y results" text)
- **Detail page URL**: `/listings/{suburb}-{state}-{postcode}-{categories}-{id}`
- **Sold filter**: Requires clicking checkbox + "Search now" button (NOT a URL param)
- **Key CSS selectors**:
  - Listing cards: `.uk-card.uk-card-default`
  - Title: `.srp-h2`
  - Price: `div[style*="#E9FBF0"]`
  - Location: `.location-wrapper > b`
  - Detail URL link: `a[href^="/listings/"]`
  - Business No: `[itemprop="serialNumber"]`
  - Status (active): `.current` → "Active"
  - Status (under offer): `.under-contract` → "Under Offer"
  - Date updated: "Updated on: DD/MM/YYYY" in `[itemtype*="schema.org/Offer"]`
  - Description: `[itemprop="description"]`
- **Data extraction notes**:
  - Most fields are in free-text description (regex parsing)
  - Revenue pattern: `_find_money_near()` helper (±60 chars around keyword)
  - `$2.3M+` format: the `+` was breaking old regex patterns
  - Occupancy: `\d+\+?\s+(?:approved\s+)?places` to handle "25+ places"
- **Data quality (429 listings)**: Active 133, Sold 296; Price 90.7%; Revenue ~14%; includes Mathnasium tutoring franchises

### 3.2 BusinessForSale.com.au

- **Project dir**: `/Users/zbowen/Crawler_dev/businessforsale/`
- **Site tech**: JS-rendered category page
- **URL**: `/for-sale/education/childcare-centre/` with `?page=N` pagination (18 results/page)
- **Detail URL**: `/australia/{ID}/{slug}`
- **Results counter**: "Showing X to Y of Z businesses"
- **Key CSS selectors**:
  - Card: `div.result.listing`
  - Title: `div.title a[href*="/australia/"]`
  - Location: `span.location`
  - Price: `span.price[itemprop="price"]`
- **Filtering**: Franchise listings and WANTED buyer ads are skipped
- **Data quality (25 listings)**: 24 Active, 1 Sold; Place 60%; Revenue 16%

### 3.3 LilleyChildcareSales (lilleyccs.com)

- **Project dir**: `/Users/zbowen/Crawler_dev/lilleychildcaresales/`
- **Site tech**: Custom site (Isotope/Masonry JS)
- **Properties page**: `https://www.lilleyccs.com/properties/` (Active, Under Offer, Under Contract)
- **Sold page**: `https://www.lilleyccs.com/sold` (current financial year only)
- **HTML structure**:
  - Properties: `.col.mix > .card.listing.[active|offer|contract]`
  - `.listing-number` → CODE: XXXX
  - `.listing-info > .listing-location` → location
- **Special**: No individual detail pages — all data extracted in Step 2; Step 3 only transforms to standard columns
- **Excludes**: DA Site listings
- **Multiple statuses**: Active, Under Offer, Under Contract, Sold
- **Data quality (~98 listings)**: Variable; highest fill rate among smaller crawlers

### 3.4 PeritusChildcare.com.au

- **Project dir**: `/Users/zbowen/Crawler_dev/perituschildcare/`
- **Site tech**: WordPress + Uncode theme
- **Data source**: WP REST API (`/wp-json/wp/v2/posts`) — no browser needed for URL scraping
- **Categories**: 68 (Current), 72 (Under Contract), 73 (Sold)
- **Date filter**: `DATE_FROM="01/01/2025"`, `DATE_TO="12/03/2026"`
- **Filtered URLs**: 53 tracked in `data/date_filtered_urls.json`
- **Data quality (~86 listings)**: Good fill rates for Price, Place

### 3.5 SydneyChildcareSales.com.au

- **Project dir**: `/Users/zbowen/Crawler_dev/sydneychildcaresales/`
- **Site tech**: WordPress + Elementor page builder (Isotope/Masonry JS gallery)
- **For-sale gallery**: `https://www.sydneychildcaresales.com.au/for-sale-gallery/` (3 pages, ~8/page)
- **Sold gallery**: `https://www.sydneychildcaresales.com.au/sold-gallery/` (6 pages, ~7-8/page)
- **Pagination**: WordPress `/page/N/` suffix
- **Detail page URL**: `/portfolio/{slug}/`
- **Critical**: Gallery items are JS-rendered (empty in raw HTML); requires `js_code` with 5s extra wait + `delay_before_return_html=10s`
- **Gallery card selector**: `.masonry-item.project` → `a[href*="/portfolio/"]`
- **Status**: From image filename (`sold-*`, `under-offer-*`) — no CSS class indicators
- **Dates**: JSON-LD `datePublished` in schema.org WebPage markup
- **All data fields**: In Elementor free-text widgets (regex extraction, no structured markup)
- **Data quality (62 listings)**: 16 for-sale, 46 sold; 14 kept after date filter; Price 100%, Place 93%, Occupancy 50%, Revenue 29%

---

## 4. Deduplication Module (`dedup.py`)

### 4.1 Overview

A shared module at the project root that filters crawled listings against the master Excel database (`0.final data leasehold & freehold.xlsx`) to avoid re-crawling known records. Integrated into both Step 2 (after URL collection) and Step 3 (before detail extraction) of all 5 crawlers.

### 4.2 Dedup Strategies (in priority order)

| Priority | Strategy | Description |
|----------|----------|-------------|
| 1 | **URL match** | Normalised URL comparison (strips protocol, `www.`, trailing `/`) |
| 2 | **Title match** | Data Source + normalised title combo (strips punctuation, collapses whitespace) |
| 3 | **Code match** | Data Source + listing code (lilley-specific, uses `code XXXX` from titles) |

### 4.3 Key Design Decisions

- lilleychildcaresales has no unique URLs (all point to `/properties/`), so code-based matching via `code_key="code"` parameter
- Data Source naming differs between Excel (lowercase, e.g. `anybusiness`) and crawlers (e.g. `Anybusiness.com.au`) — `SOURCE_MAP` dict handles mapping
- Excel column 4 (second "item" column) holds URLs — not column 0
- Skip log saved to `data/dedup_skipped.json` per crawler with `_dedup_reason` and `_dedup_time`
- `DedupChecker` uses lazy loading (loads Excel only on first call)
- If Excel file missing, dedup silently disabled — crawlers run normally

### 4.4 Data Source Mapping

| Crawler | Excel value | Crawler value |
|---------|------------|---------------|
| anybusiness | `anybusiness` | `Anybusiness.com.au` |
| businessforsale | `businessforsale` | `BusinessForSale.com.au` |
| lilleychildcaresales | `lilleychildcaresales` | `LilleyCCS.com` |
| perituschildcare | `perituschildcare` | `PeritusChildcare.com.au` |
| sydneychildcaresales | `sydneychildcaresales` | `SydneyChildcareSales.com.au` |

### 4.5 Validation Results (2026-03-15)

| Crawler | Total | Kept | Skipped | Match Types |
|---------|-------|------|---------|-------------|
| anybusiness | 429 | 409 | 20 | URL: 20 |
| businessforsale | 25 | 18 | 7 | URL: 6, Title: 1 |
| lilleychildcaresales | 98 | 80 | 18 | Code: 18 |
| perituschildcare | 86 | 71 | 15 | URL: 15 |
| sydneychildcaresales | 62 | 57 | 5 | URL: 5 |
| **Total** | **700** | **635** | **65** | |

### 4.6 Files Modified

- `dedup.py` (new) — shared module at project root
- All 5 × `02_crawl_all_listings.py` — import + filter after URL dedup
- All 5 × `03_extract_details.py` — import + filter before crawling remaining URLs

---

## 5. Output Schema (63 Fields)

All scrapers produce the same standardised columns (all stored as strings):

| Category | Fields |
|----------|--------|
| **Metadata** (6) | Business No., Date of Listing, Data Source, Related Source Item, URL, Suburb |
| **Location** (4) | City, State, Location Direction, Leasehold or Freehold |
| **Status** (5) | Site, On Sale or Not, Sold Date, Price, Net Income |
| **Financial Ratios** (2) | Net Income / Price, Years to Recover Investment |
| **Capacity** (2) | Current Occupancy, Place |
| **Rent & Lease** (4) | Rent, Rent per Place, Length of Lease, Rent Increases (Annual) |
| **Property** (4) | Area (sqm), Near School, Near Supermarket, Renovation, Fitout |
| **Revenue Metrics** (3) | Rent % Revenue, EBITDA Condition 1, Yield, Estimated Annual Net Yield |
| **Daily Fees** (4) | Daily Fee (0-2), Daily Fee (2-3), Daily Fee (3-5), Current Daily Fees |
| **EBITDA Breakdown** (10) | EBITDA 1-4, Percentage 1-4, Revenue, Current EBITDA, Current Percentage |
| **Demographics** (9) | Supply Ratio, Development, # of Students Surrounding, Avg Household Income, Resident Population, 0-5 Resident Population, 30-39 Females, Population Growth Rate, GRP of Region |
| **Quality & Amenities** (6) | Waiting List, Additional Places to be Added, NQS Rating, Parking Volume, Vehicles Passing Daily, Government Funding, Land Tax Free |

---

## 6. Master Database Summary

- **File**: `0.final data leasehold & freehold.xlsx`
- **Sheet**: `0.final data leasehold & freeho` (single sheet)
- **Total records**: 1280
- **Records with URLs**: 443

| Data Source | Record Count |
|-------------|-------------|
| burgessrawson | 418 |
| seekbusiness | 239 |
| lilleychildcaresales | 172 |
| anybusiness | 146 |
| perituschildcare | 92 |
| businessforsale | 59 |
| commercialrealestate | 56 |
| childcare4sale | 33 |
| sydneychildcaresales | 17 |
| childcare concept | 7 |

---

## 7. Excel Export Formatting

All `04_export.py` scripts produce identically styled Excel files:

- **Header**: Bold white text on dark blue (#1F4E79), centered, wrapped, height 30px, frozen at A2
- **Data rows**: Alternating light blue (#EBF3FB) and white (#FFFFFF), thin borders
- **Status column**: Red (#CC0000) for "Sold", Green (#116830) for "Active"
- **Column widths**: URL=50, Business No.=14, Date=16, Data Source=20/22, others=18
- **CSV encoding**: UTF-8-sig (BOM for Excel compatibility)

---

## 8. Tech Stack

- **[crawl4ai](https://github.com/unclecode/crawl4ai)** v0.8.0 — Async browser-based crawler with Playwright backend
- **BeautifulSoup4** — HTML parsing and CSS selector extraction
- **openpyxl** — Styled Excel output
- **requests** — REST API calls (perituschildcare)
- **Python 3.11+** (Anaconda distribution)
