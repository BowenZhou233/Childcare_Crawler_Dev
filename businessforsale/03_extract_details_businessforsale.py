#!/usr/bin/env python3
"""
Step 3: For each listing URL, fetch detail page and extract all fields.
Input:  data/listing_urls_businessforsale.json
Output: data/childcare_raw_businessforsale.json  (one dict per listing)

Field extraction strategy:
  - Structured HTML fields → CSS selectors (to be refined after HTML analysis)
  - Description-text fields → regex patterns (reused from anybusiness)
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
    delay_before_return_html=3.0,
    remove_overlay_elements=True,
)

DELAY = 1.5          # seconds between requests
CONCURRENCY = 3      # parallel crawls
PROGRESS_SAVE = 10   # save progress every N listings

# ── Date filter ──────────────────────────────────────────────────────────────
# Only keep records whose date falls within this range (inclusive).
# Format: DD/MM/YYYY.  Set to None to disable the bound.
DATE_FROM = "01/01/2025"   # None = no lower bound
DATE_TO   = None           # None = no upper bound

# ── All target columns (same as anybusiness) ─────────────────────────────────
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
    """Normalise money strings."""
    s = s.strip()
    if not s:
        return ""
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


def _parse_date_various(text: str):
    """Try to parse dates in various formats: DD/MM/YYYY, DD MMM YYYY, etc."""
    from datetime import date as _date, datetime
    text = text.strip()

    # DD/MM/YYYY
    d = _parse_date(text)
    if d:
        return d

    # DD Mon YYYY or DD Month YYYY (e.g. "14 Mar 2026")
    for fmt in ["%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y",
                "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"]:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


_DATE_FROM = _parse_date(DATE_FROM) if DATE_FROM else None
_DATE_TO   = _parse_date(DATE_TO)   if DATE_TO   else None


# ── Main extractor ────────────────────────────────────────────────────────────
def extract(url: str, html: str) -> dict:
    """
    Extract all 63 fields from a detail page.

    Confirmed CSS structure (from 01_fetch_html.py analysis):
      Title:       h1
      Price:       strong.price (inside div.price, "Asking Price $X")
      Revenue:     label "Revenue" near price block
      Profit:      label "Profit" near price block
      Client No:   div.client-info → "Client No: X"
      Last Updated: span.updated-text → "Last Updated DD Mon YYYY"
      Category:    span.category (multiple)
      Location:    breadcrumb links /for-sale/{state}/ and /for-sale/{city}-{state}-{postcode}/
      Description: div[itemprop="description"] or About section text
    """
    soup = BeautifulSoup(html, "html.parser")
    data = {col: "" for col in COLUMNS}

    # ── Fixed metadata ──────────────────────────────────────────────────────
    data["Data Source"] = "BusinessForSale.com.au"
    data["URL"]         = url

    # ── Business ID ──────────────────────────────────────────────────────────
    # From URL slug: /australia/{ID}/{slug}
    id_match = re.search(r"/australia/([^/]+)/", url)
    url_id = id_match.group(1) if id_match else ""

    # From page: "Client No: X"
    client_info = soup.select_one("div.client-info")
    client_text = client_info.get_text(" ", strip=True) if client_info else ""
    client_no = rx(r"Client\s+No[:\s]+(\S+)", client_text)
    data["Business No."] = client_no or url_id

    # ── Full page text ───────────────────────────────────────────────────────
    page_text = soup.get_text(" ", strip=True)

    # ── Title ─────────────────────────────────────────────────────────────────
    title_el = soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else ""
    data["Related Source Item"] = title

    # ── Price ─────────────────────────────────────────────────────────────────
    # strong.price contains the actual price text
    price_el = soup.select_one("strong.price")
    if price_el:
        raw_price = price_el.get_text(strip=True)
        # Extract dollar amount: "$1,490,000", "$15,000 WIWO, EOI", etc.
        pm = re.search(r"\$([\d,]+(?:\.\d+)?(?:\s*[MKmk])?)", raw_price)
        if pm:
            data["Price"] = "$" + pm.group(1)
        elif "contact" in raw_price.lower() or "refer" in raw_price.lower():
            data["Price"] = "Contact Seller"
        elif "wanted" in raw_price.lower():
            data["Price"] = "Wanted"
        elif "expression" in raw_price.lower():
            data["Price"] = "Expressions of Interest"
        else:
            data["Price"] = raw_price
    elif "contact seller" in page_text.lower():
        data["Price"] = "Contact Seller"

    # ── Revenue / Profit from page ───────────────────────────────────────────
    # These appear near the price block as "Revenue $X" or "Revenue Ask the Seller"
    rev_text = rx(r"Revenue\s*\$([\d,]+(?:\.\d+)?(?:\s*[MKmk])?)", page_text)
    if rev_text:
        data["Revenue"] = "$" + rev_text

    profit_text = rx(r"Profit\s*\$([\d,]+(?:\.\d+)?(?:\s*[MKmk])?)", page_text)
    if profit_text:
        data["Net Income"] = "$" + profit_text

    # ── Date of Listing ──────────────────────────────────────────────────────
    # span.updated-text → "Last Updated 21 Feb 2026"
    updated_el = soup.select_one("span.updated-text")
    if updated_el:
        date_text = rx(r"Last\s+Updated\s+(\d{1,2}\s+\w+\s+\d{4})", updated_el.get_text(strip=True))
        if date_text:
            parsed = _parse_date_various(date_text)
            if parsed:
                data["Date of Listing"] = parsed.strftime("%d/%m/%Y")

    # Fallback: search page text
    if not data["Date of Listing"]:
        date_text = rx_any([
            r"Last\s+Updated\s+(\d{1,2}\s+\w+\s+\d{4})",
            r"Listed[:\s]+(\d{1,2}\s+\w+\s+\d{4})",
        ], page_text)
        if date_text:
            parsed = _parse_date_various(date_text)
            if parsed:
                data["Date of Listing"] = parsed.strftime("%d/%m/%Y")

    # ── Date filter ─────────────────────────────────────────────────────────
    if data["Date of Listing"] and (_DATE_FROM or _DATE_TO):
        listing_date = _parse_date(data["Date of Listing"])
        if listing_date:
            if _DATE_FROM and listing_date < _DATE_FROM:
                return None  # too old
            if _DATE_TO and listing_date > _DATE_TO:
                return None  # too new

    # ── Location from breadcrumb ─────────────────────────────────────────────
    # Breadcrumb pattern: Business for Sale > {State} > {Region} > {City} > {Category}
    # Location links: /for-sale/{city}-{state}-{postcode}/
    breadcrumb = soup.select_one("ul.breadcrumb") or soup.select_one(".breadcrumb")
    if breadcrumb:
        crumb_links = breadcrumb.select("a")
        crumb_texts = [a.get_text(strip=True) for a in crumb_links]
        crumb_hrefs = [a.get("href", "") for a in crumb_links]

        # Find state from breadcrumb text (e.g. "Western Australia", "New South Wales")
        state_map = {
            "Western Australia": "WA", "New South Wales": "NSW",
            "Victoria": "VIC", "Queensland": "QLD",
            "South Australia": "SA", "Tasmania": "TAS",
            "Northern Territory": "NT", "ACT": "ACT",
        }
        for ct in crumb_texts:
            for full_name, abbrev in state_map.items():
                if ct == full_name or ct == abbrev:
                    data["State"] = abbrev
                    break
            if data["State"]:
                break

        # Also try state from href: /for-sale/wa/, /for-sale/nsw/
        if not data["State"]:
            state_abbrevs = {"wa", "nsw", "vic", "qld", "sa", "tas", "nt", "act"}
            for href in crumb_hrefs:
                m = re.search(r"/for-sale/([a-z]{2,3})/?$", href)
                if m and m.group(1) in state_abbrevs:
                    data["State"] = m.group(1).upper()
                    break

        # Find city/suburb from breadcrumb href: /for-sale/{city}-{state}-{postcode}/
        for href in crumb_hrefs:
            m = re.search(r"/for-sale/([\w-]+)-([a-z]{2,3})-(\d{4})/?", href)
            if m:
                city = m.group(1).replace("-", " ").title()
                data["Suburb"] = city
                data["City"] = city
                if not data["State"]:
                    data["State"] = m.group(2).upper()
                break

        # Fallback: use region name from breadcrumb
        if not data["Suburb"]:
            for ct in crumb_texts:
                if "Region" in ct:
                    data["Suburb"] = ct.replace(" Region", "")
                    data["City"] = data["Suburb"]
                    break

    # ── Status ───────────────────────────────────────────────────────────────
    text_upper = page_text.upper()
    if "SOLD" in text_upper and ("BUSINESS SOLD" in text_upper or "THIS LISTING HAS BEEN SOLD" in text_upper):
        data["On Sale or Not"] = "Sold"
    elif "UNDER OFFER" in text_upper or "UNDER CONTRACT" in text_upper:
        data["On Sale or Not"] = "Under Offer"
    else:
        data["On Sale or Not"] = "Active"

    # ── Description text ───────────────────────────────────────────────────
    # div[itemprop="description"] is present on listing cards;
    # on detail page, look for the About section
    desc = ""
    for selector in ["div[itemprop='description']", ".listing-description",
                     ".about", ".description"]:
        desc_el = soup.select_one(selector)
        if desc_el:
            desc = desc_el.get_text("\n", strip=True)
            if len(desc) > 50:  # skip short snippets
                break
    if not desc or len(desc) < 50:
        # Fallback: use full page text
        desc = page_text
    desc_lower = desc.lower()

    # ── Location Direction ──────────────────────────────────────────────────
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
    loc_dir = rx_any([
        rf"\bin\s+((?:{_DIR_CORE}\s+)+(?:{_AU_REGIONS}))",
        rf"((?:{_DIR_CORE}\s+)+(?:{_AU_REGIONS}))",
        rf"((?:{_DIR_CORE}\s+)+(?:suburbs?|region|area|coast|metro))",
    ], title + " " + desc)
    data["Location Direction"] = loc_dir.strip() if loc_dir else ""

    # ── Leasehold or Freehold ──────────────────────────────────────────────
    if "freehold" in desc_lower:
        data["Leasehold or Freehold"] = "Freehold"
    elif "leasehold" in desc_lower or "lease" in desc_lower:
        data["Leasehold or Freehold"] = "Leasehold"

    # ── Revenue ────────────────────────────────────────────────────────────
    def _parse_money(text: str) -> str:
        m = re.search(r"\$([\d,.]+)\s*([MKmk](?:illion|ILLION)?)?\+?", text, re.IGNORECASE)
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
        for m in re.finditer(keyword, text, re.IGNORECASE):
            start = max(0, m.start() - 60)
            end   = min(len(text), m.end() + 60)
            chunk = text[start:end]
            val = _parse_money(chunk)
            if val:
                return val
        return ""

    if not data["Revenue"]:
        data["Revenue"] = _find_money_near(r"revenue|turnover", desc)

    # ── Net Income (supplement from description if not found in page header)
    if not data["Net Income"]:
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

    # ── Licensed Places (number of approved places) ─────────────────────
    data["Place"] = rx_any([
        r"licensed\s+(?:for\s+)?(\d+)\+?\s+(?:children|places|kids|approved)",
        r"approved\s+for\s+(\d+)\+?\s+(?:children|places)",
        r"(\d+)\+?\s+(?:approved\s+)?places",
        r"capacity\s+(?:of\s+)?(\d+)\+?",
        r"(\d+)[- ]place\s+(?:centre|center|childcare|child\s+care)",
        r"(\d+)\+?\s+(?:licensed\s+)?(?:children|places)\s+(?:centre|center)?",
    ], desc)

    # ── Current Occupancy (percentage) ─────────────────────────────────
    data["Current Occupancy"] = rx_any([
        r"occupancy\s+(?:rate\s+)?(?:of\s+)?(?:approx\.?\s*)?(\d+(?:\.\d+)?)\s*%",
        r"(\d+(?:\.\d+)?)\s*%\s+(?:current\s+)?occupancy",
        r"currently\s+(\d+(?:\.\d+)?)\s*%\s+(?:occupied|full)",
        r"(\d+(?:\.\d+)?)\s*%\s+(?:occupied|full|utilisation|utilization)",
        r"running\s+at\s+(\d+(?:\.\d+)?)\s*%",
        r"at\s+(\d+(?:\.\d+)?)\s*%\s+(?:capacity|occupancy)",
    ], desc)
    if data["Current Occupancy"] and "%" not in data["Current Occupancy"]:
        data["Current Occupancy"] = data["Current Occupancy"] + "%"

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
    ], desc)
    if data["Current Daily Fees"] and not data["Current Daily Fees"].startswith("$"):
        data["Current Daily Fees"] = "$" + data["Current Daily Fees"]

    # ── Daily Fees by Age Group ────────────────────────────────────────────
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

    # ── Rent ───────────────────────────────────────────────────────────────
    data["Rent"] = rx_any([
        r"rent\s+(?:of\s+)?(?:approx\.?\s*)?\$([\d,]+(?:\.\d+)?)(?:\s*(?:per|p\.a\.|pa|annually|a\s+year))?",
        r"\$([\d,]+(?:\.\d+)?)\s*(?:per|p\.a\.|pa)\s+(?:in\s+)?rent",
        r"(?:annual\s+)?rent[:\s]+\$([\d,]+(?:\.\d+)?)",
    ], desc)
    if data["Rent"] and not data["Rent"].startswith("$"):
        data["Rent"] = "$" + data["Rent"]

    # ── Rent per Place ─────────────────────────────────────────────────────
    data["Rent per Place"] = rx_any([
        r"\$([\d,]+(?:\.\d+)?)\s*per\s+place\s+(?:per\s+)?(?:annum|year|pa|p\.a\.)",
        r"rent\s+of\s+approx\.?\s+\$([\d,]+(?:\.\d+)?)\s+per\s+place",
    ], desc)
    if data["Rent per Place"] and not data["Rent per Place"].startswith("$"):
        data["Rent per Place"] = "$" + data["Rent per Place"]

    # ── Length of Lease ───────────────────────────────────────────────────
    data["Length of Lease"] = rx_any([
        r"(\d+[\d\s]*[-+]\d*\s*year(?:s)?\s+(?:lease|term))",
        r"lease\s+(?:term\s+)?(?:of\s+)?(\d+\s+year(?:s)?)",
        r"(\d+)\s+year\s+(?:initial\s+)?lease",
        r"long\s+(\d+\s+year)\s+lease",
        r"lease\s+(?:term)?\s*[:\s]+(\d+\s+years?\s+\+?\s*\d*\s*years?)",
    ], desc)
    if not data["Length of Lease"]:
        data["Length of Lease"] = rx(r"(\d+\s+year[s]?\s+\+\s+\d+\s+year[s]?\s+option)", desc)

    # ── Rent Increases ─────────────────────────────────────────────────────
    data["Rent Increases (Annual)"] = rx_any([
        r"(\d+(?:\.\d+)?)\s*%\s+(?:annual\s+)?(?:rent\s+)?(?:increase|review|CPI)",
        r"(?:annual\s+)?(?:rent\s+)?(?:increase|review)[^\d%]*(\d+(?:\.\d+)?)\s*%",
        r"CPI[^\d]*(\d+(?:\.\d+)?)\s*%",
    ], desc)

    # ── Area sqm ───────────────────────────────────────────────────────────
    data["Area (sqm)"] = rx_any([
        r"(\d[\d,]*)\s*(?:square\s+metres?|sqm|m²|m2)",
    ], desc)

    # ── Near School ────────────────────────────────────────────────────────
    sch = rx_any([
        r"(\d+(?:\.\d+)?)\s*(?:km|m)\s*(?:from|of)?\s*(?:\w+\s+)?school",
        r"school[^.]*?(\d+(?:\.\d+)?)\s*(?:km|m)",
    ], desc)
    data["Near School"] = sch if sch else ""

    # ── Near Supermarket ───────────────────────────────────────────────────
    data["Near Supermarket"] = rx_any([
        r"(\d+(?:\.\d+)?)\s*(?:km|m)\s*(?:from)?\s*supermarket",
        r"supermarket[^.]*?(\d+(?:\.\d+)?)\s*(?:km|m)",
    ], desc)

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
        r"NQS\s+(?:rating\s+(?:of\s+)?|rated\s+)?(exceeding|meeting|working\s+towards)",
        r"rated\s+(exceeding|meeting|working\s+towards)",
        r"(exceeding|meeting)\s+nqs",
    ], desc)
    data["NQS Rating"] = nqs.title() if nqs else ""

    # ── Vehicles Passing Daily ─────────────────────────────────────────────
    data["Vehicles Passing Daily"] = rx_any([
        r"([\d,]+)\s+(?:cars?|vehicles?)\s+(?:passing|pass)\s+(?:daily|per\s+day)",
        r"([\d,]+)\s+(?:vehicles?|cars?)\s+per\s+day",
    ], desc)

    # ── Parking ────────────────────────────────────────────────────────────
    parking = rx_any([
        r"(\d+)\s+(?:car\s+)?(?:parking\s+)?(?:spaces?|bays?|spots?)",
        r"parking\s+(?:for\s+)?(\d+)",
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

    # ── Supply Ratio ───────────────────────────────────────────────────────
    data["Supply Ratio"] = rx_any([
        r"(\d+(?:\.\d+)?)\s*(?:km|km\s+radius)[^\w]*(?:only\s+)?(?:childcare|centre|child\s+care)",
        r"only\s+(?:childcare|centre)\s+within\s+(\d+(?:\.\d+)?)\s*km",
        r"no\s+(?:direct\s+)?competition[^.]*within\s+(\d+(?:\.\d+)?)\s*km",
    ], desc)

    # ── Demographics ───────────────────────────────────────────────────────
    data["# of Students Surrounding"] = rx_any([
        r"(\d[\d,]+)\s+children\s+aged\s+(?:0-4|0-5|under\s+5)",
        r"([\d,]+)\s+children\s+(?:in\s+the\s+area|within)",
    ], desc)

    data["Resident Population"] = rx_any([
        r"population\s+(?:of\s+)?([\d,]+)",
        r"([\d,]+)\s+(?:residents?|people)\s+(?:in\s+the\s+area|within)",
    ], desc)

    data["Population Growth Rate (Per Year)"] = rx(
        r"population\s+(?:growth\s+)?(?:rate\s+)?(?:of\s+)?(\d+(?:\.\d+)?)\s*%\s+(?:per\s+year|annually|p\.a\.)",
        desc
    )

    # ── Additional Places ──────────────────────────────────────────────────
    data["Additional Places to be Added"] = rx_any([
        r"additional\s+(\d+)\s+(?:approved\s+)?places",
        r"(\d+)\s+additional\s+(?:approved\s+)?places",
    ], desc)

    # ── Development ────────────────────────────────────────────────────────
    if re.search(r"(?:housing|residential)\s+(?:estate|development|growth)", desc_lower):
        data["Development"] = rx_any([
            r"(\d+)\s+(?:new\s+)?(?:homes?|lots?|units?)\s+(?:being\s+)?(?:built|developed)",
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
    """Crawl a batch concurrently and extract data."""
    tasks = [crawler.arun(url=item["url"], config=CRAWLER_CFG) for item in batch]
    results_html = await asyncio.gather(*tasks, return_exceptions=True)

    records = []
    date_filtered = []
    for item, res in zip(batch, results_html):
        if isinstance(res, Exception):
            print(f"  ❌ Error {item['url']}: {res}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "BusinessForSale.com.au"
            records.append(rec)
            continue

        if not res.success:
            print(f"  ❌ Failed {item['url']}: {res.error_message}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "BusinessForSale.com.au"
            records.append(rec)
            continue

        try:
            rec = extract(item["url"], res.html)
        except Exception as e:
            print(f"  ⚠️ Extract error {item['url']}: {e}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "BusinessForSale.com.au"

        if rec is None:
            print(f"  ⏭ Filtered (date out of range): {item['url']}")
            date_filtered.append(item["url"])
        else:
            records.append(rec)
    return records, date_filtered


async def main():
    urls_path = "data/listing_urls_businessforsale.json"
    if not os.path.exists(urls_path):
        print(f"❌ {urls_path} not found. Run 02_crawl_all_listings_businessforsale.py first.")
        return

    with open(urls_path, encoding="utf-8") as f:
        listings = json.load(f)

    print("=" * 65)
    print(f"  BusinessForSale.com.au — Extract Detail Pages")
    print(f"  Total listings to process: {len(listings)}")
    if _DATE_FROM or _DATE_TO:
        print(f"  Date filter: {DATE_FROM or '∞'} → {DATE_TO or '∞'}")
    print("=" * 65)

    # Load existing progress
    output_path   = "data/childcare_raw_businessforsale.json"
    filtered_path = "data/date_filtered_urls_businessforsale.json"
    done_urls = set()
    all_records = []

    if os.path.exists(output_path):
        with open(output_path, encoding="utf-8") as f:
            all_records = json.load(f)
        done_urls = {r["URL"] for r in all_records}

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
        remaining, source="businessforsale", log_dir="data"
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
