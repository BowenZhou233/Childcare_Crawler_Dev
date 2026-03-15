#!/usr/bin/env python3
"""
Step 3: For each listing URL, fetch detail page and extract all fields.
Input:  data/listing_urls.json
Output: data/childcare_raw.json  (one dict per listing)

Site: sydneychildcaresales.com.au (WordPress + Elementor)
Field extraction strategy:
  - JSON-LD schema.org → dates (datePublished, dateModified)
  - Page text (Elementor widgets) → regex patterns for all fields
  - Image filename → status hint (sold, under-offer)
  - Empty if not found (never skip the column)
"""

import asyncio
import os
import json
import re
import time
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from bs4 import BeautifulSoup

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

DELAY = 1.5
CONCURRENCY = 3
PROGRESS_SAVE = 10

# ── Date filter ──────────────────────────────────────────────────────────────
DATE_FROM = "01/01/2025"
DATE_TO   = None

# ── All target columns (same as anybusiness/businessforsale) ─────────────────
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


# ── Helpers ──────────────────────────────────────────────────────────────────
def rx(pattern: str, text: str, group: int = 1, flags=re.IGNORECASE) -> str:
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else ""


def rx_any(patterns: list, text: str) -> str:
    for p in patterns:
        v = rx(p, text)
        if v:
            return v
    return ""


def _parse_date(dmy: str):
    from datetime import date as _date
    try:
        d, m, y = dmy.strip().split("/")
        return _date(int(y), int(m), int(d))
    except Exception:
        return None


def _parse_date_various(text: str):
    from datetime import date as _date, datetime
    text = text.strip()
    d = _parse_date(text)
    if d:
        return d
    for fmt in ["%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d-%B-%Y",
                "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d",
                "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%dT%H:%M:%S%z"]:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Try ISO format with timezone
    m = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


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


_DATE_FROM = _parse_date(DATE_FROM) if DATE_FROM else None
_DATE_TO   = _parse_date(DATE_TO)   if DATE_TO   else None


# ── Main extractor ────────────────────────────────────────────────────────────
def extract(url: str, html: str, source_type: str = "") -> dict:
    """
    Extract all fields from a sydneychildcaresales.com.au detail page.

    Site structure (WordPress + Elementor):
      - Title: <h1> or h1.elementor-heading-title
      - Content: .elementor-widget-text-editor paragraphs
      - JSON-LD: datePublished, dateModified
      - No itemprop/microdata for listing fields — all in free text
      - Status: image filename (sold-*, under-offer-*) or page text
    """
    soup = BeautifulSoup(html, "html.parser")
    data = {col: "" for col in COLUMNS}

    data["Data Source"] = "SydneyChildcareSales.com.au"
    data["URL"] = url

    # ── Full page text ───────────────────────────────────────────────────
    page_text = soup.get_text(" ", strip=True)
    page_lower = page_text.lower()

    # ── Title ────────────────────────────────────────────────────────────
    title_el = soup.select_one("h1.elementor-heading-title") or soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else ""
    data["Related Source Item"] = title

    # ── Property ID / Business No ────────────────────────────────────────
    prop_id = rx_any([
        r"Property\s+ID[:\s]+(\d+)",
        r"Ref(?:erence)?\s*(?:No\.?|Number|#)[:\s]+(\d+)",
        r"ID[:\s]+(\d+)",
    ], page_text)
    if not prop_id:
        # Fallback: extract from URL slug
        slug = url.rstrip("/").split("/")[-1]
        prop_id = slug
    data["Business No."] = prop_id

    # ── JSON-LD dates ────────────────────────────────────────────────────
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string)
            # Could be a list or a single object
            if isinstance(ld, list):
                for item in ld:
                    if isinstance(item, dict):
                        if "datePublished" in item:
                            parsed = _parse_date_various(item["datePublished"])
                            if parsed:
                                data["Date of Listing"] = parsed.strftime("%d/%m/%Y")
                        if "dateModified" in item:
                            pass  # We prefer datePublished
            elif isinstance(ld, dict):
                if "@graph" in ld:
                    for item in ld["@graph"]:
                        if isinstance(item, dict) and "datePublished" in item:
                            parsed = _parse_date_various(item["datePublished"])
                            if parsed:
                                data["Date of Listing"] = parsed.strftime("%d/%m/%Y")
                            break
                elif "datePublished" in ld:
                    parsed = _parse_date_various(ld["datePublished"])
                    if parsed:
                        data["Date of Listing"] = parsed.strftime("%d/%m/%Y")
        except (json.JSONDecodeError, TypeError):
            continue

    # ── Date filter ──────────────────────────────────────────────────────
    if data["Date of Listing"] and (_DATE_FROM or _DATE_TO):
        listing_date = _parse_date(data["Date of Listing"])
        if listing_date:
            if _DATE_FROM and listing_date < _DATE_FROM:
                return None
            if _DATE_TO and listing_date > _DATE_TO:
                return None

    # ── Status ───────────────────────────────────────────────────────────
    # Check image filenames for status
    status = ""
    for img in soup.find_all("img", src=True):
        img_name = img["src"].split("/")[-1].lower()
        if "sold" in img_name:
            status = "Sold"
            break
        elif "under-offer" in img_name or "under-contract" in img_name:
            status = "Under Offer"
            break

    # Also check page text
    if not status:
        text_upper = page_text.upper()
        if "SOLD" in text_upper:
            status = "Sold"
        elif "UNDER OFFER" in text_upper or "UNDER CONTRACT" in text_upper:
            status = "Under Offer"

    # Fallback to source_type from gallery
    if not status:
        if source_type == "sold":
            status = "Sold"
        else:
            status = "Active"

    data["On Sale or Not"] = status

    # ── Description text ─────────────────────────────────────────────────
    # Collect text from Elementor text widgets (main content area)
    desc_parts = []
    for widget in soup.select(".elementor-widget-text-editor"):
        txt = widget.get_text("\n", strip=True)
        if len(txt) > 20:
            desc_parts.append(txt)

    desc = "\n".join(desc_parts) if desc_parts else page_text
    desc_lower = desc.lower()

    # ── Price ────────────────────────────────────────────────────────────
    price = rx_any([
        r"Price[:\s]+\$([\d,]+(?:\.\d+)?(?:\s*[MKmk](?:illion)?)?)",
        r"Asking\s+Price[:\s]+\$([\d,]+(?:\.\d+)?(?:\s*[MKmk](?:illion)?)?)",
        r"Sale\s+Price[:\s]+\$([\d,]+(?:\.\d+)?(?:\s*[MKmk](?:illion)?)?)",
    ], desc)
    if price:
        data["Price"] = "$" + price
    elif re.search(r"expression[s]?\s+of\s+interest|EOI", desc, re.IGNORECASE):
        data["Price"] = "Expressions of Interest"
    elif re.search(r"contact\s+(?:us|agent|seller)", desc, re.IGNORECASE):
        data["Price"] = "Contact Seller"
    else:
        # Try to find any dollar amount near "price"
        price_money = _find_money_near(r"price", desc)
        if price_money:
            data["Price"] = price_money

    # ── Location ─────────────────────────────────────────────────────────
    location = rx_any([
        r"Location[:\s]+([^\n]+?)(?:\s*$|\n)",
        r"(?:in|at)\s+(\w[\w\s]+?),?\s+(?:NSW|Sydney)",
    ], desc)
    if location:
        data["Suburb"] = location.strip().rstrip(",. ")
        data["City"] = data["Suburb"]

    # State: this site focuses on Sydney/NSW
    if re.search(r"NSW|New South Wales|Sydney", page_text, re.IGNORECASE):
        data["State"] = "NSW"
    elif re.search(r"QLD|Queensland", page_text, re.IGNORECASE):
        data["State"] = "QLD"
    elif re.search(r"VIC|Victoria|Melbourne", page_text, re.IGNORECASE):
        data["State"] = "VIC"

    # Also parse location from title (e.g. "Leasehold Centre For Sale - Parramatta Area")
    if not data["Suburb"]:
        # Try to get location from title after last dash
        if " - " in title or " – " in title:
            parts = re.split(r"\s*[-–]\s*", title)
            if len(parts) >= 2:
                loc_part = parts[-1].strip()
                # Filter out generic words
                if not re.match(r"(?:for\s+sale|sold|under|freehold|leasehold)", loc_part, re.IGNORECASE):
                    data["Suburb"] = loc_part
                    data["City"] = loc_part

    # ── Location Direction ───────────────────────────────────────────────
    _DIR_CORE = (
        r"(?:inner|outer|far|mid|central|upper|lower|"
        r"north(?:ern)?|south(?:ern)?|east(?:ern)?|west(?:ern)?)"
        r"(?:[- ](?:west(?:ern)?|east(?:ern)?|north(?:ern)?|south(?:ern)?))?"
    )
    loc_dir = rx_any([
        rf"({_DIR_CORE}\s+(?:Sydney|NSW|suburbs?|region|area|coast|shore))",
        rf"(?:in|of)\s+({_DIR_CORE}\s+\w+)",
    ], title + " " + desc)
    data["Location Direction"] = loc_dir.strip() if loc_dir else ""

    # ── Leasehold or Freehold ────────────────────────────────────────────
    if "freehold" in desc_lower or "freehold" in title.lower():
        data["Leasehold or Freehold"] = "Freehold"
    elif "leasehold" in desc_lower or "leasehold" in title.lower() or "lease" in desc_lower:
        data["Leasehold or Freehold"] = "Leasehold"
    data["Site"] = data["Leasehold or Freehold"]

    # ── Licensed Places ──────────────────────────────────────────────────
    data["Place"] = rx_any([
        r"(?:Service\s+)?Approval\s+(?:Places|for)[:\s]+(\d+)\+?\s*(?:Places|children)?",
        r"licensed\s+(?:for\s+)?(\d+)\+?\s+(?:children|places|kids|approved)",
        r"approved\s+(?:for\s+)?(\d+)\+?\s+(?:children|places)",
        r"(\d+)\+?\s+(?:approved\s+)?places",
        r"capacity\s+(?:of\s+)?(\d+)\+?",
        r"(\d+)[- ]place\s+(?:centre|center|childcare|child\s+care|service)",
        r"Places[:\s]+(\d+)",
    ], desc)

    # ── Current Occupancy ────────────────────────────────────────────────
    occ = rx_any([
        r"occupancy[:\s]+(?:approx\.?\s*)?(\d+(?:[–\-]\d+)?(?:\.\d+)?)\s*%",
        r"(\d+(?:[–\-]\d+)?(?:\.\d+)?)\s*%\s+(?:current\s+)?occupancy",
        r"currently\s+(\d+(?:\.\d+)?)\s*%\s+(?:occupied|full)",
        r"running\s+at\s+(\d+(?:\.\d+)?)\s*%",
        r"FY\d{4}\s+Occupancy[:\s]+(\d+(?:\.\d+)?)\s*%",
    ], desc)
    if occ:
        data["Current Occupancy"] = occ + "%" if "%" not in occ else occ

    # ── Revenue / Turnover ───────────────────────────────────────────────
    rev = rx_any([
        r"(?:FY\d{4}\s+)?Revenue[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
        r"(?:FY\d{4}\s+)?Turnover[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
        r"Revenue[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
    ], desc)
    if rev:
        data["Revenue"] = "$" + rev
    else:
        data["Revenue"] = _find_money_near(r"revenue|turnover", desc)

    # ── Net Income / Profit ──────────────────────────────────────────────
    ni = rx_any([
        r"(?:Net\s+)?Profit[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
        r"Net\s+Income[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
        r"EBITDA[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
    ], desc)
    if ni:
        data["Net Income"] = "$" + ni
    else:
        data["Net Income"] = _find_money_near(r"net\s+(?:profit|income)|EBITDA|profit", desc)

    # ── EBITDA ───────────────────────────────────────────────────────────
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

    # ── Rent ─────────────────────────────────────────────────────────────
    data["Rent"] = rx_any([
        r"Rent[:\s]+(?:approx\.?\s*)?\$([\d,]+(?:\.\d+)?)",
        r"rent\s+(?:of\s+)?(?:approx\.?\s*)?\$([\d,]+(?:\.\d+)?)",
        r"\$([\d,]+(?:\.\d+)?)\s*(?:per|p\.a\.|pa)\s+(?:in\s+)?rent",
    ], desc)
    if data["Rent"] and not data["Rent"].startswith("$"):
        data["Rent"] = "$" + data["Rent"]

    # ── Rent per Place ───────────────────────────────────────────────────
    data["Rent per Place"] = rx_any([
        r"\$([\d,]+(?:\.\d+)?)\s*per\s+place",
        r"rent\s+of\s+approx\.?\s+\$([\d,]+(?:\.\d+)?)\s+per\s+place",
    ], desc)
    if data["Rent per Place"] and not data["Rent per Place"].startswith("$"):
        data["Rent per Place"] = "$" + data["Rent per Place"]

    # ── Length of Lease ──────────────────────────────────────────────────
    data["Length of Lease"] = rx_any([
        r"(?:New\s+)?Lease[:\s]+(?:to\s+be\s+negotiated\s*[-–]\s*)?(\d+\s*[xX×]\s*\d+(?:\s*[xX×]\s*\d+)?)",
        r"(\d+\s*[xX×]\s*\d+(?:\s*[xX×]\s*\d+)?)\s+(?:lease|year)",
        r"(\d+[\d\s]*[-+]\d*\s*year[s]?\s+(?:lease|term))",
        r"lease\s+(?:term\s+)?(?:of\s+)?(\d+\s+year[s]?)",
        r"(\d+)\s+year\s+(?:initial\s+)?lease",
        r"lease\s+(?:term)?\s*[:\s]+(\d+\s+years?\s+\+?\s*\d*\s*years?)",
    ], desc)

    # ── Rent Increases ───────────────────────────────────────────────────
    data["Rent Increases (Annual)"] = rx_any([
        r"(\d+(?:\.\d+)?)\s*%\s+(?:annual\s+)?(?:rent\s+)?(?:increase|review|CPI)",
        r"(?:annual\s+)?(?:rent\s+)?(?:increase|review)[^\d%]*(\d+(?:\.\d+)?)\s*%",
        r"CPI[^\d]*(\d+(?:\.\d+)?)\s*%",
    ], desc)

    # ── Area sqm ─────────────────────────────────────────────────────────
    data["Area (sqm)"] = rx_any([
        r"(?:Land\s+)?Area[:\s]+(?:approx\.?\s*)?(\d[\d,]*)\s*(?:square\s+metres?|sqm|m²|m2)",
        r"(\d[\d,]*)\s*(?:square\s+metres?|sqm|m²|m2)\s+(?:approx)?",
    ], desc)

    # ── Daily Fees ───────────────────────────────────────────────────────
    data["Current Daily Fees"] = rx_any([
        r"(?:daily\s+)?fees?[:\s]+(?:from\s+)?\$([\d,]+(?:\.\d+)?)",
        r"\$([\d,]+(?:\.\d+)?)\s*(?:/|per)\s*(?:child\s+)?(?:per\s+)?day",
        r"daily\s+(?:fee|fees)\s+of\s+\$?([\d,]+(?:\.\d+)?)",
    ], desc)
    if data["Current Daily Fees"] and not data["Current Daily Fees"].startswith("$"):
        data["Current Daily Fees"] = "$" + data["Current Daily Fees"]

    # ── Daily Fees by Age Group ──────────────────────────────────────────
    for age_range, col_name in [("0-2", "Daily Fee (0-2)"),
                                ("2-3", "Daily Fee (2-3)"),
                                ("3-5", "Daily Fee (3-5)")]:
        age_rx = age_range.replace("-", r"[–\-]")
        v = rx(
            rf"\$(\d+(?:\.\d+)?)[^A-Za-z]*(?:for\s+)?(?:children\s+)?(?:aged?\s+)?{age_rx}",
            desc
        ) or rx(
            rf"{age_rx}[^A-Za-z$]*\$(\d+(?:\.\d+)?)",
            desc
        )
        if v and not data[col_name]:
            data[col_name] = "$" + v

    # ── Near School ──────────────────────────────────────────────────────
    sch = rx_any([
        r"(\d+(?:\.\d+)?)\s*(?:km|m)\s*(?:from|of)?\s*(?:\w+\s+)?school",
        r"school[^.]*?(\d+(?:\.\d+)?)\s*(?:km|m)",
    ], desc)
    data["Near School"] = sch if sch else ""

    # ── Near Supermarket ─────────────────────────────────────────────────
    data["Near Supermarket"] = rx_any([
        r"(\d+(?:\.\d+)?)\s*(?:km|m)\s*(?:from)?\s*supermarket",
    ], desc)

    # ── Renovation / Fitout ──────────────────────────────────────────────
    if re.search(r"renovate?d?|refurb|upgrade|new\s+build|purpose.built|brand.new", desc_lower):
        data["Renovation"] = "Yes"
    if re.search(r"fitout|fit.out|fit\s+out|furnished|fully\s+equipped", desc_lower):
        data["Fitout"] = "Yes"

    # ── NQS Rating ───────────────────────────────────────────────────────
    nqs = rx_any([
        r"(exceeding)\s+(?:NQS|national\s+quality)",
        r"(meeting)\s+(?:NQS|national\s+quality)",
        r"(working\s+towards)\s+(?:NQS|national\s+quality)",
        r"NQS\s+(?:rating\s+(?:of\s+)?|rated\s+)?(exceeding|meeting|working\s+towards)",
        r"rated\s+(exceeding|meeting|working\s+towards)",
        r"(exceeding|meeting)\s+nqs",
    ], desc)
    data["NQS Rating"] = nqs.title() if nqs else ""

    # ── Parking ──────────────────────────────────────────────────────────
    parking = rx_any([
        r"(\d+)\s+(?:car\s+)?(?:parking\s+)?(?:spaces?|bays?|spots?)",
        r"parking\s+(?:for\s+)?(\d+)",
    ], desc)
    if parking:
        data["Parking Volume"] = parking + " spaces"
    elif re.search(r"onsite\s+(?:car\s+)?park|parking\s+available|off-street\s+parking", desc_lower):
        data["Parking Volume"] = "Yes"

    # ── Vehicles Passing Daily ───────────────────────────────────────────
    data["Vehicles Passing Daily"] = rx_any([
        r"([\d,]+)\s+(?:cars?|vehicles?)\s+(?:passing|pass)\s+(?:daily|per\s+day)",
    ], desc)

    # ── Waiting List ─────────────────────────────────────────────────────
    if re.search(r"waiting\s+list|waitlist|wait\s+list", desc_lower):
        wl = rx(r"waiting\s+list\s+of\s+(\d+)", desc_lower) or \
             rx(r"(\d+)\s+(?:on\s+)?waiting\s+list", desc_lower) or "Yes"
        data["Waiting List"] = wl
    else:
        data["Waiting List"] = "No"

    # ── Supply Ratio ─────────────────────────────────────────────────────
    data["Supply Ratio"] = rx_any([
        r"Population\s+0[-–]4\s+per\s+LDC[^:]*[:\s]+([\d.]+)",
        r"supply\s+ratio[:\s]+([\d.]+)",
        r"demand\s+ratio[:\s]+([\d.]+)",
    ], desc)

    # ── Demographics ─────────────────────────────────────────────────────
    data["# of Students Surrounding"] = rx_any([
        r"(\d[\d,]+)\s+children\s+aged\s+(?:0-4|0-5|under\s+5)",
        r"([\d,]+)\s+children\s+(?:in\s+the\s+area|within)",
    ], desc)

    data["Resident Population"] = rx_any([
        r"population\s+(?:of\s+)?([\d,]+)",
        r"([\d,]+)\s+(?:residents?|people)\s+(?:in\s+the\s+area|within)",
    ], desc)

    data["Population Growth Rate (Per Year)"] = rx(
        r"population\s+(?:growth\s+)?(?:rate\s+)?(?:of\s+)?(\d+(?:\.\d+)?)\s*%",
        desc
    )

    # ── Additional Places ────────────────────────────────────────────────
    data["Additional Places to be Added"] = rx_any([
        r"additional\s+(\d+)\s+(?:approved\s+)?places",
        r"(\d+)\s+additional\s+(?:approved\s+)?places",
        r"potential\s+to\s+(?:add|expand)\s+(?:to\s+)?(\d+)",
    ], desc)

    # ── Development ──────────────────────────────────────────────────────
    if re.search(r"(?:housing|residential)\s+(?:estate|development|growth)", desc_lower):
        data["Development"] = rx_any([
            r"(\d+)\s+(?:new\s+)?(?:homes?|lots?|units?)",
        ], desc) or "Yes"

    # ── Government Funding ───────────────────────────────────────────────
    if re.search(r"funded\s+kinder|government\s+funding|ccs|childcare\s+subsidy|ccs\s+approved", desc_lower):
        data["Government Funding"] = "Yes"

    # ── Land Tax Free ────────────────────────────────────────────────────
    if re.search(r"land\s+tax\s+free|exempt\s+from\s+land\s+tax", desc_lower):
        data["Land Tax Free"] = "Yes"

    # ── Net Income / Price ratio ─────────────────────────────────────────
    if data["Net Income"] and data["Price"] and data["Price"].startswith("$"):
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

    # ── Rent % Revenue ───────────────────────────────────────────────────
    if data["Rent"] and data["Revenue"]:
        try:
            def parse_money2(s):
                s = re.sub(r"[,$\s]", "", s)
                if s.upper().endswith("M"):
                    return float(s[:-1]) * 1_000_000
                if s.upper().endswith("K"):
                    return float(s[:-1]) * 1_000
                return float(s)
            rent_val = parse_money2(data["Rent"])
            rev_val  = parse_money2(data["Revenue"])
            if rev_val > 0:
                data["Rent % Revenue"] = f"{rent_val / rev_val:.1%}"
        except Exception:
            pass

    return data


# ── Async crawler loop ────────────────────────────────────────────────────────
async def process_batch(crawler, batch: list[dict]) -> tuple[list[dict], list[str]]:
    tasks = [crawler.arun(url=item["url"], config=CRAWLER_CFG) for item in batch]
    results_html = await asyncio.gather(*tasks, return_exceptions=True)

    records = []
    date_filtered = []
    for item, res in zip(batch, results_html):
        if isinstance(res, Exception):
            print(f"  ERROR {item['url']}: {res}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "SydneyChildcareSales.com.au"
            records.append(rec)
            continue

        if not res.success:
            print(f"  FAILED {item['url']}: {res.error_message}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "SydneyChildcareSales.com.au"
            records.append(rec)
            continue

        try:
            source_type = item.get("source_type", "")
            rec = extract(item["url"], res.html, source_type)
        except Exception as e:
            print(f"  Extract error {item['url']}: {e}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "SydneyChildcareSales.com.au"

        if rec is None:
            print(f"  Filtered (date out of range): {item['url']}")
            date_filtered.append(item["url"])
        else:
            records.append(rec)
    return records, date_filtered


async def main():
    urls_path = "data/listing_urls.json"
    if not os.path.exists(urls_path):
        print(f"ERROR: {urls_path} not found. Run 02_crawl_all_listings.py first.")
        return

    with open(urls_path, encoding="utf-8") as f:
        listings = json.load(f)

    print("=" * 65)
    print(f"  SydneyChildcareSales.com.au - Extract Detail Pages")
    print(f"  Total listings to process: {len(listings)}")
    if _DATE_FROM or _DATE_TO:
        print(f"  Date filter: {DATE_FROM or 'any'} -> {DATE_TO or 'any'}")
    print("=" * 65)

    # Load existing progress
    output_path   = "data/childcare_raw.json"
    filtered_path = "data/date_filtered_urls.json"
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
    print(f"  Remaining: {len(remaining)}")

    async with AsyncWebCrawler(config=BROWSER_CFG) as crawler:
        for i in range(0, len(remaining), CONCURRENCY):
            batch = remaining[i : i + CONCURRENCY]
            print(f"\n[{i+1}-{min(i+CONCURRENCY, len(remaining))}/{len(remaining)}] Processing...")
            for item in batch:
                print(f"  -> {item['url']}")

            records, date_filtered = await process_batch(crawler, batch)
            all_records.extend(records)
            all_filtered_urls.extend(date_filtered)

            for rec in records:
                status = rec.get("On Sale or Not", "?")
                price  = rec.get("Price", "N/A")
                bus_no = rec.get("Business No.", "?")
                title  = rec.get("Related Source Item", "")[:50]
                print(f"  OK #{bus_no} | {status} | {price} | {title}")

            # Save progress periodically
            if (i // CONCURRENCY + 1) % (PROGRESS_SAVE // CONCURRENCY + 1) == 0:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(all_records, f, indent=2, ensure_ascii=False)
                with open(filtered_path, "w", encoding="utf-8") as f:
                    json.dump(all_filtered_urls, f, indent=2, ensure_ascii=False)
                print(f"  Progress saved ({len(all_records)} records, "
                      f"{len(all_filtered_urls)} filtered)")

            await asyncio.sleep(DELAY)

    # Final save
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_records, f, indent=2, ensure_ascii=False)
    with open(filtered_path, "w", encoding="utf-8") as f:
        json.dump(all_filtered_urls, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 65)
    print(f"  DONE: {len(all_records)} records kept -> {output_path}")
    if all_filtered_urls:
        print(f"  Date-filtered (skipped): {len(all_filtered_urls)} -> {filtered_path}")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(main())
