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
    # One query gets both searches (eventCount) and distinct users (totalUsers)
    # per ZIP; the per-zip totalUsers value IS safe here since each row is its
    # own independent dimension value (no merging across rows involved).
    r = g.run(["customEvent:search_zip"], ["eventCount", "totalUsers"], dim_filter=g.event_filter("zip_search"))
    all_zips, detail = {}, {}
    for row in r.rows:
        z = row.dimension_values[0].value
        if not g.is_valid_zip(z):
            continue
        c = int(row.metric_values[0].value)
        u = int(row.metric_values[1].value)
        all_zips[z] = all_zips.get(z, 0) + c
        prev = detail.get(z, {"searches": 0, "users": 0})
        detail[z] = {"searches": prev["searches"] + c, "users": prev["users"] + u, "nc": g.is_nc_zip(z)}
    nc_zips = {z: c for z, c in all_zips.items() if g.is_nc_zip(z)}
    data["zip_counts_all"] = all_zips
    data["zip_counts_nc"] = nc_zips
    data["zip_detail"] = detail


def collect_nearest_club():
    # Which club GA4 returned as nearest, across ALL zip_search events (not
    # scoped to the click window) -- and separately, distance to that club in
    # miles, bucketed by the tracked value. Both come from customEvent params
    # on the zip_search event itself, confirmed via GA4 property metadata.
    r = g.run(["customEvent:nearest_club_name"], ["eventCount", "totalUsers"], dim_filter=g.event_filter("zip_search"))
    clubs = {}
    for row in r.rows:
        name = row.dimension_values[0].value
        if name in ("(not set)", "", None):
            continue
        clubs[name] = {
            "events": int(row.metric_values[0].value),
            "users": int(row.metric_values[1].value),
        }
    data["nearest_club"] = clubs

    r2 = g.run(["customEvent:nearest_club_distance_miles"], ["eventCount", "totalUsers"], dim_filter=g.event_filter("zip_search"))
    distances = []
    for row in r2.rows:
        val = row.dimension_values[0].value
        if val in ("(not set)", "", None):
            continue
        try:
            miles = float(val)
        except ValueError:
            continue
        distances.append({
            "miles": miles,
            "events": int(row.metric_values[0].value),
            "users": int(row.metric_values[1].value),
        })
    distances.sort(key=lambda d: d["miles"])
    data["nearest_club_distance"] = distances


def collect_club_click_full():
    start = g.CLICK_START
    # searches in the click window (for the "N searches produced M clicks" line)
    r_search = g.run(["eventName"], ["eventCount"], start=start, dim_filter=g.event_filter("zip_search"))
    searches_in_window = int(r_search.rows[0].metric_values[0].value) if r_search.rows else 0

    # Aggregate clicks + TRUE distinct users (single filtered row, not summed
    # across a dimension breakdown -- see the totalUsers note elsewhere).
    r_clicks = g.run(["eventName"], ["eventCount", "totalUsers"], start=start, dim_filter=g.event_filter("club_click"))
    if r_clicks.rows:
        total_clicks = int(r_clicks.rows[0].metric_values[0].value)
        total_click_users = int(r_clicks.rows[0].metric_values[1].value)
    else:
        total_clicks = total_click_users = 0

    r_names = g.run(["customEvent:club_name"], ["eventCount", "totalUsers"], start=start, dim_filter=g.event_filter("club_click"))
    club_counts, club_detail = {}, {}
    for row in r_names.rows:
        name = row.dimension_values[0].value
        if name in ("(not set)", "", None):
            continue
        c = int(row.metric_values[0].value)
        u = int(row.metric_values[1].value)
        club_counts[name] = club_counts.get(name, 0) + c
        club_detail[name] = {"clicks": club_counts[name], "users": u}

    r_rank = g.run(["customEvent:club_rank"], ["eventCount"], start=start, dim_filter=g.event_filter("club_click"))
    rank_total, rank1 = 0, 0
    rank_detail = {}
    for row in r_rank.rows:
        val = row.dimension_values[0].value
        c = int(row.metric_values[0].value)
        rank_total += c
        if val == "1":
            rank1 += c
        try:
            rank_detail[int(val)] = c
        except (TypeError, ValueError):
            pass  # "(not set)" or similar -- excluded from the rank table

    r_action = g.run(["customEvent:click_action"], ["eventCount", "totalUsers"], start=start, dim_filter=g.event_filter("club_click"))
    action_total, website = 0, 0
    action_detail = {}
    for row in r_action.rows:
        val = row.dimension_values[0].value or "(not set)"
        c = int(row.metric_values[0].value)
        u = int(row.metric_values[1].value)
        action_total += c
        if val == "website":
            website += c
        action_detail[val] = {"clicks": c, "users": u}

    data["club_click"] = {
        "searches_in_window": searches_in_window,
        "total_clicks": total_clicks,
        "total_click_users": total_click_users,
        "club_counts": club_counts,
        "club_detail": club_detail,
        "distinct_clubs": len(club_counts),
        "rank1_share_pct": round(100.0 * rank1 / rank_total, 1) if rank_total else 0.0,
        "rank1_clicks": rank1,
        "rank_detail": {str(k): v for k, v in sorted(rank_detail.items())},
        "website_share_pct": round(100.0 * website / action_total, 1) if action_total else 0.0,
        "action_detail": action_detail,
        "window_start": start,
    }


def collect_click_zips():
    # Which ZIP the family searched from, among club_click events (i.e. where
    # clicking families are located), not to be confused with zip_counts_*
    # (all searches, click or not).
    start = g.CLICK_START
    r = g.run(["customEvent:search_zip"], ["eventCount", "totalUsers"], start=start, dim_filter=g.event_filter("club_click"))
    detail = {}
    for row in r.rows:
        z = row.dimension_values[0].value
        if not g.is_valid_zip(z):
            continue
        c = int(row.metric_values[0].value)
        u = int(row.metric_values[1].value)
        prev = detail.get(z, {"clicks": 0, "users": 0})
        detail[z] = {"clicks": prev["clicks"] + c, "users": prev["users"] + u, "nc": g.is_nc_zip(z)}
    data["click_zips"] = detail


def collect_coverage_gap_full():
    r = g.run(["customEvent:search_zip"], ["eventCount"], dim_filter=g.event_filter("coverage_gap"))
    total, nc_total = 0, 0
    nc_zips = set()
    zip_detail = {}
    for row in r.rows:
        z = row.dimension_values[0].value
        c = int(row.metric_values[0].value)
        # Malformed zip strings still represent real coverage_gap events --
        # only exclude them from the per-zip breakdown table, not the total
        # (matches ga_pull.py's collect_coverage_gap(), so both scripts agree
        # on the headline event count).
        total += c
        if not g.is_valid_zip(z):
            continue
        is_nc = g.is_nc_zip(z)
        if is_nc:
            nc_total += c
            nc_zips.add(z)
        zip_detail[z] = {"events": zip_detail.get(z, {"events": 0})["events"] + c, "nc": is_nc}

    # Nearest club shown / distance to it, scoped to coverage_gap events
    # specifically (a coverage gap still has a "nearest" club -- it's just
    # further than the 40mi cutoff).
    r_club = g.run(["customEvent:nearest_club_name"], ["eventCount", "totalUsers"], dim_filter=g.event_filter("coverage_gap"))
    gap_clubs = {}
    for row in r_club.rows:
        name = row.dimension_values[0].value
        if name in ("(not set)", "", None):
            continue
        gap_clubs[name] = {"events": int(row.metric_values[0].value), "users": int(row.metric_values[1].value)}

    r_dist = g.run(["customEvent:nearest_club_distance_miles"], ["eventCount", "totalUsers"], dim_filter=g.event_filter("coverage_gap"))
    gap_distances = []
    for row in r_dist.rows:
        val = row.dimension_values[0].value
        if val in ("(not set)", "", None):
            continue
        try:
            miles = float(val)
        except ValueError:
            continue
        gap_distances.append({"miles": miles, "events": int(row.metric_values[0].value), "users": int(row.metric_values[1].value)})
    gap_distances.sort(key=lambda d: d["miles"])

    data["coverage_gap"] = {
        "total": total,
        "nc_total": nc_total,
        "nc_distinct_zips": len(nc_zips),
        "zip_detail": zip_detail,
        "nearest_club": gap_clubs,
        "nearest_club_distance": gap_distances,
    }


def collect_channels_full():
    r = g.run(["sessionDefaultChannelGroup"],
              ["sessions", "engagedSessions", "engagementRate", "keyEvents", "sessionKeyEventRate",
               "userEngagementDuration"])
    channels = {}
    for row in r.rows:
        ch = row.dimension_values[0].value
        sessions = int(row.metric_values[0].value)
        engagement_duration = float(row.metric_values[5].value)
        channels[ch] = {
            "sessions": sessions,
            "engaged_sessions": int(row.metric_values[1].value),
            "engagement_pct": round(100.0 * float(row.metric_values[2].value), 0),
            "key_events": int(float(row.metric_values[3].value)),
            "session_key_event_rate_pct": round(100.0 * float(row.metric_values[4].value), 0),
            "avg_engagement_sec": round(engagement_duration / sessions, 1) if sessions else 0.0,
        }
    data["channels"] = channels


def collect_first_user_channels():
    # Base row per channel: total users / event count / key events, scoped by
    # FIRST-TOUCH channel (where a user originally came from), not session
    # channel. New/returning split needs a second query (see below) --
    # totalUsers under a newVsReturning breakdown is not the same denominator
    # as a plain per-channel totalUsers subtraction.
    r = g.run(["firstUserDefaultChannelGroup"], ["totalUsers", "eventCount", "keyEvents"])
    channels = {}
    for row in r.rows:
        ch = row.dimension_values[0].value
        channels[ch] = {
            "total_users": int(row.metric_values[0].value),
            "new_users": 0,
            "returning_users": 0,
            "event_count": int(row.metric_values[1].value),
            "key_events": int(float(row.metric_values[2].value)),
        }
    r2 = g.run(["firstUserDefaultChannelGroup", "newVsReturning"], ["totalUsers"])
    for row in r2.rows:
        ch = row.dimension_values[0].value
        bucket = row.dimension_values[1].value
        if ch not in channels:
            continue
        u = int(row.metric_values[0].value)
        if bucket == "new":
            channels[ch]["new_users"] = u
        elif bucket == "returning":
            channels[ch]["returning_users"] = u
    data["first_user_channels"] = channels


def collect_campaign_full():
    r = g.run(["sessionCampaignName"], ["sessions", "engagementRate", "keyEvents"])
    campaigns = {}
    for row in r.rows:
        name = row.dimension_values[0].value
        campaigns[name] = {
            "sessions": int(row.metric_values[0].value),
            "engagement_pct": round(100.0 * float(row.metric_values[1].value), 0),
            "key_events": int(float(row.metric_values[2].value)),
        }
        if name == g.CAMPAIGN:
            data["campaign"] = {
                "sessions": int(row.metric_values[0].value),
                "key_events": int(float(row.metric_values[2].value)),
            }
    data["campaigns_full"] = campaigns


def collect_page_rank():
    # Exact match on "/find-my-club/" only -- see the note on ga_pull.py's
    # collect_fmc_page(). Case/prefix variants ("/Find-My-Club/",
    # "/ncsoccer/find-my-club/", the legacy "/find-your-ncysa-club/") are
    # real distinct rows and stay out of both the ranking and the official
    # total, exactly like the board report's own workbook export treats them.
    r = g.run(["pagePath"], ["screenPageViews", "totalUsers", "keyEvents"])
    pages = {}
    all_rows = []  # for top_pages / fmc_variants below
    for row in r.rows:
        path = row.dimension_values[0].value or ""
        views = int(row.metric_values[0].value)
        users = int(row.metric_values[1].value)
        kev = int(float(row.metric_values[2].value))
        all_rows.append({"path": path, "views": views, "users": users, "kev": kev})
        if path == "/find-my-club/":
            continue  # this is the FMC row itself; included below by exact key
        pages[path] = {"views": views, "users": users, "kev": kev}

    fmc_row = next((r_ for r_ in all_rows if r_["path"] == "/find-my-club/"), None)
    fmc_views = fmc_row["views"] if fmc_row else 0
    fmc_users = fmc_row["users"] if fmc_row else 0
    fmc_kev = fmc_row["kev"] if fmc_row else 0
    pages["/find-my-club/"] = {"views": fmc_views, "users": fmc_users, "kev": fmc_kev}

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
        "rank_by_views": rank_of("/find-my-club/", "views"),
        "rank_by_users": rank_of("/find-my-club/", "users"),
        "rank_by_key_events": rank_of("/find-my-club/", "kev"),
    }

    # Top 25 by views (raw individual paths, not merged) for the "Top Pages"
    # workbook tab / docx table, and a separate breakdown of every URL
    # variant that could plausibly be "Find My Club" (informational only).
    top = sorted(all_rows, key=lambda r_: -r_["views"])[:25]
    data["top_pages"] = [{"path": r_["path"], "views": r_["views"], "users": r_["users"], "kev": r_["kev"]} for r_ in top]
    variants = [r_ for r_ in all_rows if "find-my-club" in r_["path"].lower() or "find-your" in r_["path"].lower()
                or "find-a-ncysa" in r_["path"].lower() or "find-your-team" in r_["path"].lower()]
    variants.sort(key=lambda r_: -r_["views"])
    data["fmc_variants"] = [{"path": r_["path"], "views": r_["views"], "users": r_["users"]} for r_ in variants]


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
        ("nearest_club", collect_nearest_club),
        ("club_click_full", collect_club_click_full),
        ("click_zips", collect_click_zips),
        ("coverage_gap_full", collect_coverage_gap_full),
        ("channels_full", collect_channels_full),
        ("first_user_channels", collect_first_user_channels),
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
