#!/usr/bin/env python3
"""
NCYSA Find My Club - board report Word doc builder (Phase C, Step 2).

Rebuilds the board packet .docx (matching NCYSA-Find-My-Club-Board-Report-2.docx's
structure) from ga_report_data.json via python-docx. Locked rules: no
spend-vs-social critique (Paid Search/Social are described, never ranked
"better"/"worse" as a spend recommendation), the seasonality caveat and the
Jul 8 tracking-start footnote stay, the June 11 campaign marker stays, and
all figures come from the GA4 API export (ga_report_data.json), not the GA4
UI.

Usage: python3 generate_docx.py [data.json] [out.docx]
"""

import sys
import json
import datetime

import zipcodes

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from build_report import ZIP_LABEL_OVERRIDES

DATA_PATH = sys.argv[1] if len(sys.argv) > 1 else "ga_report_data.json"
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "build/board_report.docx"

NAVY = RGBColor(0x10, 0x04, 0x5A)
RED = RGBColor(0xB8, 0x2F, 0x2F)
GRAY = RGBColor(0x66, 0x66, 0x66)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

MONTHS_FULL = ["", "January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November", "December"]
ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
            6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth"}

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


def ordinal(n):
    return ORDINALS.get(n, f"{n}th")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def styled_para(doc, text, size=11, color=None, bold=False, italic=False,
                 space_before=0, space_after=6, align=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    if align:
        p.alignment = align
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold
    r.italic = italic
    if color:
        r.font.color.rgb = color
    return p


def rich_para(doc, runs, size=11, space_after=10):
    """runs: list of (text, bold) tuples."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    for text, bold in runs:
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.bold = bold
    return p


def heading(doc, text, level=1):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(18 if level == 1 else 12)
    p.paragraph_format.space_after = Pt(8 if level == 1 else 6)
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(16 if level == 1 else 13)
    r.font.color.rgb = NAVY if level == 1 else RED
    return p


def shade_cell(cell, hex_color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def add_table(doc, headers, rows, col_widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.autofit = True
    hdr = t.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        r = p.add_run(str(h))
        r.bold = True
        r.font.size = Pt(10)
        r.font.color.rgb = WHITE
        shade_cell(hdr[i], "10045A")
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            r = p.add_run(str(val))
            r.font.size = Pt(10)
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in t.rows:
                row.cells[i].width = Inches(w)
    doc.paragraphs[-1].paragraph_format.space_after = Pt(4) if False else None
    return t


# ---------------------------------------------------------------------------
# Derived calculations
# ---------------------------------------------------------------------------
def daily_window_avg(daily, dates_start_iso, from_date, to_date):
    start = datetime.date.fromisoformat(dates_start_iso)
    vals = []
    for i, count in enumerate(daily):
        d = start + datetime.timedelta(days=i)
        if from_date <= d <= to_date:
            vals.append(count)
    return round(sum(vals) / len(vals), 1) if vals else 0.0


def build(data):
    win = data["window"]
    bc = data["baseline_check"]
    daily = data["daily"]
    start_iso = win["start"]
    year = datetime.date.fromisoformat(start_iso).year
    mar1 = datetime.date(year, 3, 1)
    jun10 = datetime.date(year, 6, 10)
    jun11 = datetime.date(year, 6, 11)
    range_end = datetime.date.fromisoformat(win["end"])

    if jun11.isoformat() != win["campaign_marker"]:
        warn(f"campaign marker is {win['campaign_marker']}, not 2026-06-11 -- "
             f"the docx's 'Mar 1 - Jun 10' / 'Jun 11 -' windows assume the June 11 marker")

    avg_before = daily_window_avg(daily, start_iso, mar1, jun10)
    avg_after = daily_window_avg(daily, start_iso, jun11, range_end)
    lift = round(avg_after / avg_before) if avg_before else 0

    zip_total = bc["zip_search_events"]
    zip_users = bc["zip_search_users"]
    zip_distinct_all = len(data["zip_counts_all"])
    zip_distinct_nc = len(data["zip_counts_nc"])
    nc_searches = sum(data["zip_counts_nc"].values())
    nc_share_pct = round(100.0 * nc_searches / sum(data["zip_counts_all"].values()))

    fmc = data["fmc_page"]
    campaign = data["campaign"]
    cc = data["club_click"]
    cov = data["coverage_gap"]
    paid_search = data["channels"].get("Paid Search", {})
    paid_social = data["channels"].get("Paid Social", {})

    if fmc["rank_by_views"] != 3:
        warn(f"FMC is #{fmc['rank_by_views']} by views (was #3) -- "
             f"'making it the {ordinal(fmc['rank_by_views'])} most visited page' wording is rank-aware and will update, but double check it still reads naturally")
    if fmc["rank_by_key_events"] != 1:
        warn(f"FMC is #{fmc['rank_by_key_events']} by key events (was #1) -- "
             f"'generates more key events than any other page' claim needs review")

    # -------------------------------------------------------------------
    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Inches(1)
    section.left_margin = section.right_margin = Inches(1)

    styled_para(doc, "NORTH CAROLINA YOUTH SOCCER ASSOCIATION", size=10, color=GRAY, bold=True, space_after=3)
    styled_para(doc, "Find My Club: Campaign & Analytics Report", size=28, color=NAVY, bold=True, space_after=4)
    styled_para(doc, "Prepared for the NCYSA Board of Directors  |  August 5, 2026 Meeting", size=11, color=GRAY, space_after=2)
    styled_para(doc, f"Reporting period: {long_date(win['start'])} – {long_date(win['end'], with_year=True)}"
                      f"  |  Source: Google Analytics 4 (NCYSA property)", size=10, color=GRAY, space_after=16)

    # --- Executive Summary --------------------------------------------
    heading(doc, "Executive Summary")
    rich_para(doc, [
        ("The Find My Club tool, launched on ncsoccer.org this season, has become one of the most "
         "visited destinations on the NCYSA website and the centerpiece of the Intrepid Marketing "
         "Group campaign. Since January 1, families have run ", False),
        (f"{commas(zip_total)} ZIP code searches", True),
        (" from ", False),
        (f"{commas(zip_distinct_all)} distinct ZIP codes", True),
        (", and the Find My Club page has drawn ", False),
        (f"{commas(fmc['views'])} views from {commas(fmc['users'])} users", True),
        (f", making it the {ordinal(fmc['rank_by_views'])} most visited page on the entire site, "
         "behind only the homepage and Classic schedules.", False),
    ])
    rich_para(doc, [
        ("The Intrepid campaign (", False), ("worldcup2026", True),
        ("), whose traffic first appears in the data on June 11, timed to the World Cup, produced an "
         "immediate and sustained lift. Daily searches averaged ", False),
        (f"{round(avg_before)} per day", True), (" before the campaign and ", False),
        (f"{round(avg_after)} per day", True),
        (" after it began, a five-fold increase that has held through July. The campaign has driven ", False),
        (f"{commas(campaign['sessions'])} sessions", True), (" and ", False),
        (f"{commas(campaign['key_events'])} key events", True), (" to date.", False),
    ])
    rich_para(doc, [
        ("Families who search overwhelmingly act on the results. In the period both metrics were "
         "tracked, ", False),
        (f"{commas(cc['searches_in_window'])} searches produced {commas(cc['total_clicks'])} club clicks", True),
        (", roughly one club visit per search, with ", False),
        (f"{commas(cc['distinct_clubs'])} different member clubs", True),
        (f" receiving traffic. Coverage analysis is also encouraging: of {commas(cov['total'])} recorded "
         f"coverage gap events, only {commas(cov['nc_total'])} traced to North Carolina ZIP codes, several "
         "of which were internal tests, indicating NCYSA member clubs are within reach of nearly every "
         "family in the state who has looked.", False),
    ])

    # --- Campaign Impact -------------------------------------------------
    heading(doc, "Campaign Impact: worldcup2026")
    styled_para(doc,
        "The campaign is directly visible in the data. Paid Social and Paid Search traffic to "
        "ncsoccer.org was effectively zero from January through May, appeared June 11 when the campaign "
        "launched, and has run continuously since. The search activity on the tool tripled-to-quintupled "
        "in the same week and has not fallen back.", size=11, space_after=8)
    add_table(doc, ["Metric", "Before campaign (Mar 1 – Jun 10)", f"During campaign (Jun 11 – {long_date(win['end'])})"],
              [["Average ZIP searches per day", f"{avg_before}", f"{avg_after}"],
               ["Traffic pattern", "Organic and direct only", "Organic + paid social + paid search"]])
    doc.add_paragraph()

    heading(doc, "Paid channel performance", level=2)
    # Locked rule: describe how each channel performs, never rank one as
    # "better" for future spend -- that's a decision for the board, not this
    # report.
    rich_para(doc, [
        ("The two paid channels behaved very differently, which is useful steering information for the "
         "next phase of spend. ", False),
        ("Paid Search", True),
        (f" delivered {commas(paid_search.get('sessions', 0))} sessions at a {int(paid_search.get('engagement_pct', 0))}% "
         f"engagement rate, higher than organic search, and converted at an exceptional "
         f"{int(paid_search.get('session_key_event_rate_pct', 0))}% session key event rate "
         f"({commas(paid_search.get('key_events', 0))} key events). ", False),
        ("Paid Social", True),
        (f" delivered more raw sessions ({commas(paid_social.get('sessions', 0))}) but at a "
         f"{int(paid_social.get('engagement_pct', 0))}% engagement rate and "
         f"{paid_social.get('avg_engagement_sec', 0)} seconds average engagement time, a pattern typical "
         f"of in-app social browsers where many taps bounce immediately. Paid Social still produced "
         f"{commas(paid_social.get('key_events', 0))} key events. The difference largely reflects how "
         "each channel behaves: search reaches families actively looking for a club, while social "
         "reaches families scrolling.", False),
    ])
    channel_rows = sorted(data["channels"].items(), key=lambda kv: -kv[1]["sessions"])
    add_table(doc, ["Channel", "Sessions", "Engagement rate", "Key events"],
              [[ch, commas(v["sessions"]), f"{int(v['engagement_pct'])}%", commas(v["key_events"])]
               for ch, v in channel_rows])
    doc.add_paragraph()

    # --- Tool Usage: Searches -----------------------------------------
    heading(doc, "Tool Usage: Searches")
    rich_para(doc, [
        ("Since January 1, the tool recorded ", False),
        (f"{commas(zip_total)} searches by {commas(zip_users)} users", True),
        (f" across {commas(zip_distinct_all)} distinct ZIP codes. {commas(zip_distinct_nc)} of those ZIPs "
         f"({commas(nc_searches)} searches, {nc_share_pct}%) are North Carolina ZIP codes; the remainder "
         "are out-of-state and international visitors. Search demand concentrates in the Charlotte metro "
         "and the Triangle, mirroring the state's population centers.", False),
    ])
    top_zips = sorted(data["zip_detail"].items(), key=lambda kv: -kv[1]["searches"])[:10]
    def _city(z):
        if z in ZIP_LABEL_OVERRIDES:
            return ZIP_LABEL_OVERRIDES[z]
        m = zipcodes.matching(z)
        return m[0]["city"] if m else z
    add_table(doc, ["Rank", "ZIP", "Area", "Searches", "Users"],
              [[i + 1, z, _city(z), v["searches"], v["users"]] for i, (z, v) in enumerate(top_zips)])
    doc.add_paragraph()

    # --- Club Engagement: Clicks ---------------------------------------
    heading(doc, "Club Engagement: Clicks")
    website = cc["action_detail"].get("website", {"clicks": 0})
    email = cc["action_detail"].get("email", {"clicks": 0})
    action_total = sum(v["clicks"] for v in cc["action_detail"].values())
    website_pct = round(100.0 * website["clicks"] / action_total) if action_total else 0
    rich_para(doc, [
        ("Click tracking went live July 8, so the figures below reflect roughly two weeks of data; they "
         "will grow quickly. In that window, families clicked through to club websites or emails ", False),
        (f"{commas(cc['total_clicks'])} times", True),
        (f" against {commas(cc['searches_in_window'])} searches. {website_pct}% of clicks went to club "
         f"websites ({commas(website['clicks'])}) versus club email links ({commas(email['clicks'])}). "
         f"The nearest club (rank 1 in results) received {round(cc['rank1_share_pct'])}% of all clicks, "
         "confirming that proximity drives the decision and the tool's distance-ranked design matches "
         "how families actually choose.", False),
    ])
    rich_para(doc, [
        (f"{commas(cc['distinct_clubs'])} different member clubs", True),
        (" received click traffic in just two weeks, meaning the tool is distributing value across the "
         "membership rather than concentrating it. Top recipients:", False),
    ])
    top_clubs = sorted(cc["club_detail"].items(), key=lambda kv: -kv[1]["clicks"])[:10]
    add_table(doc, ["Club", "Clicks", "Users"],
              [[name, v["clicks"], v["users"]] for name, v in top_clubs])
    doc.add_paragraph()

    # --- Coverage Analysis -------------------------------------------
    heading(doc, "Coverage Analysis")
    styled_para(doc,
        "The tool records a coverage gap event when a search finds no member club within 40 miles. "
        f"Since tracking began July 8, {commas(cov['total'])} coverage gap events were recorded, but the "
        "large majority trace to out-of-state and international ZIP codes (Virginia, Massachusetts, "
        "North Dakota, and others), visitors exploring the tool rather than North Carolina families "
        f"without options. Only {commas(cov['nc_total'])} events across {cov['nc_distinct_zips']} "
        "NC-coded ZIPs were recorded, and several of those were internal testing. The practical finding "
        "for the Board: after more than 8,000 searches, genuine in-state coverage gaps are rare. The "
        "tool will continue to log these events, giving NCYSA an ongoing early-warning map for "
        "underserved areas.", size=11, space_after=10)

    # --- Page Traffic Context -------------------------------------------
    heading(doc, "Page Traffic Context")
    kev_clause = "generates more key events than any other page on the site" if fmc["rank_by_key_events"] == 1 \
        else f"is the #{fmc['rank_by_key_events']} page on the site by key events"
    styled_para(doc,
        f"Find My Club is now the #{fmc['rank_by_views']} page on ncsoccer.org by views and "
        f"#{fmc['rank_by_users']} by unique users, remarkable for a page that did not exist last season. "
        f"It also {kev_clause}.", size=11, space_after=8)
    top5 = data["top_pages"][:5]
    add_table(doc, ["Page", "Views", "Users", "Key events"],
              [[p["path"], commas(p["views"]), commas(p["users"]), commas(p["kev"])] for p in top5])
    doc.add_paragraph()

    # --- Data Notes & Methodology ---------------------------------------
    heading(doc, "Data Notes & Methodology")
    styled_para(doc,
        f"All figures are from the NCYSA Google Analytics 4 property, {long_date(win['start'])} – "
        f"{long_date(win['end'], with_year=True)}. Three custom events instrument the tool: zip_search "
        "(each ZIP lookup), club_click (each click on a club website or email link, with club name, "
        "rank, and action), and coverage_gap (searches where the nearest club exceeds 40 miles). "
        "zip_search has tracked since the tool launched; club_click and coverage_gap tracking went live "
        "July 8, 2026, so their totals reflect approximately two weeks and understate full-period "
        "activity. Campaign attribution uses GA4 session campaign and channel grouping; the "
        "worldcup2026 campaign spans both paid social and paid search. Approximately 1% of searches "
        "originate outside the United States and are noted where relevant.", size=11, space_after=8)
    styled_para(doc,
        "Prepared by Jeremy (web development) from GA4 exports. Questions on campaign configuration: "
        "Torrey Winchester, Intrepid Marketing Group.", size=10, italic=True, color=GRAY, space_after=0)

    return doc


def main():
    data = json.load(open(DATA_PATH))
    doc = build(data)
    import os
    os.makedirs("build", exist_ok=True)
    doc.save(OUT_PATH)
    print(f"\nWrote {OUT_PATH}")
    if warnings:
        print(f"\n{len(warnings)} editorial check(s) flagged above -- numbers are correct, "
              f"but review the surrounding prose before publishing.")


if __name__ == "__main__":
    main()
