#!/usr/bin/env python3
"""
Step 3: For each listing URL, fetch detail page and extract all fields.
Input:  data/listing_urls_anybusiness.json
Output: data/childcare_raw_anybusiness.json  (one dict per listing)

Field extraction strategy:
  - Structured HTML fields → CSS selectors / itemprop
  - Description-text fields → regex patterns
  - Empty if not found (never skip the column)
"""

import asyncio
import os
import json
import re
import sys
import time
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dedup import DedupChecker

os.makedirs("data", exist_ok=True)

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
    page_timeout=45000,
    delay_before_return_html=2.0,
    remove_overlay_elements=True,
)

DELAY = 1.5          # seconds between requests
CONCURRENCY = 3      # parallel crawls
PROGRESS_SAVE = 10   # save progress every N listings

# ── Date filter ──────────────────────────────────────────────────────────────
# Only keep records whose "Updated on" date falls within this range (inclusive).
# Format: DD/MM/YYYY.  Set to None to disable the bound.
DATE_FROM = "01/01/2025"   # None = no lower bound
DATE_TO   = "12/03/2026"   # None = no upper bound

# ── All target columns ────────────────────────────────────────────────────────
COLUMNS = [
    "Business No.",
    "Date of Listing",
    "Data Source",
    "Related Source Item",
    "URL",
    "Suburb",
    "City",
    "State",
    "Location Direction",
    "Leasehold or Freehold",
    "Site",
    "On Sale or Not",
    "Sold Date",
    "Current Occupancy",
    "Price",
    "Net Income",
    "Net Income / Price",
    "Years to Recover Investment",
    "Place",
    "Rent",
    "Rent per Place",
    "Length of Lease",
    "Rent Increases (Annual)",
    "Area (sqm)",
    "Near School",
    "Near Supermarket",
    "Renovation",
    "Fitout",
    "Rent % Revenue",
    "EBITDA Condition 1",
    "Yield",
    "Estimated Annual Net Yield",
    "Daily Fee (0-2)",
    "Daily Fee (2-3)",
    "Daily Fee (3-5)",
    "Current Daily Fees",
    "EBITDA 1",
    "Percentage 1",
    "EBITDA 2",
    "Percentage 2",
    "EBITDA 3",
    "Percentage 3",
    "EBITDA 4",
    "Percentage 4",
    "Revenue",
    "Current EBITDA",
    "Current Percentage",
    "Supply Ratio",
    "Development",
    "# of Students Surrounding",
    "Average Household Income",
    "Resident Population",
    "0-5 Resident Population",
    "30-39 Females",
    "Population Growth Rate (Per Year)",
    "GRP of Region",
    "Waiting List",
    "Additional Places to be Added",
    "NQS Rating",
    "Parking Volume",
    "Vehicles Passing Daily",
    "Government Funding",
    "Land Tax Free",
]


# ── Helper: regex search in text ──────────────────────────────────────────────
def rx(pattern: str, text: str, group: int = 1, flags=re.IGNORECASE) -> str:
    """Return first regex match group or empty string."""
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else ""


def rx_any(patterns: list, text: str) -> str:
    """Try multiple patterns; return first match."""
    for p in patterns:
        v = rx(p, text)
        if v:
            return v
    return ""


def clean_money(s: str) -> str:
    """Normalise money strings like '$1,500,000' → '$1,500,000'."""
    s = s.strip()
    if not s:
        return ""
    # Remove trailing punctuation
    s = re.sub(r"[.,;:]+$", "", s)
    return s


def _parse_date(dmy: str):
    """Parse DD/MM/YYYY string → datetime.date, or None on failure."""
    from datetime import date as _date
    try:
        d, m, y = dmy.strip().split("/")
        return _date(int(y), int(m), int(d))
    except Exception:
        return None


_DATE_FROM = _parse_date(DATE_FROM) if DATE_FROM else None
_DATE_TO   = _parse_date(DATE_TO)   if DATE_TO   else None


# ── Main extractor ────────────────────────────────────────────────────────────
def extract(url: str, html: str, source_type: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    data = {col: "" for col in COLUMNS}

    # ── Fixed metadata ──────────────────────────────────────────────────────
    data["Data Source"] = "Anybusiness.com.au"
    data["URL"]         = url

    # ── Title (used for Related Source Item) ────────────────────────────────
    title_el = soup.select_one('[itemprop="name"] h1') or soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else ""
    data["Related Source Item"] = title

    # ── Business No. ───────────────────────────────────────────────────────
    sn = soup.select_one('[itemprop="serialNumber"]')
    data["Business No."] = sn.get_text(strip=True) if sn else rx(r"/listings/[^/]+-(\d+)$", url)

    # ── Status / Sold ───────────────────────────────────────────────────────
    # Active:      <div class="current">Active</div>
    # Sold:        text "SOLD" in description
    # Under Offer: <div class="under-contract">Under Offer</div>
    status_el = (
        soup.select_one(".current") or
        soup.select_one(".under-contract")
    )
    status_text = status_el.get_text(strip=True) if status_el else ""

    page_text = soup.get_text(" ", strip=True)

    if "under offer" in status_text.lower() or "under-contract" in str(status_el):
        data["On Sale or Not"] = "Under Offer"
    elif "SOLD" in page_text.upper() and "active" not in status_text.lower():
        data["On Sale or Not"] = "Sold"
        # Try to find sold date from description
        sold_date = rx_any([
            r"sold\s+(?:on|dated?|in)\s+([\w\s,/\-]+\d{4})",
            r"settlement\s+(?:date\s*:?\s*)?([\w\s,/\-]+\d{4})",
        ], page_text)
        data["Sold Date"] = sold_date
    else:
        # Fallback: parse "Status: X" label directly from offer block text
        status_label = rx(r"Status:\s*(Sold|Active|Under\s+Offer)", page_text)
        if status_label:
            sl = status_label.strip().lower()
            if "under" in sl:
                data["On Sale or Not"] = "Under Offer"
            elif "sold" in sl:
                data["On Sale or Not"] = "Sold"
            else:
                data["On Sale or Not"] = "Active"
        else:
            data["On Sale or Not"] = "Active"

    # ── Price ───────────────────────────────────────────────────────────────
    price_el = soup.select_one('[itemprop="price"]')
    if price_el:
        data["Price"] = clean_money(price_el.get_text(strip=True))
    else:
        # Fallback: look for "Price:" label in offer block
        for div in soup.select(".uk-flex"):
            t = div.get_text(" ", strip=True)
            if "Price:" in t and "$" in t:
                data["Price"] = clean_money(rx(r"Price:\s*(\$[\d,]+\+?)", t))
                break

    # ── Date of Listing (Updated on) ───────────────────────────────────────
    offer_block = soup.select_one('[itemtype*="schema.org/Offer"]')
    if offer_block:
        text = offer_block.get_text(" ", strip=True)
        data["Date of Listing"] = rx(r"Updated\s+on:\s*([\d/]+)", text)

    # ── Date filter ─────────────────────────────────────────────────────────
    if data["Date of Listing"] and (_DATE_FROM or _DATE_TO):
        listing_date = _parse_date(data["Date of Listing"])
        if listing_date:
            if _DATE_FROM and listing_date < _DATE_FROM:
                return None  # too old
            if _DATE_TO   and listing_date > _DATE_TO:
                return None  # too new

    # ── Location ───────────────────────────────────────────────────────────
    addr_el = soup.select_one('[itemprop="streetAddress"]')
    raw_addr = addr_el.get_text(strip=True) if addr_el else ""

    # Parse from URL slug: /listings/{suburb}-{state}-{postcode}-...-{id}
    slug_match = re.search(
        r"/listings/([^/]+)-([a-z]{2,3})-(\d{4})-",
        url, re.IGNORECASE
    )
    if slug_match:
        suburb_slug = slug_match.group(1).replace("-", " ").title()
        state_slug  = slug_match.group(2).upper()
    else:
        suburb_slug = ""
        state_slug  = ""

    data["Suburb"]  = raw_addr or suburb_slug
    data["City"]    = raw_addr or suburb_slug  # often same as suburb for AU
    data["State"]   = state_slug

    # ── Description text ───────────────────────────────────────────────────
    desc_el = soup.select_one('[itemprop="description"]')
    desc = desc_el.get_text("\n", strip=True) if desc_el else ""
    desc_lower = desc.lower()

    # ── Location Direction ──────────────────────────────────────────────────
    # Extract directional region from title then description, e.g.
    # "North-Western Victoria", "Inner West Sydney", "Eastern Suburbs"
    _AU_REGIONS = (
        r"Victoria|VIC|New South Wales|NSW|Queensland|QLD|"
        r"Western Australia|WA|South Australia|SA|"
        r"Tasmania|TAS|Northern Territory|NT|ACT|"
        r"Melbourne|Sydney|Brisbane|Perth|Adelaide|Hobart|Canberra|Darwin"
    )
    _DIR_CORE = (
        r"(?:inner|outer|far|mid|central|"
        r"north(?:ern)?|south(?:ern)?|east(?:ern)?|west(?:ern)?)"
        r"(?:[- ](?:west(?:ern)?|east(?:ern)?|north(?:ern)?|south(?:ern)?))?"
    )
    # Try title first ("in X"), then loose match in description
    loc_dir = rx_any([
        rf"\bin\s+((?:{_DIR_CORE}\s+)+(?:{_AU_REGIONS}))",
        rf"((?:{_DIR_CORE}\s+)+(?:{_AU_REGIONS}))",
        rf"((?:{_DIR_CORE}\s+)+(?:suburbs?|region|area|coast|metro))",
    ], title + " " + desc)
    data["Location Direction"] = loc_dir.strip() if loc_dir else ""

    # ── Leasehold or Freehold ──────────────────────────────────────────────
    if "freehold" in desc_lower:
        data["Leasehold or Freehold"] = "Freehold"
    elif "leasehold" in desc_lower:
        data["Leasehold or Freehold"] = "Leasehold"
    elif "lease" in desc_lower:
        data["Leasehold or Freehold"] = "Leasehold"

    # ── Revenue ────────────────────────────────────────────────────────────
    def _parse_money(text: str) -> str:
        """Extract first dollar amount and normalise to $X or $XM etc."""
        # Match: $1.2M, $1.2 million, $1,200,000, $1.2m+
        m = re.search(
            r"\$([\d,.]+)\s*([MKmk](?:illion|ILLION)?)?\+?",
            text, re.IGNORECASE
        )
        if not m:
            return ""
        num = m.group(1)
        suffix = (m.group(2) or "").upper()
        if suffix.startswith("M"):
            suffix = "M"
        elif suffix.startswith("K"):
            suffix = "K"
        return "$" + num + suffix

    def _find_money_near(keyword: str, text: str) -> str:
        """Find dollar amount near a keyword (before or after, within 60 chars)."""
        for m in re.finditer(keyword, text, re.IGNORECASE):
            start = max(0, m.start() - 60)
            end   = min(len(text), m.end() + 60)
            chunk = text[start:end]
            val = _parse_money(chunk)
            if val:
                return val
        return ""

    # ── Revenue ────────────────────────────────────────────────────────────
    data["Revenue"] = _find_money_near(r"revenue|turnover", desc)

    # ── Net Income ─────────────────────────────────────────────────────────
    data["Net Income"] = _find_money_near(r"net\s+(?:profit|income)|EBITDA", desc)

    # ── EBITDA ─────────────────────────────────────────────────────────────
    ebitda_matches = re.findall(
        r"(?:EBITDA)[^$\n]*\$([\d,.]+(?:[MKmk](?:illion)?)?)", desc, re.IGNORECASE
    )
    pct_matches = re.findall(
        r"(?:EBITDA|ebitda)[^%\d]*(\d+(?:\.\d+)?)\s*%", desc, re.IGNORECASE
    )
    for i, (col_val, col_pct) in enumerate(
        zip(["EBITDA 1","EBITDA 2","EBITDA 3","EBITDA 4"],
            ["Percentage 1","Percentage 2","Percentage 3","Percentage 4"])
    ):
        if i < len(ebitda_matches):
            data[col_val] = "$" + ebitda_matches[i]
        if i < len(pct_matches):
            data[col_pct] = pct_matches[i] + "%"

    # ── Current Occupancy / Licensed Places ───────────────────────────────
    data["Current Occupancy"] = rx_any([
        r"licensed\s+(?:for\s+)?(\d+)\+?\s+(?:children|places|kids|approved)",
        r"approved\s+for\s+(\d+)\+?\s+(?:children|places)",
        r"(\d+)\+?\s+(?:approved\s+)?places",
        r"capacity\s+(?:of\s+)?(\d+)\+?",
        r"(\d+)[- ]place\s+(?:centre|center|childcare|child\s+care)",
        r"(\d+)\+?\s+(?:licensed\s+)?(?:children|places)\s+(?:centre|center)?",
    ], desc)

    data["Place"] = data["Current Occupancy"]  # same field in different formats

    # ── Waiting List ───────────────────────────────────────────────────────
    if re.search(r"waiting\s+list|waitlist|wait\s+list", desc_lower):
        wl = rx(r"waiting\s+list\s+of\s+(\d+)", desc_lower) or \
             rx(r"(\d+)\s+(?:on\s+)?waiting\s+list", desc_lower) or "Yes"
        data["Waiting List"] = wl
    else:
        data["Waiting List"] = "No"

    # ── Current Daily Fees ─────────────────────────────────────────────────
    data["Current Daily Fees"] = rx_any([
        r"(?:fee|fees|charge)[^\d$\n]*\$([\d,]+(?:\.\d+)?)\s*(?:per\s+)?(?:child\s+)?(?:per\s+)?day",
        r"\$([\d,]+(?:\.\d+)?)\s*(?:/|per)\s*(?:child\s+)?(?:per\s+)?day",
        r"daily\s+(?:fee|fees)\s+of\s+\$?([\d,]+(?:\.\d+)?)",
        r"charges?\s+over\s+\$?([\d,]+(?:\.\d+)?)\s+per\s+(?:child\s+per\s+)?day",
        r"\$?([\d,]+(?:\.\d+)?)\s*per\s+day\s*(?:per\s+child)?",
        r"(?:fee|fees)\s+of\s+\$?([\d,]+(?:\.\d+)?)\s*/?\s*day",
    ], desc)
    if data["Current Daily Fees"] and not data["Current Daily Fees"].startswith("$"):
        data["Current Daily Fees"] = "$" + data["Current Daily Fees"]

    # ── Daily Fees by Age Group ────────────────────────────────────────────
    # Pattern: "$150 (0-2), $145 (2-3), $140 (3-5)" or table-like
    # Try to find age-specific fees
    for age_range, col_name in [("0-2", "Daily Fee (0-2)"),
                                  ("2-3", "Daily Fee (2-3)"),
                                  ("3-5", "Daily Fee (3-5)"),
                                  ("0.2", "Daily Fee (0-2)"),
                                  ("2.3", "Daily Fee (2-3)"),
                                  ("3.5", "Daily Fee (3-5)")]:
        age_rx = age_range.replace(".", r"[–\-]")
        v = rx(
            rf"\$(\d+(?:\.\d+)?)[^A-Za-z]*(?:for\s+)?(?:children\s+)?(?:aged?\s+)?{age_rx}",
            desc
        ) or rx(
            rf"{age_rx}[^A-Za-z$]*\$(\d+(?:\.\d+)?)",
            desc
        )
        if v and not data[col_name]:
            data[col_name] = "$" + v

    # Fall back: if we have current daily fee and no age breakdown
    if data["Current Daily Fees"] and not data["Daily Fee (0-2)"]:
        for col in ["Daily Fee (0-2)", "Daily Fee (2-3)", "Daily Fee (3-5)"]:
            data[col] = ""  # leave blank – not specified

    # ── Rent ───────────────────────────────────────────────────────────────
    data["Rent"] = rx_any([
        r"rent\s+(?:of\s+)?(?:approx\.?\s*)?\$([\d,]+(?:\.\d+)?)(?:\s*(?:per|p\.a\.|pa|annually|a\s+year))?",
        r"\$([\d,]+(?:\.\d+)?)\s*(?:per|p\.a\.|pa)\s+(?:in\s+)?rent",
        r"(?:annual\s+)?rent[:\s]+\$([\d,]+(?:\.\d+)?)",
        # No dollar sign format: "rent of approx. 3500"
        r"rent\s+(?:of\s+)?(?:approx\.?\s*)([\d,]+(?:\.\d+)?)\s*(?:per|p\.a\.)?",
    ], desc)
    if data["Rent"] and not data["Rent"].startswith("$"):
        data["Rent"] = "$" + data["Rent"]

    # ── Rent per Place ─────────────────────────────────────────────────────
    data["Rent per Place"] = rx_any([
        r"\$([\d,]+(?:\.\d+)?)\s*per\s+place\s+(?:per\s+)?(?:annum|year|pa|p\.a\.)",
        r"rent\s+of\s+approx\.?\s+\$([\d,]+(?:\.\d+)?)\s+per\s+place",
        r"rent\s+of\s+approx\.?\s+([\d,]+(?:\.\d+)?)\s+per\s+place",
        r"per\s+place\s+(?:per\s+)?(?:annum|year|pa)[^$\n]*\$([\d,]+(?:\.\d+)?)",
    ], desc)
    if data["Rent per Place"] and not data["Rent per Place"].startswith("$"):
        data["Rent per Place"] = "$" + data["Rent per Place"]

    # ── Length of Lease ───────────────────────────────────────────────────
    data["Length of Lease"] = rx_any([
        r"(\d+[\d\s]*[-+]\d*\s*year(?:s)?\s+(?:lease|term))",
        r"lease\s+(?:term\s+)?(?:of\s+)?(\d+\s+year(?:s)?)",
        r"(\d+)\s+year\s+(?:initial\s+)?lease",
        r"long\s+(\d+\s+year)\s+lease\s+(?:term\s+)?(?:with\s+options?)",
        r"lease\s+(?:term)?\s*[:\s]+(\d+\s+years?\s+\+?\s*\d*\s*years?)",
    ], desc)
    if not data["Length of Lease"]:
        data["Length of Lease"] = rx(r"(\d+\s+year[s]?\s+\+\s+\d+\s+year[s]?\s+option)", desc)

    # ── Rent Increases ─────────────────────────────────────────────────────
    data["Rent Increases (Annual)"] = rx_any([
        r"(\d+(?:\.\d+)?)\s*%\s+(?:annual\s+)?(?:rent\s+)?(?:increase|review|CPI)",
        r"(?:annual\s+)?(?:rent\s+)?(?:increase|review)[^\d%]*(\d+(?:\.\d+)?)\s*%",
        r"CPI[^\d]*(\d+(?:\.\d+)?)\s*%",
        r"rent\s+increases?\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*%",
    ], desc)

    # ── Area sqm ───────────────────────────────────────────────────────────
    data["Area (sqm)"] = rx_any([
        r"(\d[\d,]*)\s*(?:square\s+metres?|sqm|m²|m2)",
        r"(\d[\d,]*)\s*(?:sqm|m²|m2)\s+(?:of\s+)?(?:floor\s+)?(?:space|area)",
    ], desc)

    # ── Near School ────────────────────────────────────────────────────────
    sch = rx_any([
        r"(\d+(?:\.\d+)?)\s*(?:km|m|metres?|meters?)\s*(?:from|away from|of)?\s*(?:\w+\s+)?(?:primary|high|secondary)?\s*school",
        r"(?:primary|high|secondary)?\s*school[^.]*?(\d+(?:\.\d+)?)\s*(?:km|m)",
    ], desc)
    data["Near School"] = sch + (" km" if sch and "km" not in sch.lower() and "m" not in sch.lower() else "") if sch else ""

    # ── Near Supermarket ───────────────────────────────────────────────────
    sm = rx_any([
        r"(\d+(?:\.\d+)?)\s*(?:km|m)\s*(?:from)?\s*(?:\w+\s+)?supermarket",
        r"supermarket[^.]*?(\d+(?:\.\d+)?)\s*(?:km|m)",
        r"(\d+(?:\.\d+)?)\s*(?:km|m)\s*(?:from)?\s*(?:shops?|retail|shopping)",
    ], desc)
    data["Near Supermarket"] = sm if sm else ""

    # ── Renovation / Fitout ────────────────────────────────────────────────
    if re.search(r"renovate?d?|refurb|upgrade|new\s+build|purpose.built", desc_lower):
        data["Renovation"] = "Yes"
    if re.search(r"fitout|fit.out|fit\s+out|furnished|equipment", desc_lower):
        data["Fitout"] = "Yes"

    # ── NQS Rating ─────────────────────────────────────────────────────────
    nqs = rx_any([
        r"(exceeding)\s+(?:NQS|national\s+quality)",
        r"(meeting)\s+(?:NQS|national\s+quality)",
        r"(working\s+towards)\s+(?:NQS|national\s+quality)",
        r"NQS\s+(?:rating\s+(?:of\s+)?|rated\s+|assessment\s+of\s+)?(exceeding|meeting|working\s+towards)",
        r"rated\s+(exceeding|meeting|working\s+towards)",
        r"(exceeding|meeting)\s+nqs",
    ], desc)
    data["NQS Rating"] = nqs.title() if nqs else ""

    # ── Vehicles Passing Daily ─────────────────────────────────────────────
    data["Vehicles Passing Daily"] = rx_any([
        r"([\d,]+)\s+(?:cars?|vehicles?)\s+(?:passing|pass)\s+(?:by\s+)?(?:daily|per\s+day|a\s+day)",
        r"(?:daily\s+)?(?:traffic|vehicles?|cars?)\s+(?:count\s+)?(?:of\s+)?([\d,]+)\s+(?:cars?|vehicles?)?",
        r"([\d,]+)\s+(?:vehicles?|cars?)\s+per\s+day",
    ], desc)

    # ── Parking ────────────────────────────────────────────────────────────
    parking = rx_any([
        r"(\d+)\s+(?:car\s+)?(?:parking\s+)?(?:spaces?|bays?|spots?)",
        r"parking\s+(?:for\s+)?(\d+)\s+(?:cars?|vehicles?)",
        r"onsite\s+(?:car\s+)?parking[:\s]+(\d+)",
        r"car\s+park(?:ing)?\s+(?:for\s+)?(\d+)",
    ], desc)
    if parking:
        data["Parking Volume"] = parking + " spaces"
    elif re.search(r"onsite\s+(?:car\s+)?park|parking\s+available", desc_lower):
        data["Parking Volume"] = "Yes"

    # ── Government Funding ─────────────────────────────────────────────────
    if re.search(r"funded\s+kinder|government\s+funding|ccs|childcare\s+subsidy|ccs\s+approved", desc_lower):
        data["Government Funding"] = "Yes"

    # ── Land Tax Free ─────────────────────────────────────────────────────
    if re.search(r"land\s+tax\s+free|exempt\s+from\s+land\s+tax", desc_lower):
        data["Land Tax Free"] = "Yes"

    # ── Supply Ratio / Competition ─────────────────────────────────────────
    data["Supply Ratio"] = rx_any([
        r"(\d+(?:\.\d+)?)\s*(?:km|km\s+radius)[^\w]*(?:only\s+)?(?:childcare|centre|child\s+care)",
        r"only\s+(?:childcare|centre|child\s+care)\s+within\s+(\d+(?:\.\d+)?)\s*km",
        r"no\s+(?:direct\s+)?competition[^.]*within\s+(\d+(?:\.\d+)?)\s*km",
    ], desc)

    # ── Demographics ───────────────────────────────────────────────────────
    data["# of Students Surrounding"] = rx_any([
        r"(\d[\d,]+)\s+children\s+aged\s+(?:0-4|0-5|under\s+5)",
        r"market\s+of\s+([\d,]+)\s+children",
        r"([\d,]+)\s+children\s+(?:in\s+the\s+area|within)",
    ], desc)

    data["Resident Population"] = rx_any([
        r"population\s+(?:of\s+)?([\d,]+)",
        r"([\d,]+)\s+(?:residents?|people)\s+(?:in\s+the\s+area|within)",
        r"suburb\s+population[:\s]+([\d,]+)",
    ], desc)

    data["Population Growth Rate (Per Year)"] = rx(
        r"population\s+(?:growth\s+)?(?:rate\s+)?(?:of\s+)?(\d+(?:\.\d+)?)\s*%\s+(?:per\s+year|annually|p\.a\.)",
        desc
    )

    # ── Additional Places ──────────────────────────────────────────────────
    data["Additional Places to be Added"] = rx_any([
        r"additional\s+(\d+)\s+(?:approved\s+)?places",
        r"(?:expand|extension)\s+(?:to\s+)?(\d+)\s+(?:more\s+)?places",
        r"(\d+)\s+additional\s+(?:approved\s+)?places",
    ], desc)

    # ── Development nearby ─────────────────────────────────────────────────
    if re.search(r"(?:housing|residential)\s+(?:estate|development|growth|estate)", desc_lower):
        data["Development"] = rx_any([
            r"(\d+)\s+(?:new\s+)?(?:homes?|blocks?|lots?|units?)\s+(?:being\s+)?(?:built|developed|under\s+construction)",
            r"(?:housing|residential)\s+(?:estate|development)[^.]*?(\d+\s+(?:homes?|lots?|blocks?))",
        ], desc) or "Yes"

    # ── Leasehold/Freehold → Site ──────────────────────────────────────────
    data["Site"] = data["Leasehold or Freehold"]

    # ── Net Income / Price ratio ───────────────────────────────────────────
    if data["Net Income"] and data["Price"]:
        try:
            def parse_money(s):
                s = re.sub(r"[,$\s]", "", s)
                if s.upper().endswith("M"):
                    return float(s[:-1]) * 1_000_000
                if s.upper().endswith("K"):
                    return float(s[:-1]) * 1_000
                return float(s)
            ni = parse_money(data["Net Income"])
            pr = parse_money(data["Price"])
            if pr > 0:
                ratio = ni / pr
                data["Net Income / Price"] = f"{ratio:.2%}"
                if ratio > 0:
                    data["Years to Recover Investment"] = f"{1/ratio:.1f}"
        except Exception:
            pass

    return data


# ── Async crawler loop ────────────────────────────────────────────────────────
async def process_batch(crawler, batch: list[dict]) -> tuple[list[dict], list[str]]:
    """Crawl a batch concurrently and extract data.
    Returns (records, date_filtered_urls).
    """
    tasks = [crawler.arun(url=item["url"], config=CRAWLER_CFG) for item in batch]
    results_html = await asyncio.gather(*tasks, return_exceptions=True)

    records = []
    date_filtered = []
    for item, res in zip(batch, results_html):
        if isinstance(res, Exception):
            print(f"  ❌ Error {item['url']}: {res}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "Anybusiness.com.au"
            records.append(rec)
            continue

        if not res.success:
            print(f"  ❌ Failed {item['url']}: {res.error_message}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "Anybusiness.com.au"
            records.append(rec)
            continue

        try:
            rec = extract(item["url"], res.html, item.get("source_type", ""))
        except Exception as e:
            print(f"  ⚠️ Extract error {item['url']}: {e}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "Anybusiness.com.au"

        if rec is None:
            print(f"  ⏭ Filtered (date out of range): {item['url']}")
            date_filtered.append(item["url"])
        else:
            records.append(rec)
    return records, date_filtered


async def main():
    # Load listing URLs
    urls_path = "data/listing_urls_anybusiness.json"
    if not os.path.exists(urls_path):
        print(f"❌ {urls_path} not found. Run 02_crawl_all_listings_anybusiness.py first.")
        return

    with open(urls_path, encoding="utf-8") as f:
        listings = json.load(f)

    print("=" * 65)
    print(f"  Anybusiness Childcare — Extract Detail Pages")
    print(f"  Total listings to process: {len(listings)}")
    if _DATE_FROM or _DATE_TO:
        print(f"  Date filter: {DATE_FROM or '∞'} → {DATE_TO or '∞'}")
    print("=" * 65)

    # Load existing progress (saved records)
    output_path   = "data/childcare_raw_anybusiness.json"
    filtered_path = "data/date_filtered_urls_anybusiness.json"
    done_urls = set()
    all_records = []

    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            all_records = json.load(f)
        done_urls = {r["URL"] for r in all_records}

    # Also treat previously date-filtered URLs as done (avoid re-crawling)
    all_filtered_urls = []
    if os.path.exists(filtered_path):
        with open(filtered_path, encoding="utf-8") as f:
            all_filtered_urls = json.load(f)
        done_urls.update(all_filtered_urls)

    print(f"  Resuming: {len(done_urls)} already processed "
          f"({len(all_records)} kept, {len(all_filtered_urls)} filtered).")

    remaining = [l for l in listings if l["url"] not in done_urls]

    # Dedup against master database (second-pass safety net)
    checker = DedupChecker()
    remaining = checker.filter_extract_listings(
        remaining, source="anybusiness", log_dir="data"
    )
    print(f"  Remaining: {len(remaining)}")

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:
        for i in range(0, len(remaining), CONCURRENCY):
            batch = remaining[i : i + CONCURRENCY]
            print(f"\n[{i+1}-{min(i+CONCURRENCY, len(remaining))}/{len(remaining)}] Processing...")
            for item in batch:
                print(f"  → {item['url']}")

            records, date_filtered = await process_batch(crawler, batch)
            all_records.extend(records)
            all_filtered_urls.extend(date_filtered)

            for rec in records:
                status = rec.get("On Sale or Not", "?")
                price  = rec.get("Price", "N/A")
                bus_no = rec.get("Business No.", "?")
                print(f"  ✅ #{bus_no} | {status} | {price}")

            # Save progress periodically
            if (i // CONCURRENCY + 1) % (PROGRESS_SAVE // CONCURRENCY + 1) == 0:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(all_records, f, indent=2, ensure_ascii=False)
                with open(filtered_path, "w", encoding="utf-8") as f:
                    json.dump(all_filtered_urls, f, indent=2, ensure_ascii=False)
                print(f"  💾 Progress saved ({len(all_records)} records, "
                      f"{len(all_filtered_urls)} filtered)")

            await asyncio.sleep(DELAY)

    # Final save
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)
    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(all_filtered_urls, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 65)
    print(f"  DONE: {len(all_records)} records kept → {output_path}")
    if all_filtered_urls:
        print(f"  Date-filtered (skipped): {len(all_filtered_urls)} → {filtered_path}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
