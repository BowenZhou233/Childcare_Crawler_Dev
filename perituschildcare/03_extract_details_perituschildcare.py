#!/usr/bin/env python3
"""
Step 3: For each listing, fetch content via WP REST API and extract all fields.
Input:  data/listing_urls_perituschildcare.json
Output: data/childcare_raw_perituschildcare.json  (one dict per listing)

Site: perituschildcare.com.au (WordPress + Uncode theme)
Data source: WP REST API content.rendered + title.rendered
Field extraction strategy:
  - Title parsed for structured fields (Places, Daily Fee, Lease, Location, etc.)
  - content.rendered HTML → BeautifulSoup → regex patterns for all fields
  - Empty if not found (never skip the column)
"""

import os
import json
import re
import sys
import time
import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dedup import DedupChecker

os.makedirs("data", exist_ok=True)

API_URL = "https://perituschildcare.com.au/wp-json/wp/v2/posts"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

DELAY = 1.0
PROGRESS_SAVE = 10

# ── Date filter ──────────────────────────────────────────────────────────────
DATE_FROM = "01/01/2024"
DATE_TO   = None

# ── All target columns (same as anybusiness/businessforsale/sydneychildcaresales) ─
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
                "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S"]:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
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


def _parse_money_value(s: str) -> float:
    """Parse money string to float value."""
    s = re.sub(r"[,$\s]", "", s)
    if s.upper().endswith("M") or s.upper().endswith("MILLION"):
        return float(re.sub(r"[A-Za-z]", "", s)) * 1_000_000
    if s.upper().endswith("K"):
        return float(s[:-1]) * 1_000
    return float(s)


_DATE_FROM = _parse_date(DATE_FROM) if DATE_FROM else None
_DATE_TO   = _parse_date(DATE_TO)   if DATE_TO   else None


# ── Title parser ─────────────────────────────────────────────────────────────
def parse_title_fields(title: str) -> dict:
    """
    Peritus titles are structured with || separators, e.g.:
    "FOR SALE || Leasehold (Business Sale) || Kareela || 75 Place Centre || $164 Avg Daily Fee || 87% Avg Occupancy || 19 Year Lease"
    """
    fields = {}
    parts = [p.strip() for p in title.split("||")]

    for part in parts:
        part_lower = part.lower()

        # Status
        if part_lower.startswith("sold") or part_lower == "sold":
            fields["status"] = "Sold"
        elif part_lower.startswith("leased"):
            fields["status"] = "Sold"  # Treat LEASED as Sold
        elif part_lower.startswith("under contract"):
            fields["status"] = "Under Contract"
        elif part_lower.startswith("for sale"):
            fields["status"] = "Active"
        elif part_lower.startswith("for lease"):
            fields["status"] = "Active"

        # Leasehold/Freehold
        if "leasehold" in part_lower:
            fields["tenure"] = "Leasehold"
        elif "freehold" in part_lower:
            fields["tenure"] = "Freehold"

        # Places
        m = re.search(r"(\d+)\s+place", part, re.IGNORECASE)
        if m:
            fields["places"] = m.group(1)

        # Daily fee
        m = re.search(r"\$(\d+(?:\.\d+)?)\s+(?:avg\s+)?daily\s+fee", part, re.IGNORECASE)
        if m:
            fields["daily_fee"] = "$" + m.group(1)

        # ADR (Average Daily Rate)
        m = re.search(r"\$(\d+(?:\.\d+)?)\s+ADR", part, re.IGNORECASE)
        if m:
            fields["daily_fee"] = "$" + m.group(1)

        # Occupancy
        m = re.search(r"(\d+(?:\.\d+)?)\s*%\s+(?:avg\s+)?occupancy", part, re.IGNORECASE)
        if m:
            fields["occupancy"] = m.group(1) + "%"

        # Lease term
        m = re.search(r"(\d+)\s+year\s+lease", part, re.IGNORECASE)
        if m:
            fields["lease_years"] = m.group(1) + " Year Lease"

        # Per place rent
        m = re.search(r"\$([\d,]+)\s+per\s+place\s+rent", part, re.IGNORECASE)
        if m:
            fields["rent_per_place"] = "$" + m.group(1)

        # Net profit in title
        m = re.search(r"\$([\d,]+(?:K|k)?)\s+(?:FY\d{2}\s+)?net\s+profit", part, re.IGNORECASE)
        if m:
            fields["net_profit"] = "$" + m.group(1)

        # Price in title
        m = re.search(r"For\s+Sale\s+\$([\d,]+)", part, re.IGNORECASE)
        if m:
            fields["price"] = "$" + m.group(1)

        # Location — a part that is a single word or short location name
        # (not matched by other patterns above)

    # Try to find location: look for suburb name in parts
    # Location is typically after the status/tenure parts and before metrics
    for part in parts:
        part_stripped = part.strip()
        # Skip known non-location patterns
        if re.match(r"(?:SOLD|LEASED|FOR SALE|FOR LEASE|UNDER CONTRACT|Leasehold|Freehold|\$|\d+\s+Place|\d+%|\d+\s+Year)", part_stripped, re.IGNORECASE):
            continue
        if re.search(r"daily\s+fee|ADR|occupancy|rent|net\s+profit|turn.key|lease\s+term|per\s+place|business\s+sale|interest", part_stripped, re.IGNORECASE):
            continue
        # Likely a location
        if len(part_stripped) > 1 and len(part_stripped) < 60:
            # Could have extra info like "Within Westfield Penrith"
            loc = re.sub(r"(?:NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\s*$", "", part_stripped).strip()
            if loc and "location" not in fields:
                fields["location"] = loc

    return fields


# ── Main extractor ────────────────────────────────────────────────────────────
def extract(post_data: dict, html_content: str) -> dict:
    """
    Extract all fields from a perituschildcare.com.au listing.

    Uses both:
    - post_data: WP REST API metadata (title, date, categories, url)
    - html_content: content.rendered HTML for detailed field extraction
    """
    soup = BeautifulSoup(html_content, "html.parser")
    data = {col: "" for col in COLUMNS}

    data["Data Source"] = "PeritusChildcare.com.au"
    url = post_data.get("url", "")
    data["URL"] = url

    # ── Title ────────────────────────────────────────────────────────────
    title = post_data.get("title", "")
    data["Related Source Item"] = title

    # Parse structured title fields
    title_fields = parse_title_fields(title)

    # ── Full page text ───────────────────────────────────────────────────
    page_text = soup.get_text(" ", strip=True)
    desc = page_text
    desc_lower = desc.lower()

    # ── Business No / ID ─────────────────────────────────────────────────
    data["Business No."] = str(post_data.get("id", ""))

    # ── Date of Listing ──────────────────────────────────────────────────
    date_str = post_data.get("date", "")
    if date_str:
        parsed = _parse_date_various(date_str)
        if parsed:
            data["Date of Listing"] = parsed.strftime("%d/%m/%Y")

    # ── Date filter ──────────────────────────────────────────────────────
    if data["Date of Listing"] and (_DATE_FROM or _DATE_TO):
        listing_date = _parse_date(data["Date of Listing"])
        if listing_date:
            if _DATE_FROM and listing_date < _DATE_FROM:
                return None
            if _DATE_TO and listing_date > _DATE_TO:
                return None

    # ── Status ───────────────────────────────────────────────────────────
    source_type = post_data.get("source_type", "")
    status = title_fields.get("status", "")
    if not status:
        if source_type == "sold":
            status = "Sold"
        elif source_type == "under-contract":
            status = "Under Contract"
        else:
            status = "Active"
    data["On Sale or Not"] = status

    # ── Location ─────────────────────────────────────────────────────────
    location = title_fields.get("location", "")
    if location:
        # Clean up: remove "Within Westfield" etc.
        loc_clean = re.sub(r"^(?:Within\s+\w+\s+)?", "", location).strip()
        data["Suburb"] = loc_clean
        data["City"] = loc_clean

    # Also try from content
    if not data["Suburb"]:
        loc = rx_any([
            r"Location[:\s]+([^\n<]+?)(?:\s*$|\n|<)",
            r"(?:located\s+in|situated\s+in|in\s+the\s+suburb\s+of)\s+(\w[\w\s]+?)(?:\s*,|\s*\.|$)",
        ], desc)
        if loc:
            data["Suburb"] = loc.strip().rstrip(",. ")
            data["City"] = data["Suburb"]

    # State detection
    state = ""
    if re.search(r"\bNSW\b|New South Wales", desc, re.IGNORECASE):
        state = "NSW"
    elif re.search(r"\bVIC\b|Victoria", desc, re.IGNORECASE):
        state = "VIC"
    elif re.search(r"\bQLD\b|Queensland", desc, re.IGNORECASE):
        state = "QLD"
    elif re.search(r"\bSA\b|South Australia", desc, re.IGNORECASE):
        state = "SA"
    elif re.search(r"\bWA\b|Western Australia", desc, re.IGNORECASE):
        state = "WA"
    elif re.search(r"\bACT\b", desc, re.IGNORECASE):
        state = "ACT"
    # Also check title
    if not state:
        if re.search(r"\bNSW\b", title):
            state = "NSW"
        elif re.search(r"\bVIC\b", title):
            state = "VIC"
    data["State"] = state

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
    tenure = title_fields.get("tenure", "")
    if not tenure:
        if "freehold" in desc_lower:
            tenure = "Freehold"
        elif "leasehold" in desc_lower or "lease" in desc_lower:
            tenure = "Leasehold"
    data["Leasehold or Freehold"] = tenure
    data["Site"] = tenure

    # ── Price ────────────────────────────────────────────────────────────
    price = title_fields.get("price", "")
    if not price:
        price_str = rx_any([
            r"(?:Asking\s+)?Price[:\s]+\$([\d,]+(?:\.\d+)?(?:\s*[MKmk](?:illion)?)?)",
            r"Sale\s+Price[:\s]+\$([\d,]+(?:\.\d+)?(?:\s*[MKmk](?:illion)?)?)",
            r"For\s+Sale\s+\$([\d,]+(?:\.\d+)?)",
        ], desc)
        if price_str:
            price = "$" + price_str
    if not price:
        if re.search(r"expression[s]?\s+of\s+interest|EOI", desc, re.IGNORECASE):
            price = "Expressions of Interest"
        elif re.search(r"contact\s+(?:us|agent|seller)", desc, re.IGNORECASE):
            price = "Contact Seller"
        else:
            price_money = _find_money_near(r"price", desc)
            if price_money:
                price = price_money
    data["Price"] = price

    # ── Licensed Places ──────────────────────────────────────────────────
    places = title_fields.get("places", "")
    if not places:
        places = rx_any([
            r"(?:Service\s+)?Approval\s+(?:Places|for)[:\s]+(\d+)\+?\s*(?:Places|children)?",
            r"licensed\s+(?:for\s+)?(\d+)\+?\s+(?:children|places|kids|approved)",
            r"approved\s+(?:for\s+)?(\d+)\+?\s+(?:children|places)",
            r"(\d+)\+?\s+(?:approved\s+)?places",
            r"capacity\s+(?:of\s+)?(\d+)\+?",
            r"(\d+)[- ]place\s+(?:centre|center|childcare|child\s+care|service|ELC|early\s+learning)",
            r"(\d+)\s*[- ](?:place|room)\s+(?:centre|center)",
            r"Places[:\s]+(\d+)",
        ], desc)
    data["Place"] = places

    # ── Current Occupancy ────────────────────────────────────────────────
    occ = title_fields.get("occupancy", "")
    if not occ:
        occ = rx_any([
            r"(?:FY\d{2,4}\s+)?(?:average\s+)?(?:annual\s+)?occupancy[:\s]+(?:approx\.?\s*)?(\d+(?:[–\-]\d+)?(?:\.\d+)?)\s*%",
            r"(\d+(?:[–\-]\d+)?(?:\.\d+)?)\s*%\s+(?:average\s+)?(?:annual\s+)?(?:current\s+)?(?:spot\s+)?occupancy",
            r"currently\s+(\d+(?:\.\d+)?)\s*%\s+(?:occupied|full)",
            r"running\s+at\s+(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s*%\s+(?:avg\s+)?occupancy",
        ], desc)
    if occ and "%" not in occ:
        occ = occ + "%"
    data["Current Occupancy"] = occ

    # ── Revenue / Turnover ───────────────────────────────────────────────
    rev = rx_any([
        r"(?:FY\d{2,4}\s+)?Revenue[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
        r"(?:FY\d{2,4}\s+)?Turnover[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
        r"Revenue[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
    ], desc)
    if rev:
        data["Revenue"] = "$" + rev
    else:
        data["Revenue"] = _find_money_near(r"revenue|turnover", desc)

    # ── Net Income / Profit ──────────────────────────────────────────────
    ni = title_fields.get("net_profit", "")
    if not ni:
        ni_str = rx_any([
            r"(?:FY\d{2,4}\s+)?(?:Actual\s+)?(?:Adjusted\s+)?(?:Net\s+)?Profit[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
            r"(?:Net\s+)?Income[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
            r"(?:Forecast\s+)?(?:FY\d{2,4}\s+)?(?:Adjusted\s+)?EBITDA[:\s]+(?:~?\s*)?\$([\d,.]+(?:\s*[MKmk](?:illion)?)?)",
        ], desc)
        if ni_str:
            ni = "$" + ni_str
        else:
            ni = _find_money_near(r"net\s+(?:profit|income)|EBITDA|profit", desc)
    data["Net Income"] = ni

    # ── EBITDA breakdown ─────────────────────────────────────────────────
    ebitda_matches = re.findall(
        r"(?:EBITDA|ebitda)[^$\n]*\$([\d,.]+(?:[MKmk](?:illion)?)?)", desc, re.IGNORECASE
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

    # ── Current EBITDA (first match) ─────────────────────────────────────
    if ebitda_matches:
        data["Current EBITDA"] = "$" + ebitda_matches[0]

    # ── Rent ─────────────────────────────────────────────────────────────
    rent = rx_any([
        r"(?:Annual\s+)?(?:Base\s+)?Rent(?:al)?[:\s]+(?:approx\.?\s*)?\$([\d,]+(?:\.\d+)?)",
        r"rent\s+(?:of\s+)?(?:approx\.?\s*)?\$([\d,]+(?:\.\d+)?)",
        r"\$([\d,]+(?:\.\d+)?)\s*(?:per|p\.a\.|pa)\s+(?:in\s+)?rent",
    ], desc)
    if rent:
        data["Rent"] = "$" + rent

    # ── Rent per Place ───────────────────────────────────────────────────
    rpp = title_fields.get("rent_per_place", "")
    if not rpp:
        rpp_str = rx_any([
            r"\$([\d,]+(?:\.\d+)?)\s+per\s+place",
            r"rent\s+(?:per\s+place|/\s*place)[:\s]+\$([\d,]+(?:\.\d+)?)",
            r"\$([\d,]+)\s+per\s+place\s+rent",
        ], desc)
        if rpp_str:
            rpp = "$" + rpp_str
    data["Rent per Place"] = rpp

    # ── Length of Lease ──────────────────────────────────────────────────
    lease = title_fields.get("lease_years", "")
    if not lease:
        lease = rx_any([
            r"(\d+\s*[xX×]\s*\d+(?:\s*[xX×]\s*\d+)?)\s*(?:year)?\s*(?:lease|term)",
            r"(\d+[\d\s]*[-+]\d*\s*year[s]?\s+(?:lease|term))",
            r"(\d+)\s*[- ]year\s+(?:secured\s+)?lease",
            r"lease\s+(?:term\s+)?(?:of\s+)?(\d+\s+year[s]?)",
            r"(\d+)\s+year\s+(?:initial\s+)?(?:secured\s+)?lease",
            r"(\d+)\s+year[s]?\s+remaining",
        ], desc)
    data["Length of Lease"] = lease

    # ── Rent Increases ───────────────────────────────────────────────────
    data["Rent Increases (Annual)"] = rx_any([
        r"(\d+(?:\.\d+)?)\s*%\s+(?:annual\s+)?(?:rent\s+)?(?:increase|review|CPI)",
        r"(?:annual\s+)?(?:rent\s+)?(?:increase|review)[^\d%]*(\d+(?:\.\d+)?)\s*%",
        r"CPI[^\d]*(\d+(?:\.\d+)?)\s*%",
    ], desc)

    # ── Area sqm ─────────────────────────────────────────────────────────
    data["Area (sqm)"] = rx_any([
        r"(?:Land\s+)?(?:Site\s+)?Area[:\s]+(?:approx\.?\s*)?(\d[\d,]*)\s*(?:square\s+metres?|sqm|m²|m2)",
        r"(\d[\d,]*)\s*(?:square\s+metres?|sqm|m²|m2)\s+(?:approx)?",
        r"(\d[\d,]*)\s*sqm",
    ], desc)

    # ── Daily Fees ───────────────────────────────────────────────────────
    daily_fee = title_fields.get("daily_fee", "")
    if not daily_fee:
        fee_str = rx_any([
            r"(?:weighted\s+)?(?:average\s+)?daily\s+(?:fee|rate)[:\s]+(?:from\s+)?\$([\d,]+(?:\.\d+)?)",
            r"\$([\d,]+(?:\.\d+)?)\s*(?:/|per)\s*(?:child\s+)?(?:per\s+)?day",
            r"(?:avg|average)\s+daily\s+(?:fee|rate)\s+(?:of\s+)?\$?([\d,]+(?:\.\d+)?)",
        ], desc)
        if fee_str:
            daily_fee = "$" + fee_str
    data["Current Daily Fees"] = daily_fee

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
        if v:
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
    if re.search(r"renovate?d?|refurb|upgrade|new\s+build|purpose.built|brand.new|turn.key", desc_lower):
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
        data["Waiting List"] = ""

    # ── Supply/Demand Ratio ──────────────────────────────────────────────
    data["Supply Ratio"] = rx_any([
        r"demand[- ](?:to[- ])?supply\s+ratio[:\s]+([\d.:]+)",
        r"([\d.]+)\s*:\s*1\s+demand[- ](?:to[- ])?supply",
        r"supply\s+ratio[:\s]+([\d.]+)",
        r"Population\s+0[-–]4\s+per\s+LDC[^:]*[:\s]+([\d.]+)",
    ], desc)

    # ── Demographics ─────────────────────────────────────────────────────
    data["# of Students Surrounding"] = rx_any([
        r"(\d[\d,]+)\s+(?:resident\s+)?(?:children|kids)\s+(?:aged|age)\s+(?:0[-–]4|0[-–]5|under\s+5)",
        r"([\d,]+)\s+children\s+(?:in\s+the\s+area|within)",
    ], desc)

    data["0-5 Resident Population"] = rx_any([
        r"(?:resident\s+)?0[-–]5\s+population[:\s]+([\d,]+)",
        r"([\d,]+)\s+resident\s+0[-–]5\s+population",
    ], desc)

    data["Resident Population"] = rx_any([
        r"(?:estimated\s+)?resident\s+population[:\s]+([\d,]+)",
        r"population\s+(?:of\s+)?([\d,]+)",
        r"([\d,]+)\s+(?:residents?|people)\s+(?:in\s+the\s+area|within)",
    ], desc)

    data["30-39 Females"] = rx_any([
        r"([\d,]+)\s+females?\s+aged?\s+30[-–]39",
        r"females?\s+30[-–]39[:\s]+([\d,]+)",
    ], desc)

    data["Average Household Income"] = rx_any([
        r"(?:average|median)\s+household\s+income[:\s]+\$?([\d,]+)",
    ], desc)

    data["Population Growth Rate (Per Year)"] = rx(
        r"population\s+(?:growth\s+)?(?:rate\s+)?(?:of\s+)?(\d+(?:\.\d+)?)\s*%",
        desc
    )

    # ── Additional Places ────────────────────────────────────────────────
    data["Additional Places to be Added"] = rx_any([
        r"additional\s+(\d+)\s+(?:approved\s+)?places",
        r"(\d+)\s+additional\s+(?:approved\s+)?places",
        r"(?:expanded|expand)\s+(?:from\s+\d+\s+(?:to|places\s+to)\s+)?(\d+)",
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

    # ── Occupancy cost ratio as Rent % Revenue ───────────────────────────
    occ_cost = rx(r"(\d+(?:\.\d+)?)\s*%\s+occupancy\s+cost\s+ratio", desc)
    if occ_cost:
        data["Rent % Revenue"] = occ_cost + "%"

    # ── Net Income / Price ratio ─────────────────────────────────────────
    if data["Net Income"] and data["Price"] and data["Price"].startswith("$"):
        try:
            ni_val = _parse_money_value(data["Net Income"])
            pr_val = _parse_money_value(data["Price"])
            if pr_val > 0:
                ratio = ni_val / pr_val
                data["Net Income / Price"] = f"{ratio:.2%}"
                if ratio > 0:
                    data["Years to Recover Investment"] = f"{1/ratio:.1f}"
        except Exception:
            pass

    # ── Rent % Revenue (fallback) ────────────────────────────────────────
    if not data["Rent % Revenue"] and data["Rent"] and data["Revenue"]:
        try:
            rent_val = _parse_money_value(data["Rent"])
            rev_val  = _parse_money_value(data["Revenue"])
            if rev_val > 0:
                data["Rent % Revenue"] = f"{rent_val / rev_val:.1%}"
        except Exception:
            pass

    return data


# ── Fetch content via WP REST API ────────────────────────────────────────────
def fetch_post_content(post_id: int) -> str:
    """Fetch rendered content for a single post via WP REST API."""
    url = f"{API_URL}/{post_id}"
    params = {"_fields": "content"}
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("content", {}).get("rendered", "")


def main():
    urls_path = "data/listing_urls_perituschildcare.json"
    if not os.path.exists(urls_path):
        print(f"ERROR: {urls_path} not found. Run 02_crawl_all_listings_perituschildcare.py first.")
        return

    with open(urls_path, encoding="utf-8") as f:
        listings = json.load(f)

    print("=" * 65)
    print(f"  PeritusChildcare.com.au - Extract Detail Pages")
    print(f"  Total listings to process: {len(listings)}")
    if _DATE_FROM or _DATE_TO:
        print(f"  Date filter: {DATE_FROM or 'any'} -> {DATE_TO or 'any'}")
    print("=" * 65)

    # Load existing progress
    output_path   = "data/childcare_raw_perituschildcare.json"
    filtered_path = "data/date_filtered_urls_perituschildcare.json"
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
        remaining, source="perituschildcare", log_dir="data"
    )
    print(f"  Remaining: {len(remaining)}")

    for i, item in enumerate(remaining):
        print(f"\n[{i+1}/{len(remaining)}] {item['url']}")

        try:
            html_content = fetch_post_content(item["id"])
        except Exception as e:
            print(f"  ERROR fetching content: {e}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "PeritusChildcare.com.au"
            rec["Related Source Item"] = item.get("title", "")
            all_records.append(rec)
            continue

        try:
            post_data = {
                "id": item["id"],
                "url": item["url"],
                "title": item["title"],
                "date": item["date"],
                "source_type": item.get("source_type", ""),
            }
            rec = extract(post_data, html_content)
        except Exception as e:
            print(f"  Extract error: {e}")
            rec = {col: "" for col in COLUMNS}
            rec["URL"] = item["url"]
            rec["Data Source"] = "PeritusChildcare.com.au"
            rec["Related Source Item"] = item.get("title", "")

        if rec is None:
            print(f"  Filtered (date out of range)")
            all_filtered_urls.append(item["url"])
        else:
            all_records.append(rec)
            status = rec.get("On Sale or Not", "?")
            price  = rec.get("Price", "N/A")
            places = rec.get("Place", "?")
            suburb = rec.get("Suburb", "?")
            print(f"  OK | {status} | {price} | {places} places | {suburb}")

        # Save progress periodically
        if (i + 1) % PROGRESS_SAVE == 0:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(all_records, f, indent=2, ensure_ascii=False)
            with open(filtered_path, "w", encoding="utf-8") as f:
                json.dump(all_filtered_urls, f, indent=2, ensure_ascii=False)
            print(f"  Progress saved ({len(all_records)} records, "
                  f"{len(all_filtered_urls)} filtered)")

        time.sleep(DELAY)

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
    main()
