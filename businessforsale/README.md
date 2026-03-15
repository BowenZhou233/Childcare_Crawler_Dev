# BusinessForSale.com.au Childcare Centre Scraper

Collects childcare centre listings from [businessforsale.com.au](https://www.businessforsale.com.au) category page and exports to Excel/CSV.

## Scripts

| Script | Description |
|---|---|
| `01_fetch_html.py` | Fetch raw HTML for structural analysis |
| `02_crawl_all_listings.py` | Collect listing URLs from childcare-centre category → `data/listing_urls.json` |
| `03_extract_details.py` | Extract 63 fields from each detail page → `data/childcare_raw.json` |
| `04_export.py` | Export JSON → `data/childcare_data.xlsx` + `data/childcare_data.csv` |
| `run_all.py` | One-click runner: steps 2 → 3 → 4 |

## Quick Start

```bash
pip install crawl4ai beautifulsoup4 openpyxl
crawl4ai-setup

# Step 1: Analyse site structure (run once)
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

## Category URL

`02_crawl_all_listings.py` uses the dedicated childcare-centre category (not keyword search):

```python
CATEGORY_URL = "https://www.businessforsale.com.au/for-sale/education/childcare-centre/"
```

This ensures only genuine childcare centre listings are collected. Franchise and "WANTED" listings are automatically filtered out.

## Output Columns (63 fields)

Same as the anybusiness scraper — see [anybusiness/README.md](../anybusiness/README.md) for full column list.

## Site Technical Notes

- **Category URL**: `/for-sale/education/childcare-centre/`
- **Pagination**: `?page=N`, 18 results per page
- **Detail page URL**: `/australia/{ID}/{slug}`
- **JS-rendered**: Site requires headless browser (crawl4ai) for full content
- **Results counter**: "Showing X to Y of Z businesses"
- **Filters**: Franchise listings and "WANTED" buyer ads are skipped automatically

## Data Quality (latest run: 2026-03-15)

| Field | Fill Rate |
|---|---|
| State | 100% |
| Price | 100% |
| Suburb | 92% |
| Leasehold/Freehold | 80% |
| Place (licensed places) | 60% |
| Revenue | 16% |
| Current Occupancy | 16% |
| NQS Rating | 12% |
| Daily Fee | 8% |

- Total: 25 listings (24 Active, 1 Sold)
- Place = number of licensed places (e.g. 85)
- Current Occupancy = occupancy percentage (e.g. 61%)

## Dev Log

See [MEMORY.md](MEMORY.md) for detailed development notes.
