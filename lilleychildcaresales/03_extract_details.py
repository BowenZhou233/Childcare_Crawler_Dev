#!/usr/bin/env python3
"""
Step 3: Map raw listing data to standard columns.
Since lilleyccs.com has no individual detail pages, all data was already
extracted in step 2. This script transforms raw data into the standard
column format used across all crawlers.

Input:  data/listing_urls.json
Output: data/childcare_raw.json
"""

import os
import json
import re

os.makedirs("data", exist_ok=True)

# ── All target columns (same as anybusiness/businessforsale/sydneychildcaresales/peritus) ─
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


def parse_location(location: str) -> dict:
    """
    Parse location string into suburb, city, state components.
    Examples:
      "QLD Gold Coast" -> state=QLD, suburb=Gold Coast
      "Sydney Hurstville Area" -> state=NSW, city=Sydney, suburb=Hurstville Area
      "Melbourne Whittlesea Area" -> state=VIC, city=Melbourne, suburb=Whittlesea Area
      "Sydney - Bangor" -> state=NSW, city=Sydney, suburb=Bangor
      "VIC - Melbourne - Tarneit" -> state=VIC, city=Melbourne, suburb=Tarneit
      "NSW - Cooma" -> state=NSW, suburb=Cooma
      "Regional NSW North-West" -> state=NSW, suburb=North-West
    """
    result = {"suburb": "", "city": "", "state": "", "direction": ""}

    if not location:
        return result

    loc = location.strip()

    # State mapping from city/region prefixes
    CITY_STATE = {
        "sydney": "NSW", "melbourne": "VIC", "brisbane": "QLD",
        "adelaide": "SA", "perth": "WA", "hobart": "TAS",
        "canberra": "ACT", "darwin": "NT", "gold coast": "QLD",
        "sunshine coast": "QLD", "townsville": "QLD",
    }

    STATE_CODES = {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"}

    # Pattern: "STATE - City - Suburb" or "STATE - Suburb"
    dash_parts = [p.strip() for p in re.split(r"\s*[-–]\s*", loc)]

    if len(dash_parts) >= 3:
        # e.g., "VIC - Melbourne - Tarneit"
        if dash_parts[0].upper() in STATE_CODES:
            result["state"] = dash_parts[0].upper()
            result["city"] = dash_parts[1]
            result["suburb"] = " - ".join(dash_parts[2:])
        elif dash_parts[0].lower() in CITY_STATE:
            result["state"] = CITY_STATE[dash_parts[0].lower()]
            result["city"] = dash_parts[0]
            result["suburb"] = " - ".join(dash_parts[1:])
        else:
            result["suburb"] = loc
    elif len(dash_parts) == 2:
        # e.g., "Sydney - Bangor" or "NSW - Cooma"
        first = dash_parts[0]
        second = dash_parts[1]
        if first.upper() in STATE_CODES:
            result["state"] = first.upper()
            result["suburb"] = second
        elif first.lower() in CITY_STATE:
            result["state"] = CITY_STATE[first.lower()]
            result["city"] = first
            result["suburb"] = second
        else:
            result["suburb"] = loc
    else:
        # Single part, e.g., "QLD Gold Coast" or "Sydney Inner West"
        # Check if starts with state code
        state_match = re.match(
            r"^(NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\s+(.+)", loc, re.IGNORECASE
        )
        if state_match:
            result["state"] = state_match.group(1).upper()
            remainder = state_match.group(2).strip()
            # Check if remainder starts with a city
            for city, st in CITY_STATE.items():
                if remainder.lower().startswith(city):
                    result["city"] = remainder[:len(city)].title()
                    result["suburb"] = remainder[len(city):].strip()
                    break
            if not result["suburb"]:
                result["suburb"] = remainder
        else:
            # Check if starts with a known city
            for city, st in CITY_STATE.items():
                if loc.lower().startswith(city):
                    result["state"] = st
                    result["city"] = loc[:len(city)].title()
                    remainder = loc[len(city):].strip()
                    result["suburb"] = remainder if remainder else city.title()
                    break
            if not result["suburb"]:
                # Check for "Regional NSW" pattern
                reg_match = re.match(
                    r"Regional\s+(NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\s*(.*)",
                    loc, re.IGNORECASE
                )
                if reg_match:
                    result["state"] = reg_match.group(1).upper()
                    result["suburb"] = reg_match.group(2).strip() or "Regional"
                    result["direction"] = "Regional"
                else:
                    result["suburb"] = loc

    # Clean "Area" suffix from suburb
    result["suburb"] = re.sub(r"\s+Area$", "", result["suburb"]).strip()

    # Detect direction keywords
    if not result["direction"]:
        dir_match = re.search(
            r"(Inner West|Eastern Suburbs|Western Suburbs|Northern|Southern|"
            r"North[- ]?West|South[- ]?West|North[- ]?East|South[- ]?East|"
            r"Lower North Shore|Upper North Shore|Central West|"
            r"Sutherland Shire|Northern Beaches|Hills District|"
            r"CBD|Olympic Park|Penrith Region)",
            loc, re.IGNORECASE
        )
        if dir_match:
            result["direction"] = dir_match.group(1)

    # If no city set, use state capital as city
    if not result["city"] and result["state"]:
        STATE_CAPITALS = {
            "NSW": "Sydney", "VIC": "Melbourne", "QLD": "Brisbane",
            "SA": "Adelaide", "WA": "Perth", "TAS": "Hobart",
            "ACT": "Canberra", "NT": "Darwin",
        }
        result["city"] = STATE_CAPITALS.get(result["state"], "")

    return result


def map_to_columns(raw: dict) -> dict:
    """Map raw listing data to standard column format."""
    data = {col: "" for col in COLUMNS}

    data["Data Source"] = "LilleyCCS.com"
    data["Business No."] = raw.get("code", "")

    # URL - construct from source
    if raw.get("source") == "sold":
        data["URL"] = "https://www.lilleyccs.com/sold"
    else:
        data["URL"] = "https://www.lilleyccs.com/properties/"

    # Related Source Item — raw text description
    data["Related Source Item"] = raw.get("raw_text", "")

    # Status mapping
    status = raw.get("status", "")
    if status == "Active":
        data["On Sale or Not"] = "Active"
    elif status == "Under Offer":
        data["On Sale or Not"] = "Under Offer"
    elif status == "Under Contract":
        data["On Sale or Not"] = "Under Contract"
    elif status == "Sold":
        data["On Sale or Not"] = "Sold"
    else:
        data["On Sale or Not"] = status or "Unknown"

    # Financial year as sold date proxy
    if raw.get("financial_year"):
        data["Sold Date"] = raw["financial_year"]

    # Location
    location = raw.get("location", "")
    loc_parts = parse_location(location)
    data["Suburb"] = loc_parts["suburb"]
    data["City"] = loc_parts["city"]
    data["State"] = loc_parts["state"]
    data["Location Direction"] = loc_parts["direction"]

    # Price
    data["Price"] = raw.get("price", "")

    # Places
    data["Place"] = raw.get("places", "")

    # Leasehold or Freehold — infer from sale_type
    sale_type = raw.get("sale_type", "")
    if sale_type == "Business Only":
        data["Leasehold or Freehold"] = "Leasehold"
        data["Site"] = "Leasehold"
    elif sale_type == "Freehold Only":
        data["Leasehold or Freehold"] = "Freehold"
        data["Site"] = "Freehold"
    elif sale_type == "Business and Freehold":
        data["Leasehold or Freehold"] = "Business and Freehold"
        data["Site"] = "Business and Freehold"

    return data


def main():
    input_path  = "data/listing_urls.json"
    output_path = "data/childcare_raw.json"

    if not os.path.exists(input_path):
        print(f"ERROR: {input_path} not found. Run 02_crawl_all_listings.py first.")
        return

    with open(input_path, encoding="utf-8") as f:
        raw_listings = json.load(f)

    print("=" * 65)
    print(f"  LilleyCCS.com - Map Data to Standard Columns")
    print(f"  Total raw listings: {len(raw_listings)}")
    print("=" * 65)

    records = []
    for raw in raw_listings:
        rec = map_to_columns(raw)
        records.append(rec)
        status = rec.get("On Sale or Not", "?")
        price  = rec.get("Price", "N/A") or "N/A"
        places = rec.get("Place", "?") or "?"
        suburb = rec.get("Suburb", "?") or "?"
        print(f"  {status:16s} | {price:20s} | {places:>4s} places | {suburb}")

    # Save
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    # Summary
    active = sum(1 for r in records if r["On Sale or Not"] == "Active")
    offer  = sum(1 for r in records if r["On Sale or Not"] == "Under Offer")
    contract = sum(1 for r in records if r["On Sale or Not"] == "Under Contract")
    sold   = sum(1 for r in records if r["On Sale or Not"] == "Sold")
    w_price = sum(1 for r in records if r["Price"])
    w_place = sum(1 for r in records if r["Place"])

    print("\n" + "=" * 65)
    print(f"  DONE: {len(records)} records saved -> {output_path}")
    print(f"    Active:         {active}")
    print(f"    Under Offer:    {offer}")
    print(f"    Under Contract: {contract}")
    print(f"    Sold:           {sold}")
    print(f"    Has Price:      {w_price}")
    print(f"    Has Places:     {w_place}")
    print("=" * 65)


if __name__ == "__main__":
    main()
