#!/usr/bin/env python3
"""
One-click runner: collect all listings -> extract -> export
Usage: python run_all.py [--step N]
  --step 2  : only collect listings (step 2)
  --step 3  : only extract/map details (step 3)
  --step 4  : only export (step 4)
  (no args) : run all steps 2 -> 3 -> 4
"""
import sys, subprocess, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

STEPS = {
    2: ("Crawl all listings",     "02_crawl_all_listings_lilleychildcaresales.py"),
    3: ("Map to standard columns", "03_extract_details_lilleychildcaresales.py"),
    4: ("Export CSV/Excel",        "04_export_lilleychildcaresales.py"),
}

def run_step(n):
    name, script = STEPS[n]
    print(f"\n{'='*60}")
    print(f"  Step {n}: {name}")
    print(f"{'='*60}")
    result = subprocess.run([sys.executable, script], check=True)
    return result.returncode == 0

target = None
for arg in sys.argv[1:]:
    if arg.startswith("--step"):
        parts = arg.split("=")
        if len(parts) == 2:
            target = int(parts[1])
        elif len(sys.argv) > sys.argv.index(arg) + 1:
            target = int(sys.argv[sys.argv.index(arg) + 1])

if target:
    run_step(target)
else:
    for step in [2, 3, 4]:
        if not run_step(step):
            print(f"Step {step} failed. Stopping.")
            sys.exit(1)

print("\nAll done! Output: data/childcare_data.xlsx and data/childcare_data.csv")
