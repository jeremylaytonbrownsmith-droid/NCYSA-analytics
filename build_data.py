#!/usr/bin/env python3
"""
NCYSA Find My Club - full data pull for the board report rebuild (Phase B).

Extends ga_pull.py's reconciliation collectors with everything
build_report.py needs to regenerate templates/board_report_template.html:
the daily zip_search series, every ZIP's search count, the club-click
breakdown, coverage-gap detail, channel/campaign stats, and page rank.

Read-only. Publishes nothing. Writes ga_report_data.json.

Auth/config are the same as ga_pull.py (GA4_KEY_FILE, GA4_PROPERTY_ID,
RANGE_START, RANGE_END, CLICK_START env vars).
"""

import os
import sys
import json
import datetime

import ga_pull as g

data = {}
errors = {}


def safe(name, fn):
    try:
        return fn()
    except Exception as e:  # noqa
        errors[name] = repr(e)
        print(f"  [!] {name} FAILED: {e}")
        return None


def fmt_date_label(d):
    return f"{d.strftime('%b')} {d.day}"


def collect_daily_series():
    r = g.run(["date"], ["eventCount"], dim_filter=g.event_filter("zip_search"))
    counts = {row.dimension_values[0].value: int(row.metric_values[0].value) for row in r.rows}
    start = datetime.date.fromisoformat(g.RANGE_START)
    end = datetime.date.fromisoformat(g.RANGE_END)
    daily, dates = [], []
    d = start
    while d <= end:
        key = d.strftime("%Y%m%d")
        daily.append(counts.get(key, 0))
        dates.append(fmt_date_label(d))
        d += datetime.timedelta(days=1)
    data["daily"] = daily
    data["dates"] = dates
    # marker index: first date >= CAMPAIGN_MARKER
    marker_date = datetime.date.fromisoformat(g.CAMPAIGN_MARKER)
    data["marker_index"] = (marker_date - start).days


def collect_zip_counts():
    r = g.run(["customEvent:search_zip"], ["eventCount"], dim_filter=g.event_filter("zip_search"))
    all_zips = {}
    for row in r.rows:
        z = row.dimension_values[0].value
        c = int(row.metric_values[0].value)
        if not g.is_valid_zip(z):
            continue
        all_zips[z] = all_zips.get(z, 0) + c
    nc_zips = {z: c for z, c in all_zips.items() if g.is_nc_zip(z)}
    data["zip_counts_all"] = all_zips
    data["zip_counts_nc"] = nc_zips


def collect_club_click_full():
    start = g.CLICK_START
    # searches in the click window (for the "N searches produced M clicks" line)
    r_search = g.run(["eventName"], ["eventCount"], start=start, dim_filter=g.event_filter("zip_search"))
    searches_in_window = int(r_search.rows[0].metric_values[0].value) if r_search.rows else 0

    r_clicks = g.run(["eventName"], ["eventCount"], start=start, dim_filter=g.event_filter("club_click"))
    total_clicks = int(r_clicks.rows[0].metric_values[0].value) if r_clicks.rows else 0

    r_names = g.run(["customEvent:club_name"], ["eventCount"], start=start, dim_filter=g.event_filter("club_click"))
    club_counts = {}
    for row in r_names.rows:
        name = row.dimension_values[0].value
        if name in ("(not set)", "", None):
            continue
        club_counts[name] = club_counts.get(name, 0) + int(row.metric_values[0].value)

    r_rank = g.run(["customEvent:club_rank"], ["eventCount"], start=start, dim_filter=g.event_filter("club_click"))
    rank_total, rank1 = 0, 0
    for row in r_rank.rows:
        c = int(row.metric_values[0].value)
        rank_total += c
        if row.dimension_values[0].value == "1":
            rank1 += c

    r_action = g.run(["customEvent:click_action"], ["eventCount"], start=start, dim_filter=g.event_filter("club_click"))
    action_total, website = 0, 0
    for row in r_action.rows:
        c = int(row.metric_values[0].value)
        action_total += c
        if row.dimension_values[0].value == "website":
            website += c

    data["club_click"] = {
        "searches_in_window": searches_in_window,
        "total_clicks": total_clicks,
        "club_counts": club_counts,
        "distinct_clubs": len(club_counts),
        "rank1_share_pct": round(100.0 * rank1 / rank_total, 1) if rank_total else 0.0,
        "website_share_pct": round(100.0 * website / action_total, 1) if action_total else 0.0,
        "window_start": start,
    }


def collect_coverage_gap_full():
    r = g.run(["customEvent:search_zip"], ["eventCount"], dim_filter=g.event_filter("coverage_gap"))
    total, nc_total = 0, 0
    nc_zips = set()
    for row in r.rows:
        z = row.dimension_values[0].value
        c = int(row.metric_values[0].value)
        total += c
        if g.is_nc_zip(z):
            nc_total += c
            nc_zips.add(z)
    data["coverage_gap"] = {
        "total": total,
        "nc_total": nc_total,
        "nc_distinct_zips": len(nc_zips),
    }


def collect_channels_full():
    r = g.run(["sessionDefaultChannelGroup"], ["sessions", "engagementRate", "keyEvents"])
    channels = {}
    for row in r.rows:
        ch = row.dimension_values[0].value
        channels[ch] = {
            "sessions": int(row.metric_values[0].value),
            "engagement_pct": round(100.0 * float(row.metric_values[1].value), 0),
            "key_events": int(float(row.metric_values[2].value)),
        }
    data["channels"] = channels


def collect_campaign_full():
    r = g.run(["sessionCampaignName"], ["sessions", "keyEvents"])
    for row in r.rows:
        if row.dimension_values[0].value == g.CAMPAIGN:
            data["campaign"] = {
                "sessions": int(row.metric_values[0].value),
                "key_events": int(float(row.metric_values[1].value)),
            }


def collect_page_rank():
    from google.analytics.data_v1beta.types import Filter as _Filter, FilterExpression as _FE

    r = g.run(["pagePath"], ["screenPageViews", "totalUsers", "keyEvents"])
    pages = {}
    for row in r.rows:
        path = row.dimension_values[0].value or ""
        if "find-my-club" in path.lower():
            continue  # merged below via a server-side filtered aggregate
        pages[path] = {
            "views": int(row.metric_values[0].value),
            "users": int(row.metric_values[1].value),
            "kev": int(float(row.metric_values[2].value)),
        }

    # totalUsers is a distinct-user count per row and is NOT safely additive
    # across dimension rows (a visitor to two URL variants would be double
    # counted). Get the FMC merge as one server-side aggregate instead.
    fmc_filter = _FE(filter=_Filter(
        field_name="pagePath",
        string_filter=_Filter.StringFilter(value="find-my-club", match_type=_Filter.StringFilter.MatchType.CONTAINS),
    ))
    rf = g.run([], ["screenPageViews", "totalUsers", "keyEvents"], dim_filter=fmc_filter)
    if rf.rows:
        fmc_views = int(rf.rows[0].metric_values[0].value)
        fmc_users = int(rf.rows[0].metric_values[1].value)
        fmc_kev = int(float(rf.rows[0].metric_values[2].value))
    else:
        fmc_views = fmc_users = fmc_kev = 0
    pages["__FMC__"] = {"views": fmc_views, "users": fmc_users, "kev": fmc_kev}

    def rank_of(key, metric):
        ordered = sorted(pages.items(), key=lambda kv: kv[1][metric], reverse=True)
        for i, (k, _) in enumerate(ordered, start=1):
            if k == key:
                return i
        return None

    data["fmc_page"] = {
        "views": fmc_views,
        "users": fmc_users,
        "key_events": fmc_kev,
        "rank_by_views": rank_of("__FMC__", "views"),
        "rank_by_users": rank_of("__FMC__", "users"),
        "rank_by_key_events": rank_of("__FMC__", "kev"),
    }


def main():
    if not os.path.exists(g.KEY_FILE):
        print(f"ERROR: key file '{g.KEY_FILE}' not found.")
        sys.exit(2)
    g.client = g.get_client()
    print("Pulling full GA4 dataset for board report rebuild (read-only)...")

    # Base reconciliation numbers (zip totals, fmc page merge check, club_click
    # summary, coverage_gap summary, channels, campaign) -- reuse ga_pull's own
    # collectors so both scripts agree on the same numbers.
    for name, fn in [
        ("zip_search", g.collect_zip_search),
        ("zip_breakdown", g.collect_zip_breakdown),
        ("club_click", g.collect_club_click),
        ("coverage_gap", g.collect_coverage_gap),
        ("daily_marker", g.collect_daily_marker),
    ]:
        safe(name, fn)
    data["baseline_check"] = dict(g.results)

    for name, fn in [
        ("daily_series", collect_daily_series),
        ("zip_counts", collect_zip_counts),
        ("club_click_full", collect_club_click_full),
        ("coverage_gap_full", collect_coverage_gap_full),
        ("channels_full", collect_channels_full),
        ("campaign_full", collect_campaign_full),
        ("page_rank", collect_page_rank),
    ]:
        safe(name, fn)

    data["window"] = {
        "start": g.RANGE_START,
        "end": g.RANGE_END,
        "click_start": g.CLICK_START,
        "campaign_marker": g.CAMPAIGN_MARKER,
    }
    data["errors"] = errors

    out_path = "ga_report_data.json"
    with open(out_path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"\nWrote {out_path}.")
    if errors:
        print(f"{len(errors)} collector(s) failed: {', '.join(errors)}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
