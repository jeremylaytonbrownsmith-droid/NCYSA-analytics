#!/usr/bin/env python3
"""
NCYSA Find My Club - pre-publish guardrail (Phase C, Step 5).

Compares this run's core numbers against the last known-good baseline
(baseline.json, committed to the repo) before any publish happens. Aborts
with a non-zero exit -- which makes the GitHub Actions job fail and GitHub
email a failure notice -- if any core metric is zero/missing, or has swung
more than 60% from the last baseline in either direction. A swing that
large is much more likely to mean something broke upstream (wrong property
ID, a renamed GA4 dimension, auth silently returning empty data) than
genuine traffic change.

On a passing run, baseline.json is overwritten with this run's numbers --
but ONLY on a pass, so a bad run never poisons what future runs compare
against.

First run (no baseline.json yet): nothing to compare, so it passes
unconditionally (after the zero/missing check, which always applies) and
writes the initial baseline.

Usage: python3 guardrail.py [data.json] [baseline.json]
"""

import sys
import json

DATA_PATH = sys.argv[1] if len(sys.argv) > 1 else "ga_report_data.json"
BASELINE_PATH = sys.argv[2] if len(sys.argv) > 2 else "baseline.json"

SWING_THRESHOLD = 0.60


def extract_core_numbers(data):
    bc = data["baseline_check"]
    return {
        "zip_search_events": bc.get("zip_search_events"),
        "fmc_page_views": data.get("fmc_page", {}).get("views"),
        "club_click_events": data.get("club_click", {}).get("total_clicks"),
        "zip_search_distinct_zips": bc.get("zip_search_distinct_zips"),
    }


def main():
    data = json.load(open(DATA_PATH))
    current = extract_core_numbers(data)

    missing = [k for k, v in current.items() if v is None or v == 0]
    if missing:
        print("Guardrail: ABORT")
        print(f"  Zero or missing value(s) for: {', '.join(missing)}")
        print(f"  Values this run: {current}")
        print("  Not publishing. This usually means an upstream query broke silently "
              "(wrong property ID, a renamed dimension, auth returning empty data).")
        sys.exit(1)

    try:
        baseline = json.load(open(BASELINE_PATH))
    except FileNotFoundError:
        print(f"Guardrail: no {BASELINE_PATH} yet -- first run, nothing to compare against.")
        for k, v in current.items():
            print(f"  {k}: {v}")
        json.dump(current, open(BASELINE_PATH, "w"), indent=2)
        print(f"Wrote initial {BASELINE_PATH}. PASS.")
        sys.exit(0)

    swings = []
    print("Guardrail: comparing against last baseline")
    for k, new in current.items():
        old = baseline.get(k)
        if old is None or old == 0:
            print(f"  {k}: {old} -> {new} (no prior baseline for this metric, skipping swing check)")
            continue
        pct = (new - old) / old
        flag = "  <-- SWING > 60%" if abs(pct) > SWING_THRESHOLD else ""
        print(f"  {k}: {old} -> {new} ({pct:+.0%}){flag}")
        if abs(pct) > SWING_THRESHOLD:
            swings.append((k, old, new, pct))

    if swings:
        print(f"\nGuardrail: ABORT -- {len(swings)} metric(s) swung more than {SWING_THRESHOLD:.0%}:")
        for k, old, new, pct in swings:
            print(f"  {k}: {old} -> {new} ({pct:+.0%})")
        print(f"  Not publishing. {BASELINE_PATH} left unchanged -- the next run will compare "
              "against these same last-known-good numbers, not this run's.")
        sys.exit(1)

    json.dump(current, open(BASELINE_PATH, "w"), indent=2)
    print(f"\nGuardrail: PASS -- {BASELINE_PATH} updated.")
    sys.exit(0)


if __name__ == "__main__":
    main()
