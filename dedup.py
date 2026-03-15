#!/usr/bin/env python3
"""
Shared deduplication module for all childcare crawlers.

Loads the master database spreadsheet and provides functions to filter out
listings that already exist in the database.

Dedup logic:
  1. Primary: exact URL match
  2. Secondary: (Data Source + Related Source Item title) fuzzy combo match

Usage in 02_crawl_all_listings_{site}.py:
    from dedup import DedupChecker
    checker = DedupChecker()
    new_listings = checker.filter_listings(all_listings, source="anybusiness")

Usage in 03_extract_details_{site}.py:
    from dedup import DedupChecker
    checker = DedupChecker()
    new_listings = checker.filter_listings(listings, source="anybusiness")
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Path to the master database Excel file
DB_EXCEL_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "0.final data leasehold & freehold.xlsx",
)

# Mapping: crawler Data Source name → database Data Source name (lowercase)
SOURCE_MAP = {
    "anybusiness":          "anybusiness",
    "Anybusiness.com.au":   "anybusiness",
    "businessforsale":      "businessforsale",
    "BusinessForSale.com.au": "businessforsale",
    "lilleychildcaresales": "lilleychildcaresales",
    "LilleyCCS.com":        "lilleychildcaresales",
    "perituschildcare":     "perituschildcare",
    "PeritusChildcare.com.au": "perituschildcare",
    "sydneychildcaresales": "sydneychildcaresales",
    "SydneyChildcareSales.com.au": "sydneychildcaresales",
}

# Skipped-listings log directory (created per-crawler under data/)
SKIP_LOG_NAME = "dedup_skipped.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_url(url: str | None) -> str:
    """Normalise a URL for comparison: lowercase, strip trailing slash & whitespace."""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip().lower().rstrip("/")
    # Remove protocol prefix for looser matching
    url = re.sub(r"^https?://", "", url)
    # Remove www. prefix
    url = re.sub(r"^www\.", "", url)
    return url


def _normalise_title(title: str | None) -> str:
    """Normalise a title for fuzzy comparison."""
    if not title or not isinstance(title, str):
        return ""
    t = title.strip().lower()
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t)
    # Remove common punctuation for looser matching
    t = re.sub(r"[^\w\s]", "", t)
    return t


def _normalise_source(source: str | None) -> str:
    """Map any source name variant to a canonical lowercase key."""
    if not source:
        return ""
    s = source.strip()
    return SOURCE_MAP.get(s, s.lower())


# ---------------------------------------------------------------------------
# DedupChecker
# ---------------------------------------------------------------------------

class DedupChecker:
    """Loads the master database and checks new listings for duplicates."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or DB_EXCEL_PATH
        self._url_set: set[str] = set()            # normalised URLs
        self._title_by_source: dict[str, set[str]] = {}  # source → set of normalised titles
        self._code_by_source: dict[str, set[str]] = {}   # source → set of codes (e.g. lilley)
        self._loaded = False

    def _load(self) -> None:
        """Load master database from Excel (lazy, one-time)."""
        if self._loaded:
            return
        try:
            import openpyxl
        except ImportError:
            print("[dedup] openpyxl not installed — skipping dedup check")
            self._loaded = True
            return

        if not os.path.exists(self.db_path):
            print(f"[dedup] Database file not found: {self.db_path}")
            print("[dedup] Dedup check disabled — all listings will be processed.")
            self._loaded = True
            return

        print(f"[dedup] Loading master database: {self.db_path}")
        wb = openpyxl.load_workbook(self.db_path, read_only=True, data_only=True)
        ws = wb[wb.sheetnames[0]]

        row_count = 0
        url_count = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(v is not None for v in row[:5]):
                continue
            row_count += 1

            # Column mapping: 0=item, 1=Date, 2=DataSource, 3=Title, 4=URL/item
            raw_url = row[4] if len(row) > 4 else None
            raw_title = row[3] if len(row) > 3 else None
            raw_source = row[2] if len(row) > 2 else None

            # --- Primary key: URL ---
            if raw_url and isinstance(raw_url, str) and raw_url.startswith("http"):
                norm_url = _normalise_url(raw_url)
                if norm_url:
                    self._url_set.add(norm_url)
                    url_count += 1

            # --- Secondary key: Source + Title ---
            norm_source = _normalise_source(str(raw_source) if raw_source else "")
            norm_title = _normalise_title(str(raw_title) if raw_title else "")
            if norm_source and norm_title:
                self._title_by_source.setdefault(norm_source, set()).add(norm_title)

            # --- Code index (for lilley-style listings with "code XXXX" titles) ---
            if norm_source and raw_title and isinstance(raw_title, str):
                code_match = re.search(r"(?:code\s*)?0?(\d{3,4})\b", str(raw_title), re.IGNORECASE)
                if code_match:
                    self._code_by_source.setdefault(norm_source, set()).add(
                        code_match.group(1).zfill(4)
                    )

        wb.close()
        self._loaded = True
        print(f"[dedup] Loaded {row_count} records ({url_count} with URLs) from database.")
        for src, titles in sorted(self._title_by_source.items()):
            print(f"  {src}: {len(titles)} titles indexed")

    # ----- public API -----

    def is_duplicate(
        self,
        url: str | None = None,
        title: str | None = None,
        source: str | None = None,
        code: str | None = None,
    ) -> tuple[bool, str]:
        """
        Check if a listing is already in the database.

        Returns:
            (is_dup, reason) — reason is "" if not a duplicate,
            otherwise "url_match", "title_match", or "code_match".
        """
        self._load()

        # 1) Primary: URL match
        norm_url = _normalise_url(url)
        if norm_url and norm_url in self._url_set:
            return True, "url_match"

        # 2) Secondary: Source + Title match
        norm_source = _normalise_source(source)
        norm_title = _normalise_title(title)
        if norm_source and norm_title:
            known_titles = self._title_by_source.get(norm_source, set())
            if norm_title in known_titles:
                return True, "title_match"

        # 3) Code match (for lilley-style listings)
        if code and norm_source:
            norm_code = code.strip().lstrip("0").zfill(4)
            known_codes = self._code_by_source.get(norm_source, set())
            if norm_code in known_codes:
                return True, "code_match"

        return False, ""

    def filter_listings(
        self,
        listings: list[dict],
        source: str,
        url_key: str = "url",
        title_key: str = "title",
        code_key: str | None = None,
        log_dir: str | None = None,
    ) -> list[dict]:
        """
        Filter a list of listing dicts, removing those already in the database.

        Args:
            listings:  list of dicts from step 2 (each has url, title, etc.)
            source:    crawler source name (e.g. "anybusiness")
            url_key:   key in the dict that holds the URL
            title_key: key in the dict that holds the title
            code_key:  key in the dict that holds a listing code (e.g. "code" for lilley)
            log_dir:   directory to write the skip log (defaults to current dir)

        Returns:
            Filtered list with duplicates removed.
        """
        self._load()

        kept: list[dict] = []
        skipped: list[dict] = []

        for item in listings:
            item_url = item.get(url_key, "")
            item_title = item.get(title_key, "")
            item_code = item.get(code_key, "") if code_key else ""

            is_dup, reason = self.is_duplicate(
                url=item_url, title=item_title, source=source, code=item_code
            )

            if is_dup:
                skipped.append({
                    **item,
                    "_dedup_reason": reason,
                    "_dedup_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
            else:
                kept.append(item)

        # Summary
        reason_counts = {}
        for s in skipped:
            r = s["_dedup_reason"]
            reason_counts[r] = reason_counts.get(r, 0) + 1
        reasons_str = ", ".join(f"{k}: {v}" for k, v in sorted(reason_counts.items()))
        print(f"[dedup] {source}: {len(listings)} total → "
              f"{len(kept)} new, {len(skipped)} skipped "
              f"({reasons_str})")

        # Save skip log for verification
        if skipped:
            out_dir = log_dir or "."
            os.makedirs(out_dir, exist_ok=True)
            skip_name = f"dedup_skipped_{source}.json"
            log_path = os.path.join(out_dir, skip_name)

            # Merge with existing log if present
            existing = []
            if os.path.exists(log_path):
                try:
                    with open(log_path, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, OSError):
                    existing = []

            # Avoid duplicating skip entries
            existing_urls = {_normalise_url(e.get(url_key, "")) for e in existing}
            for s in skipped:
                if _normalise_url(s.get(url_key, "")) not in existing_urls:
                    existing.append(s)

            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
            print(f"[dedup] Skip log saved: {log_path} ({len(existing)} entries)")

        return kept

    def filter_extract_listings(
        self,
        listings: list[dict],
        source: str,
        url_key: str = "url",
        title_key: str = "title",
        code_key: str | None = None,
        log_dir: str | None = None,
    ) -> list[dict]:
        """
        Same as filter_listings but for step 3 (03_extract_details.py).
        Uses the same logic — this is a second-pass safety net.
        """
        return self.filter_listings(
            listings, source, url_key, title_key, code_key, log_dir
        )


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """Quick test: load database and print stats."""
    checker = DedupChecker()
    checker._load()

    print(f"\nURL index size: {len(checker._url_set)}")
    print(f"Title indexes: {len(checker._title_by_source)} sources")

    # Test with a known URL from the database
    test_urls = [
        "https://www.anybusiness.com.au/listings/melton-vic-3337-education-training-child-care-34384799",
        "https://perituschildcare.com.au/scone/",
        "https://www.example.com/not-in-db",
    ]
    print("\n--- URL dedup tests ---")
    for u in test_urls:
        dup, reason = checker.is_duplicate(url=u)
        print(f"  {'DUP' if dup else 'NEW'} [{reason:12s}] {u[:80]}")

    # Test title matching
    print("\n--- Title dedup tests ---")
    test_titles = [
        ("property ID 29610 NSW-Moss Vale (est 2016)- BUSINESS and/or FREEHOLD", "commercialrealestate"),
        ("Some New Listing Never Seen", "anybusiness"),
    ]
    for title, src in test_titles:
        dup, reason = checker.is_duplicate(title=title, source=src)
        print(f"  {'DUP' if dup else 'NEW'} [{reason:12s}] {src}: {title[:60]}")
