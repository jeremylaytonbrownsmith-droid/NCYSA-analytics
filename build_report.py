#!/usr/bin/env python3
"""
NCYSA Find My Club - board report builder (Phase B, Step 2).

Fills templates/board_report_template.html from ga_report_data.json
(produced by build_data.py) via targeted, anchored substitutions -- every
byte of markup/CSS/JS outside the substituted spans is left untouched.

Regenerates: the daily/dates JS arrays, the sparkline SVG path/polyline and
June-11 marker position, the before/after-campaign caption, the 5 stat-band
numbers and the page-rank tile, the campaign/channel cards, the NC map dots
(via a fixed lon/lat -> cx/cy affine transform fit once against the original
template's ~600 dots), the top-10 ZIP and top-10 club bar lists, the
coverage-gap paragraph, the page-views paragraph, and the date ranges.

Locked and left untouched: page layout/CSS/JS, the map's state outline
path, the board-meeting date in the eyebrow, the seasonality caveat, the
Jul-8 tracking-start footnote, the campaign-attribution note, and the
"no spend-vs-social critique" editorial stance -- this script never writes
new prose, only substitutes numbers into the existing sentences.

Usage: python3 build_report.py [data.json] [template.html] [out.html]
"""

import sys
import re
import json
import math
import datetime

import zipcodes

TEMPLATE_PATH = sys.argv[2] if len(sys.argv) > 2 else "templates/board_report_template.html"
DATA_PATH = sys.argv[1] if len(sys.argv) > 1 else "ga_report_data.json"
OUT_PATH = sys.argv[3] if len(sys.argv) > 3 else "build/board_report.html"

# Fit once (2026-07-22) by least-squares against the ~618 dots baked into the
# original template, using zipcodes-package centroids: cx = A*lon+B*lat+C,
# cy = D*lon+E*lat+F. Reproduces the original dots within ~0.13px at the 95th
# percentile (a handful of PO-Box/military-base ZIPs run 2-15px off -- normal
# centroid disagreement between geocoding datasets for those, not a fit bug).
AFFINE = {
    "A": 108.293504, "B": 0.050936, "C": 9149.769790,
    "D": -0.003658, "E": -123.562591, "F": 4540.631396,
}

MONTHS_FULL = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
MONTHS_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

warnings = []


def warn(msg):
    warnings.append(msg)
    print(f"  [!] EDITORIAL CHECK: {msg}")


def commas(n):
    return f"{n:,}"


def long_date(iso, with_year=False):
    d = datetime.date.fromisoformat(iso)
    s = f"{MONTHS_FULL[d.month]} {d.day}"
    return f"{s}, {d.year}" if with_year else s


def short_date(iso, with_year=False):
    d = datetime.date.fromisoformat(iso)
    s = f"{MONTHS_ABBR[d.month]} {d.day}"
    return f"{s}, {d.year}" if with_year else s


def month_range(start_iso, end_iso):
    s = datetime.date.fromisoformat(start_iso)
    e = datetime.date.fromisoformat(end_iso)
    return f"{MONTHS_FULL[s.month]} &ndash; {MONTHS_FULL[e.month]} {e.year}"


def zip_city(z):
    m = zipcodes.matching(z)
    return m[0]["city"] if m else z


def sub_one(html, pattern, replacement, flags=0):
    new_html, n = re.subn(pattern, replacement, html, count=1, flags=flags)
    if n != 1:
        raise RuntimeError(f"Anchor not found (expected exactly 1 match): {pattern[:80]}...")
    return new_html


def build():
    data = json.load(open(DATA_PATH))
    html = open(TEMPLATE_PATH).read()

    win = data["window"]
    bc = data["baseline_check"]
    daily = data["daily"]
    dates = data["dates"]
    n = len(daily)
    marker_index = data["marker_index"]

    # ---- sparkline geometry -------------------------------------------------
    max_count = max(daily) if daily else 1
    xs = [6 + i / (n - 1) * 988 for i in range(n)]
    ys = [214 - (c / max_count) * 206 for c in daily]
    points_str = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    path_d = f"M 6,214 L {points_str} L 994,214 Z"
    marker_x = 6 + marker_index / (n - 1) * 988
    text_x = marker_x - 10

    daily_before = bc["daily_before_marker"]
    daily_after = bc["daily_after_marker"]
    lift = daily_after / daily_before if daily_before else 0
    if not (3 <= lift <= 8):
        warn(f"before/after lift is {lift:.1f}x -- caption text still says 'a 5x lift', review wording")

    # ---- stat band / hero -----------------------------------------------
    zip_total = bc["zip_search_events"]
    zip_distinct_all = len(data["zip_counts_all"])
    zip_distinct_nc = len(data["zip_counts_nc"])
    nc_share_pct = round(100.0 * sum(data["zip_counts_nc"].values()) / sum(data["zip_counts_all"].values()))
    club_click_total = data["club_click"]["total_clicks"]
    club_distinct = data["club_click"]["distinct_clubs"]
    rank_views = data["fmc_page"]["rank_by_views"]
    rank_users = data["fmc_page"]["rank_by_users"]
    rank_kev = data["fmc_page"]["rank_by_key_events"]
    if rank_views != 3:
        warn(f"FMC is now #{rank_views} by views (was #3) -- H2 'A top-three page in one season' may need rewording")
    if rank_kev != 1:
        warn(f"FMC is now #{rank_kev} by key events (was #1) -- 'by a wide margin' phrasing needs review")

    # ---- campaign / channels ----------------------------------------------
    campaign = data["campaign"]
    paid_search = data["channels"].get("Paid Search", {"sessions": 0, "engagement_pct": 0, "key_events": 0})
    paid_social = data["channels"].get("Paid Social", {"sessions": 0, "engagement_pct": 0, "key_events": 0})

    # ---- club click -----------------------------------------------------
    cc = data["club_click"]
    if cc["rank1_share_pct"] < 40:
        warn(f"closest-club share is now {cc['rank1_share_pct']}% -- 'confirming proximity drives the decision' claim needs review")

    # ---- coverage gap -----------------------------------------------------
    cov = data["coverage_gap"]

    # ---- map dots -----------------------------------------------------
    nc_items = sorted(data["zip_counts_nc"].items(), key=lambda kv: -kv[1])
    circle_parts = []
    unresolved = []
    for z, cnt in nc_items:
        m = zipcodes.matching(z)
        if not m:
            unresolved.append(z)
            continue
        lon, lat = float(m[0]["long"]), float(m[0]["lat"])
        cx = AFFINE["A"] * lon + AFFINE["B"] * lat + AFFINE["C"]
        cy = AFFINE["D"] * lon + AFFINE["E"] * lat + AFFINE["F"]
        r = max(1.08 * math.sqrt(cnt) + 1.62, 2.5)
        circle_parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" data-zip="{z}" data-n="{cnt}"/>')
    if unresolved:
        warn(f"{len(unresolved)} NC zip(s) not found in zipcodes package, dropped from map "
             f"(still counted in the '{zip_distinct_nc} North Carolina ZIPs' text stat): {unresolved}")
    dots_html = "".join(circle_parts)
    plotted_nc_count = len(circle_parts)  # map caption must match what's actually rendered

    # ---- top-10 zip bars -----------------------------------------------
    top_zips = sorted(data["zip_counts_all"].items(), key=lambda kv: -kv[1])[:10]
    zip_max = top_zips[0][1] if top_zips else 1
    zip_rows = []
    for z, cnt in top_zips:
        w = round(100.0 * cnt / zip_max)
        city = zip_city(z)
        zip_rows.append(
            f'<div class="fmcr-bar-row"><span class="fmcr-bar-label">{z} <em>{city}</em></span>'
            f'<span class="fmcr-bar-track"><span class="fmcr-bar-fill" data-w="{w}"></span></span>'
            f'<span class="fmcr-bar-val">{cnt}</span></div>'
        )
    zip_rows_html = "      " + zip_rows[0] + "\n" + "\n".join(zip_rows[1:])

    # ---- top-10 club bars -----------------------------------------------
    top_clubs = sorted(cc["club_counts"].items(), key=lambda kv: -kv[1])[:10]
    club_max = top_clubs[0][1] if top_clubs else 1
    club_rows = []
    for name, cnt in top_clubs:
        w = round(100.0 * cnt / club_max)
        club_rows.append(
            f'<div class="fmcr-bar-row"><span class="fmcr-bar-label">{name}</span>'
            f'<span class="fmcr-bar-track"><span class="fmcr-bar-fill fmcr-red" data-w="{w}"></span></span>'
            f'<span class="fmcr-bar-val">{cnt}</span></div>'
        )
    club_rows_html = "      " + club_rows[0] + "\n" + "\n".join(club_rows[1:])

    # ---- page views section -----------------------------------------------
    fmc = data["fmc_page"]

    # =========================================================================
    # Apply substitutions
    # =========================================================================

    # JS daily / dates arrays
    html = sub_one(
        html, r"var daily = \[[^\]]*\];",
        "var daily = [" + ", ".join(str(x) for x in daily) + "];",
    )
    html = sub_one(
        html, r'var dates = \[[^\]]*\];',
        'var dates = [' + ", ".join(f'"{d}"' for d in dates) + '];',
    )

    # SVG area path + polyline + marker + marker label x
    html = sub_one(html, r'<path d="M 6,214 L .*?" fill="rgba\(237,195,44,\.18\)"/>',
                   f'<path d="{path_d}" fill="rgba(237,195,44,.18)"/>', flags=re.S)
    html = sub_one(html, r'<polyline points="[^"]*" fill="none" stroke="#edc32c" stroke-width="2\.5"/>',
                   f'<polyline points="{points_str}" fill="none" stroke="#edc32c" stroke-width="2.5"/>')
    html = sub_one(
        html, r'<line x1="[\d.]+" y1="8" x2="[\d.]+" y2="214" stroke="#b82f2f"',
        f'<line x1="{marker_x:.1f}" y1="8" x2="{marker_x:.1f}" y2="214" stroke="#b82f2f"',
    )
    html = sub_one(
        html, r'<text x="[\d.]+" y="26" fill="#f9f7f7"',
        f'<text x="{text_x:.1f}" y="26" fill="#f9f7f7"',
    )

    # hero sub + period
    html = sub_one(
        html,
        r'One tool, one campaign, and [\d,]+ families searching for a place to play\. '
        r'Here is what Google Analytics recorded from [^.]*\.',
        f'One tool, one campaign, and {commas(zip_total)} families searching for a place to play. '
        f'Here is what Google Analytics recorded from {long_date(win["start"])} to {long_date(win["end"], with_year=True)}.',
    )
    html = sub_one(
        html, r'Daily ZIP searches &middot; [^&]*&ndash; \w+ \d{4} &middot;',
        f'Daily ZIP searches &middot; {month_range(win["start"], win["end"])} &middot;',
    )

    # before/after caption
    html = sub_one(
        html, r'Searches averaged <b>\d+ per day</b> before the campaign and <b>\d+ per day</b> after',
        f'Searches averaged <b>{daily_before} per day</b> before the campaign and <b>{daily_after} per day</b> after',
    )

    # stat band
    html = sub_one(html, r'data-n="8125"', f'data-n="{zip_total}"')
    html = sub_one(html, r'data-n="856"', f'data-n="{zip_distinct_all}"')
    html = sub_one(html, r'data-n="2314"', f'data-n="{club_click_total}"')
    html = sub_one(html, r'data-n="105"', f'data-n="{club_distinct}"')
    html = sub_one(html, r'<b>#3</b><span>page on ncsoccer\.org</span>', f'<b>#{rank_views}</b><span>page on ncsoccer.org</span>')

    # campaign paragraph
    html = sub_one(
        html, r'The campaign has driven <strong>[\d,]+ sessions</strong> and <strong>[\d,]+ key events</strong>',
        f'The campaign has driven <strong>{commas(campaign["sessions"])} sessions</strong> '
        f'and <strong>{commas(campaign["key_events"])} key events</strong>',
    )
    html = sub_one(
        html,
        r'<div class="fmcr-card"><h3>Paid Search</h3><div class="fmcr-big">\d+%</div>'
        r'<small>engagement rate &middot; [\d,]+ sessions &middot; [\d,]+ key events\.',
        f'<div class="fmcr-card"><h3>Paid Search</h3><div class="fmcr-big">{int(paid_search["engagement_pct"])}%</div>'
        f'<small>engagement rate &middot; {commas(paid_search["sessions"])} sessions &middot; '
        f'{commas(paid_search["key_events"])} key events.',
    )
    html = sub_one(
        html,
        r'<div class="fmcr-card fmcr-alt"><h3>Paid Social</h3><div class="fmcr-big">\d+%</div>'
        r'<small>engagement rate &middot; [\d,]+ sessions &middot; [\d,]+ key events\.',
        f'<div class="fmcr-card fmcr-alt"><h3>Paid Social</h3><div class="fmcr-big">{int(paid_social["engagement_pct"])}%</div>'
        f'<small>engagement rate &middot; {commas(paid_social["sessions"])} sessions &middot; '
        f'{commas(paid_social["key_events"])} key events.',
    )

    # zip intro paragraph
    html = sub_one(
        html,
        r'Families in <strong>[\d,]+ ZIP codes</strong> have used the tool &mdash; [\d,]+ of them '
        r'North Carolina ZIPs covering \d+% of all searches\.',
        f'Families in <strong>{commas(zip_distinct_all)} ZIP codes</strong> have used the tool &mdash; '
        f'{commas(zip_distinct_nc)} of them North Carolina ZIPs covering {nc_share_pct}% of all searches.',
    )

    # map dots + caption
    html = sub_one(
        html, r'<g class="fmcr-map-dots" id="fmcr-map-dots">.*?</g>',
        f'<g class="fmcr-map-dots" id="fmcr-map-dots">{dots_html}</g>', flags=re.S,
    )
    html = sub_one(
        html, r'\d+ North Carolina ZIP codes with at least one search &middot; [^<]*',
        f'{plotted_nc_count} North Carolina ZIP codes with at least one search &middot; '
        f'{short_date(win["start"])} &ndash; {short_date(win["end"], with_year=True)}',
    )

    # top-10 zip bars
    html = sub_one(
        html,
        r'      <div class="fmcr-bar-row"><span class="fmcr-bar-label">\d{5} <em>.*?</em></span>.*?'
        r'<span class="fmcr-bar-val">\d+</span></div>(\n<div class="fmcr-bar-row">.*?</div>){9}',
        zip_rows_html, flags=re.S,
    )

    # club click paragraph
    html = sub_one(
        html,
        r'In roughly two weeks, <strong>[\d,]+ searches produced [\d,]+ clicks</strong> to club websites and '
        r'emails &mdash; about one club visit per search\. The closest club earns \d+% of clicks',
        f'In roughly two weeks, <strong>{commas(cc["searches_in_window"])} searches produced '
        f'{commas(cc["total_clicks"])} clicks</strong> to club websites and emails &mdash; about one club '
        f'visit per search. The closest club earns {round(cc["rank1_share_pct"])}% of clicks',
    )
    html = sub_one(
        html, r'\d+ different member clubs have already received traffic',
        f'{club_distinct} different member clubs have already received traffic',
    )

    # top-10 club bars
    html = sub_one(
        html,
        r'      <div class="fmcr-bar-row"><span class="fmcr-bar-label">[^<]*</span>'
        r'<span class="fmcr-bar-track"><span class="fmcr-bar-fill fmcr-red".*?</div>'
        r'(\n<div class="fmcr-bar-row"><span class="fmcr-bar-label">[^<]*</span>'
        r'<span class="fmcr-bar-track"><span class="fmcr-bar-fill fmcr-red".*?</div>){9}',
        club_rows_html, flags=re.S,
    )

    # coverage paragraph
    html = sub_one(
        html,
        r'Of \d+ events recorded so far, nearly all trace to out-of-state visitors exploring the tool\. Only '
        r'<strong>\d+ events from \d+ NC-coded ZIPs</strong> appeared',
        f'Of {commas(cov["total"])} events recorded so far, nearly all trace to out-of-state visitors exploring '
        f'the tool. Only <strong>{commas(cov["nc_total"])} events from {cov["nc_distinct_zips"]} NC-coded ZIPs</strong> appeared',
    )

    # page views paragraph
    kev_clause = (f"#{rank_kev} by a wide margin in key events" if rank_kev == 1
                  else f"#{rank_kev} in key events")
    html = sub_one(
        html,
        r'Find My Club drew <strong>[\d,]+ views from [\d,]+ users</strong> since January &mdash; the #\d+ page '
        r'on ncsoccer\.org by views, #\d+ by unique visitors, and #\d+ by a wide margin in key events \([\d,]+\)\.',
        f'Find My Club drew <strong>{commas(fmc["views"])} views from {commas(fmc["users"])} users</strong> '
        f'since January &mdash; the #{rank_views} page on ncsoccer.org by views, #{rank_users} by unique visitors, '
        f'and {kev_clause} ({commas(fmc["key_events"])}).',
    )

    # footer date range
    html = sub_one(
        html, r'Source: Google Analytics 4, NCYSA property, [^.]*\.',
        f'Source: Google Analytics 4, NCYSA property, {short_date(win["start"])} &ndash; '
        f'{short_date(win["end"], with_year=True)}.',
    )

    return html


def main():
    html = build()
    import os
    os.makedirs("build", exist_ok=True)
    with open(OUT_PATH, "w") as f:
        f.write(html)
    print(f"\nWrote {OUT_PATH}")
    if warnings:
        print(f"\n{len(warnings)} editorial check(s) flagged above -- numbers are correct, "
              f"but review the surrounding prose before publishing.")


if __name__ == "__main__":
    main()
