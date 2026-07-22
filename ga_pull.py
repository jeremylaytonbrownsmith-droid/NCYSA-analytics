#!/usr/bin/env python3
"""
NCYSA Find My Club - GA4 data pull + reconciliation.

Phase A (this file): pull every number the board report needs from the GA4
Data API and print a reconciliation table against the known-good baseline
(the figures that shipped in the July report). It PUBLISHES NOTHING. Its only
job is to prove the API access works and the numbers line up before we ever
wire up the WordPress publish step.

Runs anywhere with normal internet access (e.g. GitHub Actions). It does NOT
run inside the Cowork sandbox, which is firewalled off from Google's APIs.

Auth: expects the service-account JSON at the path in env GA4_KEY_FILE
(default: key.json). Property from env GA4_PROPERTY_ID (default: 514757424).
Date window from env RANGE_START / RANGE_END (default: 2026-01-01 .. yesterday).
For a clean comparison to the July baseline, set RANGE_END=2026-07-20.
"""

import os
import sys
import json
import datetime

from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest, DateRange, Dimension, Metric,
    Filter, FilterExpression, FilterExpressionList,
)

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
KEY_FILE = os.environ.get("GA4_KEY_FILE", "key.json")
PROPERTY = "properties/" + os.environ.get("GA4_PROPERTY_ID", "514757424")
RANGE_START = os.environ.get("RANGE_START", "2026-01-01")
RANGE_END = os.environ.get(
    "RANGE_END",
    (datetime.date(2026, 7, 20)).isoformat(),  # default matches baseline window
)
# club_click tracking only began 2026-07-08; its window is separate.
CLICK_START = os.environ.get("CLICK_START", "2026-07-08")
CAMPAIGN = "worldcup2026"
CAMPAIGN_MARKER = "2026-06-11"  # locked-in "campaign first appears" date

# Known-good baseline that shipped in the July board report. The dry run diffs
# live API numbers against these so we can trust the pipeline before publishing.
BASELINE = {
    "zip_search_events": 8125,
    "zip_search_users": 6342,
    "zip_search_distinct_zips": 856,
    "zip_search_nc_zips": 657,
    "zip_search_nc_share_pct": 96.0,
    "fmc_page_views": 24014,
    "fmc_page_key_events": 5742,
    "club_click_events": 2314,
    "club_click_rank1_share_pct": 55.0,
    "club_click_distinct_clubs": 105,
    "club_click_website_share_pct": 97.0,
    "coverage_gap_events": 67,
    "coverage_gap_nc_events": 16,
    "paid_search_sessions": 7041,
    "paid_search_key_events": 4002,
    "paid_social_sessions": 8885,
    "paid_social_key_events": 739,
    "campaign_sessions": 16170,
    "campaign_key_events": 4733,
    "daily_before_marker": 25,
    "daily_after_marker": 138,
}

client = None
results = {}
errors = {}


def get_client():
    creds = service_account.Credentials.from_service_account_file(
        KEY_FILE, scopes=["https://www.googleapis.com/auth/analytics.readonly"])
    # REST transport avoids gRPC; works everywhere and is easier to proxy.
    return BetaAnalyticsDataClient(credentials=creds, transport="rest")


def run(dimensions, metrics, start=RANGE_START, end=RANGE_END, dim_filter=None):
    req = RunReportRequest(
        property=PROPERTY,
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name=d) for d in dimensions],
        metrics=[Metric(name=m) for m in metrics],
        dimension_filter=dim_filter,
        limit=100000,
    )
    return client.run_report(req)


def event_filter(*names):
    return FilterExpression(or_group=FilterExpressionList(expressions=[
        FilterExpression(filter=Filter(
            field_name="eventName",
            string_filter=Filter.StringFilter(value=n))) for n in names
    ]))


def is_valid_zip(z):
    z = (z or "").strip()
    return len(z) == 5 and z.isdigit()


def is_nc_zip(z):
    # Require a proper 5-digit zip before checking the prefix: some search_zip
    # values arrive with a stripped leading zero (e.g. "2720" for MA's 02720),
    # and z[:2] == "27" on that malformed value would misclassify it as NC.
    z = (z or "").strip()
    return is_valid_zip(z) and z[:2] in ("27", "28")


def safe(name, fn):
    """Run a metric collector, capturing failures so one broken query doesn't
    abort the whole reconciliation."""
    try:
        fn()
    except Exception as e:  # noqa
        errors[name] = repr(e)
        print(f"  [!] {name} FAILED: {e}")


# ----------------------------------------------------------------------------
# Collectors
# ----------------------------------------------------------------------------
def collect_zip_search():
    r = run(["eventName"], ["eventCount", "totalUsers"], dim_filter=event_filter("zip_search"))
    if r.rows:
        results["zip_search_events"] = int(r.rows[0].metric_values[0].value)
        results["zip_search_users"] = int(r.rows[0].metric_values[1].value)


def collect_zip_breakdown():
    r = run(["customEvent:search_zip"], ["eventCount"], dim_filter=event_filter("zip_search"))
    zips, total, nc_total, nc_zips = set(), 0, 0, set()
    for row in r.rows:
        z = row.dimension_values[0].value
        c = int(row.metric_values[0].value)
        if not is_valid_zip(z):
            continue
        zips.add(z)
        total += c
        if is_nc_zip(z):
            nc_total += c
            nc_zips.add(z)
    results["zip_search_distinct_zips"] = len(zips)
    results["zip_search_nc_zips"] = len(nc_zips)
    results["zip_search_nc_share_pct"] = round(100.0 * nc_total / total, 1) if total else 0.0


def collect_fmc_page():
    # Match the Find My Club page by path fragment. "find-your-ncysa-club" is a
    # separate legacy page (0 key events, not the interactive tool) and must
    # not be folded into this total.
    r = run(["pagePath"], ["screenPageViews", "keyEvents"])
    views, kev = 0, 0
    for row in r.rows:
        path = (row.dimension_values[0].value or "").lower()
        if "find-my-club" in path:
            views += int(row.metric_values[0].value)
            kev += int(float(row.metric_values[1].value))
    results["fmc_page_views"] = views
    results["fmc_page_key_events"] = kev


def collect_club_click():
    r = run(["eventName"], ["eventCount"], start=CLICK_START, dim_filter=event_filter("club_click"))
    if r.rows:
        results["club_click_events"] = int(r.rows[0].metric_values[0].value)
    # rank-1 share
    r2 = run(["customEvent:club_rank"], ["eventCount"], start=CLICK_START, dim_filter=event_filter("club_click"))
    total, rank1 = 0, 0
    for row in r2.rows:
        c = int(row.metric_values[0].value)
        total += c
        if row.dimension_values[0].value == "1":
            rank1 += c
    results["club_click_rank1_share_pct"] = round(100.0 * rank1 / total, 1) if total else 0.0
    # distinct clubs
    r3 = run(["customEvent:club_name"], ["eventCount"], start=CLICK_START, dim_filter=event_filter("club_click"))
    clubs = {row.dimension_values[0].value for row in r3.rows
             if row.dimension_values[0].value not in ("(not set)", "", None)}
    results["club_click_distinct_clubs"] = len(clubs)
    # website vs email share
    r4 = run(["customEvent:click_action"], ["eventCount"], start=CLICK_START, dim_filter=event_filter("club_click"))
    total4, web = 0, 0
    for row in r4.rows:
        c = int(row.metric_values[0].value)
        total4 += c
        if row.dimension_values[0].value == "website":
            web += c
    results["club_click_website_share_pct"] = round(100.0 * web / total4, 1) if total4 else 0.0


def collect_coverage_gap():
    r = run(["customEvent:search_zip"], ["eventCount"], dim_filter=event_filter("coverage_gap"))
    total, nc = 0, 0
    for row in r.rows:
        z = row.dimension_values[0].value
        c = int(row.metric_values[0].value)
        total += c
        if is_nc_zip(z):
            nc += c
    results["coverage_gap_events"] = total
    results["coverage_gap_nc_events"] = nc


def collect_channels():
    r = run(["sessionDefaultChannelGroup"], ["sessions", "engagementRate", "keyEvents"])
    for row in r.rows:
        ch = row.dimension_values[0].value
        sess = int(row.metric_values[0].value)
        eng = round(100.0 * float(row.metric_values[1].value), 0)
        kev = int(float(row.metric_values[2].value))
        if ch == "Paid Search":
            results["paid_search_sessions"] = sess
            results["paid_search_key_events"] = kev
            results["paid_search_eng_pct"] = eng
        elif ch == "Paid Social":
            results["paid_social_sessions"] = sess
            results["paid_social_key_events"] = kev
            results["paid_social_eng_pct"] = eng


def collect_campaign():
    r = run(["sessionCampaignName"], ["sessions", "keyEvents"])
    for row in r.rows:
        if row.dimension_values[0].value == CAMPAIGN:
            results["campaign_sessions"] = int(row.metric_values[0].value)
            results["campaign_key_events"] = int(float(row.metric_values[1].value))


def collect_daily_marker():
    # Daily zip_search counts, split at the campaign marker date.
    r = run(["date"], ["eventCount"], dim_filter=event_filter("zip_search"))
    marker = CAMPAIGN_MARKER.replace("-", "")
    before, before_days, after, after_days = 0, 0, 0, 0
    first_campaign_day = None
    for row in r.rows:
        d = row.dimension_values[0].value  # YYYYMMDD
        c = int(row.metric_values[0].value)
        if d < marker:
            before += c
            before_days += 1
        else:
            after += c
            after_days += 1
    results["daily_before_marker"] = round(before / before_days) if before_days else 0
    results["daily_after_marker"] = round(after / after_days) if after_days else 0
    # First day the campaign itself shows traffic (independent check of the marker)
    rc = run(["date"], ["sessions"], dim_filter=FilterExpression(filter=Filter(
        field_name="sessionCampaignName", string_filter=Filter.StringFilter(value=CAMPAIGN))))
    days = sorted(row.dimension_values[0].value for row in rc.rows
                  if int(row.metric_values[0].value) > 0)
    if days:
        d = days[0]
        results["campaign_first_day"] = f"{d[:4]}-{d[4:6]}-{d[6:]}"


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------
def reconcile():
    print("\n" + "=" * 72)
    print(f"NCYSA Find My Club - GA4 reconciliation")
    print(f"Property {PROPERTY.split('/')[-1]}   window {RANGE_START} .. {RANGE_END}")
    print(f"(club_click / coverage windows start {CLICK_START})")
    print("=" * 72)
    print(f"{'metric':32s}{'expected':>12s}{'actual':>12s}{'delta%':>9s}  status")
    print("-" * 72)
    worst = 0.0
    for key, exp in BASELINE.items():
        act = results.get(key)
        if act is None:
            print(f"{key:32s}{exp:>12}{'MISSING':>12s}{'':>9s}  [!] not collected")
            worst = max(worst, 999)
            continue
        delta = (act - exp) / exp * 100 if exp else 0.0
        worst = max(worst, abs(delta))
        flag = "ok" if abs(delta) <= 2 else ("close" if abs(delta) <= 8 else "CHECK")
        print(f"{key:32s}{exp:>12}{act:>12}{delta:>8.1f}%  {flag}")
    print("-" * 72)
    if "campaign_first_day" in results:
        cf = results["campaign_first_day"]
        note = "matches marker" if cf == CAMPAIGN_MARKER else f"marker is {CAMPAIGN_MARKER}"
        print(f"campaign first traffic day: {cf}  ({note})")
    if errors:
        print(f"\n{len(errors)} query error(s): " + ", ".join(errors))
    print(f"\nlargest deviation from baseline: {worst:.1f}%")
    print("A few percent drift is normal (GA4 keeps processing data for ~48h).")
    print("Anything in the CHECK column is worth a closer look before publishing.")
    return worst


def main():
    global client
    if not os.path.exists(KEY_FILE):
        print(f"ERROR: key file '{KEY_FILE}' not found. In GitHub Actions the "
              f"workflow writes the GA4_SA_KEY secret to this path.")
        sys.exit(2)
    client = get_client()
    print("Pulling GA4 reports (read-only)...")
    for name, fn in [
        ("zip_search", collect_zip_search),
        ("zip_breakdown", collect_zip_breakdown),
        ("fmc_page", collect_fmc_page),
        ("club_click", collect_club_click),
        ("coverage_gap", collect_coverage_gap),
        ("channels", collect_channels),
        ("campaign", collect_campaign),
        ("daily_marker", collect_daily_marker),
    ]:
        safe(name, fn)
    worst = reconcile()
    with open("ga_results.json", "w") as f:
        json.dump({"window": [RANGE_START, RANGE_END], "results": results,
                   "errors": errors}, f, indent=2)
    print("\nWrote ga_results.json (raw numbers, saved as a workflow artifact).")
    # Never fail the build on data drift during Phase A; this is a read-only report.
    sys.exit(0)


if __name__ == "__main__":
    main()
