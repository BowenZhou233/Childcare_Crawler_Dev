# Sydney Childcare Sales Scraper

## Site Info
- **URL**: https://www.sydneychildcaresales.com.au
- **Platform**: WordPress + Elementor page builder
- **For-sale gallery**: `/for-sale-gallery/` (3 pages, 8 per page)
- **Sold gallery**: `/sold-gallery/` (6 pages, 7-8 per page)
- **Pagination**: WordPress default `/page/N/` suffix
- **Detail pages**: `/portfolio/[slug]/`
- **Organization**: Pabro P/L t/as Sydney Childcare Sales, ABN 24 167 805 165

## Key CSS Selectors & Patterns

### Gallery pages (JS-rendered via Elementor deo-portfolio widget)
- **Portfolio widget**: `.elementor-widget-deo-portfolio`
- **Grid container**: `.row.masonry-grid` (Isotope/Masonry layout)
- **Listing card**: `.masonry-item.project` (each has `data-id="id-XXXX"`)
- **Inner container**: `.project__container.post-XXXX.portfolio` (has WP post ID and category classes)
- **Image holder**: `.project__img-holder > a[href*="/portfolio/"] > img.project__img`
- **Title**: `.project__title` or `h3.project__title > a`
- **Pagination**: `nav.pagination.portfolio-pagination` → `.page-numbers` (spans + links)
- **Category filter tabs**: "All", "For Sale", "Offer / Contract in Place" (CSS: `.term-15`, `.term-16`)

### Status detection (from image filename)
- `sold-*.jpg` → Sold
- `under-offer-*.jpg` → Under Offer
- `under-contract-*.jpg` → Under Contract
- Other → Active
- Also from container class: `portfolio_categories-offer-contract-in-place`

### Detail pages (Elementor text widgets)
- **Page title**: `h1.elementor-heading-title` or `<h1>`
- **Content widgets**: `.elementor-widget-text-editor` (free-text paragraphs)
- **JSON-LD**: `datePublished`, `dateModified` in `schema.org/WebPage` markup
- **No structured listing markup** (no itemprop, microdata) — all fields in free text

## Data Fields (from detail pages, regex-extracted)
- **Price**: "Price: $1,450,000" or "Expressions of Interest" or "EOI"
- **Location**: "Location: Parramatta area" (also parsed from title after "–")
- **Approved Places**: "Service Approval Places: 40 Places" or "XX places"
- **Occupancy**: "Current Occupancy: 90-100%" or "FY2025 Occupancy: 97.5%"
- **Revenue/Turnover**: "2024 Revenue: $742,340" or "Turnover: ~$1.05m"
- **Lease Terms**: "New Lease to be negotiated – 10 x 10 x 5" (format: initial x option x option)
- **Category of Care**: "Long Day Care", "Before & After School"
- **Property ID**: "Property ID: 1632530" (fallback: URL slug)
- **NQS Rating**: "Exceeding NQS" in description text
- **Land Area**: "Land Area: 958m2 approx" or "XXXm2"
- **Supply Ratio**: "Population 0-4 per LDC: X.X" (site-specific metric)

## Scripts
- `01_fetch_html.py` — fetch raw HTML for analysis (screenshots, markdown, links)
- `02_crawl_all_listings.py` — collect all listing URLs (for-sale + sold galleries)
- `03_extract_details.py` — extract 63 fields from each detail page (3 concurrent, resumes on restart)
- `04_export.py` — export JSON → CSV + Excel (openpyxl, blue header, alternating rows)
- `run_all.py` — one-click runner for steps 2→3→4

## Data Quality (2026-03-15, date filter >=2025-01-01)
- Total crawled: 62 listings (16 for-sale, 46 sold)
- After date filter: 14 records (10 Active, 3 Sold, 1 Under Offer)
- Price: 14/14 (100%)
- Place: 13/14 (93%)
- Suburb: 14/14 (100%)
- Occupancy: 7/14 (50%)
- Revenue: 4/14 (29%)
- Area: 5/14 (36%)
- Leasehold/Freehold: 12/14 (86%)
- NQS Rating: 1/14 (7%)
- Note: Most listings on this site have limited financial data compared to anybusiness/businessforsale

## Development Log

### 2026-03-15: Initial build
1. **Reference projects**: Built following the same 4-step pipeline architecture as `anybusiness/` and `businessforsale/` scrapers
2. **Site analysis via WebFetch**: Discovered WordPress + Elementor stack, gallery + detail page structure
3. **01_fetch_html.py created**: Fetches for-sale gallery, sold gallery, and auto-detects first detail page
4. **Critical discovery — JS rendering**: Gallery content is empty in raw HTML. The Elementor `deo-portfolio` widget uses Isotope/Masonry JS to render items dynamically. The `.masonry-grid` div has computed height but zero children in server-rendered HTML.
5. **Fix**: Added `js_code` with 5s extra wait + set `delay_before_return_html=10.0` + disabled `remove_overlay_elements` in `02_crawl_all_listings.py`. This allows JS to render the masonry grid items before HTML extraction.
6. **Actual card structure discovered**: `.masonry-item.project` → `.project__container` → `a[href*="/portfolio/"]` + `img.project__img` + `.project__title`
7. **02_crawl_all_listings.py**: Extracts from masonry items with fallback to plain link detection. Status from image filename + container category classes.
8. **03_extract_details.py**: Adapted regex patterns from businessforsale. Key differences:
   - Dates from JSON-LD `datePublished` (not page text)
   - Status from image filenames (not CSS classes)
   - Price/Revenue/Places all in Elementor text widget free text
   - Lease format: "10 x 10 x 5" (not "10 years + 10 years")
   - Supply Ratio: "Population 0-4 per LDC" (site-specific metric)
   - Location parsed from title suffix (after "–") as fallback
9. **04_export.py + run_all.py**: Identical structure to existing scrapers (63 columns, styled Excel, UTF-8 CSV)
10. **Full pipeline test**: 62 URLs collected → 14 records kept (48 filtered by date) → CSV + Excel exported successfully
