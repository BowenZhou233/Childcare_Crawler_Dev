# Anybusiness.com.au Childcare Scraper

Collects all childcare-for-sale and sold listings from [anybusiness.com.au](https://www.anybusiness.com.au/child-care-for-sale) and exports to Excel/CSV.

## Scripts

| Script | Description |
|---|---|
| `01_fetch_html.py` | Fetch raw HTML for structural analysis |
| `02_crawl_all_listings.py` | Collect all listing URLs (active + sold) → `data/listing_urls.json` |
| `03_extract_details.py` | Extract 63 fields from each detail page → `data/childcare_raw.json` |
| `04_export.py` | Export JSON → `data/childcare_data.xlsx` + `data/childcare_data.csv` |
| `run_all.py` | One-click runner: steps 2 → 3 → 4 |

## Quick Start

```bash
pip install crawl4ai beautifulsoup4 openpyxl
crawl4ai-setup

# Run everything
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
DATE_TO   = "12/03/2026"   # DD/MM/YYYY — set to None for no upper bound
```

Records outside this range are skipped and tracked in `data/date_filtered_urls.json` to avoid re-crawling.

## Output Columns (63 fields)

Business No., Date of Listing, Data Source, Related Source Item, URL, Suburb, City, State, Location Direction, Leasehold or Freehold, Site, On Sale or Not, Sold Date, Current Occupancy, Price, Net Income, Net Income / Price, Years to Recover Investment, Place, Rent, Rent per Place, Length of Lease, Rent Increases (Annual), Area (sqm), Near School, Near Supermarket, Renovation, Fitout, Rent % Revenue, EBITDA Condition 1, Yield, Estimated Annual Net Yield, Daily Fee (0-2), Daily Fee (2-3), Daily Fee (3-5), Current Daily Fees, EBITDA 1–4, Percentage 1–4, Revenue, Current EBITDA, Current Percentage, Supply Ratio, Development, # of Students Surrounding, Average Household Income, Resident Population, 0-5 Resident Population, 30-39 Females, Population Growth Rate (Per Year), GRP of Region, Waiting List, Additional Places to be Added, NQS Rating, Parking Volume, Vehicles Passing Daily, Government Funding, Land Tax Free

## Site Technical Notes

- **Stack**: Ruby on Rails + UIKit CSS + React (server-rendered)
- **Active listings**: `/child-care-for-sale` (~133 listings, 25/page)
- **Sold listings**: `/child-care-for-sale?status=sold` (~296 listings, 25/page)
- **Pagination**: `?page=N`; total pages computed from "X of Y results" text
- **Status classes**: `.current` (Active), `.under-contract` (Under Offer); Sold detected via page text
- **Most fields**: extracted via regex from free-text `[itemprop="description"]`

## Dev Log

See [MEMORY.md](MEMORY.md) for detailed notes on selectors, field extraction patterns, known issues, and fixes.
