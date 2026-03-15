# Childcare Crawler Dev

A collection of web scrapers for extracting childcare centre sale listings across Australian business-for-sale platforms. Each scraper follows a standardised 4-step pipeline and outputs a unified 63-field dataset for downstream analysis.

## Target Sites

| Scraper | Website | Listings | Tech Stack |
|---------|---------|----------|------------|
| **anybusiness** | [anybusiness.com.au](https://www.anybusiness.com.au/child-care-for-sale) | ~429 (active + sold) | Rails + UIKit + React (server-rendered) |
| **businessforsale** | [businessforsale.com.au](https://www.businessforsale.com.au) | ~25 (childcare category) | JS-rendered |
| **sydneychildcaresales** | [sydneychildcaresales.com.au](https://www.sydneychildcaresales.com.au) | ~62 (for-sale + sold) | WordPress + Elementor (JS masonry gallery) |
| **lilleychildcaresales** | [lilleyccs.com](https://www.lilleyccs.com) | Variable | Custom site (Isotope/Masonry JS) |
| **perituschildcare** | [perituschildcare.com.au](https://perituschildcare.com.au) | Variable | WordPress + REST API |

## Pipeline Architecture

Every scraper follows the same 4-step pipeline:

```
01_fetch_html.py   →  Fetch sample pages for selector analysis (dev/debug only)
02_crawl_all_listings.py  →  Collect all listing URLs → listing_urls.json
03_extract_details.py     →  Extract 63 fields from each detail page → childcare_raw.json
04_export.py              →  Export JSON → Excel (.xlsx) + CSV
run_all.py                →  One-click runner (steps 2 → 3 → 4)
```

### Step Details

1. **Fetch HTML** (`01_fetch_html.py`) — Downloads raw HTML, markdown, and screenshots from sample pages. Used during development to identify CSS selectors and page structure. Not required for production runs.

2. **Crawl All Listings** (`02_crawl_all_listings.py`) — Navigates paginated listing/gallery pages and collects all detail page URLs. Handles both active and sold listings. Supports configurable date filtering (`DATE_FROM` / `DATE_TO`).

3. **Extract Details** (`03_extract_details.py`) — Visits each detail page and extracts structured data. Uses a combination of CSS selectors, schema.org markup, and regex parsing of free-text descriptions. Supports resume-on-restart (skips already-processed URLs) and runs 3 concurrent workers.

4. **Export** (`04_export.py`) — Converts the raw JSON into formatted Excel (blue header, alternating row colours via openpyxl) and CSV files.

## Output Schema (63 Fields)

All scrapers produce the same standardised columns:

| Category | Fields |
|----------|--------|
| **Basic** | Business No., Date, Data Source, URL, Suburb, City, State, Location Direction |
| **Status** | On Sale / Under Offer / Sold, Sold Date |
| **Property** | Leasehold / Freehold, Site Type |
| **Operations** | Licensed Places, Current Occupancy (%), Rent, Rent per Place, Lease Terms |
| **Financial** | Price, Net Income, Revenue, EBITDA, Yield, Daily Fees (0-2, 2-3, 3-5) |
| **Demographics** | Supply Ratio, Population (0-5), 30-39 Females, Avg Household Income, Growth Rate, GRP |
| **Quality** | NQS Rating, Government Funding, Parking, Waiting List |
| **Site** | Area (sqm), Near School, Supermarket, Renovation, Fitout, Land Tax Free |

## Tech Stack

- **[crawl4ai](https://github.com/unclecode/crawl4ai)** (v0.8.0) — Async browser-based crawler with Playwright backend
- **BeautifulSoup4** — HTML parsing and CSS selector extraction
- **openpyxl** — Styled Excel output
- **Python 3.11+**

## Setup

```bash
# Install dependencies
pip install crawl4ai beautifulsoup4 openpyxl

# Install Playwright browsers (required by crawl4ai)
playwright install chromium
```

## Usage

Run a complete scrape for any site:

```bash
cd anybusiness/        # or any other scraper directory
python run_all.py      # runs steps 2 → 3 → 4
```

Or run individual steps:

```bash
python 02_crawl_all_listings.py   # collect URLs
python 03_extract_details.py      # extract data (resumable)
python 04_export.py               # generate Excel + CSV
```

Output files are written to each scraper's `data/` directory.

## Deduplication Module

A shared deduplication module (`dedup.py`) prevents re-crawling listings that already exist in the master database spreadsheet (`0.final data leasehold & freehold.xlsx`).

### How It Works

The module is integrated into both **Step 2** (URL collection) and **Step 3** (detail extraction) of every scraper, providing two layers of dedup:

| Priority | Strategy | Description |
|----------|----------|-------------|
| 1 | **URL match** | Normalised URL comparison (strips protocol, `www.`, trailing `/`) |
| 2 | **Title match** | Data Source + normalised title combo (strips punctuation, collapses whitespace) |
| 3 | **Code match** | Data Source + listing code (for lilleychildcaresales which has no unique URLs) |

### Skip Log

Skipped listings are logged to `data/dedup_skipped.json` in each scraper directory for verification. Each entry includes:
- All original listing fields
- `_dedup_reason`: `url_match`, `title_match`, or `code_match`
- `_dedup_time`: timestamp of when the record was skipped

### Configuration

- The module automatically loads the master Excel file from the project root
- If the Excel file is missing, dedup is silently disabled (crawlers run normally)
- No manual configuration needed — just keep the master spreadsheet in `Crawler_dev/`

### Data Source Mapping

| Crawler | Excel `Data Source` value | Crawler `Data Source` value |
|---------|--------------------------|----------------------------|
| anybusiness | `anybusiness` | `Anybusiness.com.au` |
| businessforsale | `businessforsale` | `BusinessForSale.com.au` |
| lilleychildcaresales | `lilleychildcaresales` | `LilleyCCS.com` |
| perituschildcare | `perituschildcare` | `PeritusChildcare.com.au` |
| sydneychildcaresales | `sydneychildcaresales` | `SydneyChildcareSales.com.au` |

## Project Structure

```
Crawler_dev/
├── dedup.py                  # Shared deduplication module
├── 0.final data leasehold & freehold.xlsx  # Master database spreadsheet
├── anybusiness/              # anybusiness.com.au scraper
│   ├── 01_fetch_html.py
│   ├── 02_crawl_all_listings.py
│   ├── 03_extract_details.py
│   ├── 04_export.py
│   ├── run_all.py
│   ├── data/                 # output data (gitignored)
│   │   └── dedup_skipped.json  # skipped listings log
│   └── html_output/          # debug HTML/screenshots (gitignored)
├── businessforsale/          # businessforsale.com.au scraper
│   └── (same structure)
├── sydneychildcaresales/     # sydneychildcaresales.com.au scraper
│   └── (same structure)
├── lilleychildcaresales/     # lilleyccs.com scraper
│   └── (same structure)
├── perituschildcare/         # perituschildcare.com.au scraper
│   └── (same structure)
└── README.md
```

## Site-Specific Notes

### anybusiness
- Largest dataset (~429 listings). Sold filter requires JS interaction (checkbox + "Search now").
- Most childcare-specific fields are embedded in free-text descriptions and extracted via regex.

### businessforsale
- JS-rendered pages require headless browser. Automatically filters out franchise and "WANTED" listings.
- Breadcrumb-based location extraction.

### sydneychildcaresales
- Gallery is JS-rendered (Isotope/Masonry) — requires extra wait time (`delay_before_return_html=10s`).
- Status determined from image filenames (`sold-*`, `under-offer-*`).
- Dates from JSON-LD `datePublished` schema markup.

### lilleychildcaresales
- Multiple status categories: Active, Under Offer, Under Contract, Sold.
- Sold page only shows current financial year listings (no historical archive).
- Excludes "DA Site" listings.

### perituschildcare
- Uses WordPress REST API (`/wp-json/wp/v2/posts`) for efficient listing collection — no browser needed for URL scraping.
- Three category endpoints: Current (cat 68), Under Contract (cat 72), Sold (cat 73).
