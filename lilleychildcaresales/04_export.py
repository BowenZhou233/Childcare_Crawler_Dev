#!/usr/bin/env python3
"""
Step 4: Export childcare_raw.json -> childcare_data.xlsx and childcare_data.csv
Input:  data/childcare_raw.json
Output: data/childcare_data.xlsx
        data/childcare_data.csv
"""

import os
import json

os.makedirs("data", exist_ok=True)

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


def load_data(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        records = json.load(f)

    cleaned = []
    for rec in records:
        row = {col: rec.get(col, "") for col in COLUMNS}
        cleaned.append(row)
    return cleaned


def export_csv(records: list[dict], path: str):
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    print(f"  CSV  -> {path}  ({len(records)} rows)")


def export_excel(records: list[dict], path: str):
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("  openpyxl not installed. Installing...")
        import subprocess, sys
        subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl", "-q"])
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Childcare Listings"

    # Header style
    header_font   = Font(bold=True, color="FFFFFF", size=10)
    header_fill   = PatternFill("solid", fgColor="1F4E79")
    header_align  = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border   = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin")
    )

    # Write header
    for col_idx, col_name in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font   = header_font
        cell.fill   = header_fill
        cell.alignment = header_align
        cell.border = thin_border

    ws.row_dimensions[1].height = 30
    ws.freeze_panes = "A2"

    # Alternating row fills
    fill_even = PatternFill("solid", fgColor="EBF3FB")
    fill_odd  = PatternFill("solid", fgColor="FFFFFF")
    data_align = Alignment(vertical="center", wrap_text=False)
    sold_font  = Font(color="CC0000")
    active_font = Font(color="116830")

    # Write data
    for row_idx, rec in enumerate(records, start=2):
        fill = fill_even if row_idx % 2 == 0 else fill_odd
        is_sold = rec.get("On Sale or Not", "").lower() in ("sold",)

        for col_idx, col_name in enumerate(COLUMNS, start=1):
            val = rec.get(col_name, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.fill      = fill
            cell.alignment = data_align
            cell.border    = thin_border

            if col_name == "On Sale or Not":
                cell.font = sold_font if is_sold else active_font

    # Column widths
    col_widths = {
        "Business No.": 14,
        "Date of Listing": 16,
        "Data Source": 26,
        "Related Source Item": 18,
        "URL": 50,
        "Suburb": 16,
        "City": 16,
        "State": 8,
        "Location Direction": 18,
        "Leasehold or Freehold": 20,
        "Site": 12,
        "On Sale or Not": 14,
        "Sold Date": 14,
        "Current Occupancy": 18,
        "Price": 14,
    }
    for col_idx, col_name in enumerate(COLUMNS, start=1):
        width = col_widths.get(col_name, 18)
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    wb.save(path)
    print(f"  Excel -> {path}  ({len(records)} rows, {len(COLUMNS)} columns)")


def print_summary(records: list[dict]):
    total   = len(records)
    active  = sum(1 for r in records if r.get("On Sale or Not", "").lower() == "active")
    sold    = sum(1 for r in records if r.get("On Sale or Not", "").lower() == "sold")
    offer   = sum(1 for r in records if "under offer" in r.get("On Sale or Not", "").lower())
    contract = sum(1 for r in records if "under contract" in r.get("On Sale or Not", "").lower())
    w_price = sum(1 for r in records if r.get("Price", ""))
    w_place = sum(1 for r in records if r.get("Place", ""))
    w_state = sum(1 for r in records if r.get("State", ""))
    w_tenure= sum(1 for r in records if r.get("Leasehold or Freehold", ""))

    print(f"\n  Summary:")
    print(f"    Total records      : {total}")
    print(f"    Active             : {active}")
    print(f"    Under Offer        : {offer}")
    print(f"    Under Contract     : {contract}")
    print(f"    Sold               : {sold}")
    print(f"    Has Price          : {w_price}")
    print(f"    Has Places         : {w_place}")
    print(f"    Has State          : {w_state}")
    print(f"    Has Lease/Freehold : {w_tenure}")


def main():
    input_path  = "data/childcare_raw.json"
    csv_path    = "data/childcare_data_lilleychildcaresales.csv"
    excel_path  = "data/childcare_data_lilleychildcaresales.xlsx"

    if not os.path.exists(input_path):
        print(f"ERROR: {input_path} not found. Run 03_extract_details.py first.")
        return

    print("=" * 65)
    print("  LilleyCCS.com - Export Data")
    print("=" * 65)

    records = load_data(input_path)
    print_summary(records)

    print("\n  Exporting...")
    export_csv(records, csv_path)
    export_excel(records, excel_path)

    print("\n  Export complete!")
    print("=" * 65)


if __name__ == "__main__":
    main()
