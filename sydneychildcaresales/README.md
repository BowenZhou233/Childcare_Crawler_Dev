# SydneyChildcareSales.com.au Scraper

Collects childcare centre listings (for-sale + sold) from [sydneychildcaresales.com.au](https://www.sydneychildcaresales.com.au) and exports to Excel/CSV.

## Scripts

| Script | Description |
|---|---|
| `01_fetch_html.py` | Fetch raw HTML for structural analysis |
| `02_crawl_all_listings.py` | Collect listing URLs from for-sale + sold galleries → `data/listing_urls.json` |
| `03_extract_details.py` | Extract 63 fields from each detail page → `data/childcare_raw.json` |
| `04_export.py` | Export JSON → `data/childcare_data.xlsx` + `data/childcare_data.csv` |
| `run_all.py` | One-click runner: steps 2 → 3 → 4 |

## Quick Start

```bash
pip install crawl4ai beautifulsoup4 openpyxl
crawl4ai-setup

# Step 1: Analyse site structure (run once, optional)
python 01_fetch_html.py
# → Review html_output/ to verify CSS selectors

# Run everything (steps 2-4)
python run_all.py

# Or individual steps
python run_all.py --step 2   # collect URLs
python run_all.py --step 3   # extract details
python run_all.py --step 4   # export
```

## Date Filter

Edit the constants at the top of `03_extract_details.py`:

```python
DATE_FROM = "01/01/2025"   # DD/MM/YYYY — set to None for no lower bound
DATE_TO   = None           # DD/MM/YYYY — set to None for no upper bound
```

Records outside this range are skipped and tracked in `data/date_filtered_urls.json` to avoid re-crawling on restart.

## Gallery URLs

`02_crawl_all_listings.py` crawls two separate galleries:

```python
FORSALE_GALLERY = "https://www.sydneychildcaresales.com.au/for-sale-gallery/"
SOLD_GALLERY    = "https://www.sydneychildcaresales.com.au/sold-gallery/"
```

## Output Columns (63 fields)

Same as the anybusiness/businessforsale scrapers — see [anybusiness/README.md](../anybusiness/README.md) for full column list.

## Site Technical Notes

- **Platform**: WordPress + Elementor page builder
- **Gallery widget**: Elementor `deo-portfolio` with Masonry/Isotope JS rendering
- **Gallery content is JS-rendered**: Items load dynamically via JavaScript; crawler uses `js_code` with extra 5s wait to ensure items render before extraction
- **For-sale gallery**: `/for-sale-gallery/` (~3 pages, 8 per page)
- **Sold gallery**: `/sold-gallery/` (~6 pages, 7-8 per page)
- **Pagination**: WordPress default `/page/N/` suffix, `.page-numbers` class
- **Detail page URL**: `/portfolio/{slug}/`
- **Listing card structure** (JS-rendered):
  - `.masonry-item.project` → card wrapper
  - `.project__container` → inner container (has WordPress post ID in class)
  - `.project__img-holder > a > img.project__img` → image + link
  - `.project__title` → title text
- **Status detection**: Image filename (`sold-*`, `under-offer-*`, `under-contract-*`)
- **Dates**: JSON-LD `schema.org` markup (`datePublished`, `dateModified`)
- **Data fields**: All in Elementor free-text widgets, extracted via regex
- **No structured data**: No `itemprop`, microdata, or dedicated listing markup

## Data Quality (latest run: 2026-03-15)

| Field | Fill Rate |
|---|---|
| Price | 100% (14/14) |
| Suburb | 100% (14/14) |
| Place (licensed places) | 93% (13/14) |
| Leasehold/Freehold | 86% (12/14) |
| Current Occupancy | 50% (7/14) |
| Revenue | 29% (4/14) |
| Area (sqm) | 36% (5/14) |
| NQS Rating | 7% (1/14) |

- Total crawled: 62 listings (16 for-sale, 46 sold)
- After date filter (>=2025-01-01): 14 records (10 Active, 3 Sold, 1 Under Offer)
- Step 3 supports **resume on restart** (skips already-processed URLs)

## Dev Log

See [MEMORY.md](MEMORY.md) for detailed development notes.
