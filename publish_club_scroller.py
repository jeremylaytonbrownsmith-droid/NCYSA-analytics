#!/usr/bin/env python3
"""
NCYSA member-club logo scroller - publish step.

Swaps the "Our Member Clubs" scroller block on the live
https://www.ncsoccer.org/find-my-club/ page for freshly generated HTML
(build/club_scroller.html, from build_club_scroller.py). Nothing else on
that page is touched -- only the specific scroller block, and only the
page's `content` field is written (never title/status/password).

Two replacement paths:
  1. Steady state: the live content already has our START/END markers
     (every run after the first) -- replace exactly what's between them.
  2. One-time migration: the live content still has the original,
     hand-authored version of the scroller (no markers yet) -- replace it
     by anchoring on its opening comment through to the container's
     closing tags, then the new content carries the markers going forward.

Either path requires EXACTLY one match; if the anchor isn't found (or is
ambiguous), the script aborts instead of guessing -- the live page is only
ever touched via a substitution it can prove is correct.

Also refuses to publish if the new club count would fall below half the
current live count (a corrupted or truncated clubs.json shouldn't be able
to wipe the scroller).

Env vars: WP_SITE, WP_USER, WP_APP_PASSWORD (required), WP_FMC_SLUG
(default "find-my-club").

Usage: python3 publish_club_scroller.py [scroller.html] [--dry-run]

--dry-run fetches the live page and reports which replacement path would
fire and how many clubs would change, but never writes anything back.
"""

import os
import re
import sys

import requests
from requests.auth import HTTPBasicAuth

WP_SITE = os.environ.get("WP_SITE", "https://www.ncsoccer.org").rstrip("/")
WP_USER = os.environ.get("WP_USER")
WP_APP_PASSWORD = os.environ.get("WP_APP_PASSWORD")
FMC_SLUG = os.environ.get("WP_FMC_SLUG", "find-my-club")

PAGES_API = f"{WP_SITE}/wp-json/wp/v2/pages"

SCROLLER_PATH = sys.argv[1] if len(sys.argv) > 1 else "build/club_scroller.html"

START_MARKER = "<!-- NCYSA-CLUB-SCROLLER:START -->"
END_MARKER = "<!-- NCYSA-CLUB-SCROLLER:END -->"

ORIGINAL_ANCHOR_START = "<!-- NCYSA Member Clubs Logo Scroller - Embed below Find My Club tool -->"


def die(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def check_wp_error(r):
    if r.status_code >= 400:
        die(f"WordPress API error {r.status_code}: {r.text[:800]}")


def find_page():
    r = requests.get(
        PAGES_API, params={"slug": FMC_SLUG, "status": "publish,draft,private", "context": "edit"},
        auth=HTTPBasicAuth(WP_USER, WP_APP_PASSWORD), timeout=30,
    )
    check_wp_error(r)
    results = r.json()
    if len(results) != 1:
        die(f"Expected exactly 1 page with slug '{FMC_SLUG}', found {len(results)}.")
    return results[0]


def swap_scroller(live_content, new_block):
    if START_MARKER in live_content:
        pattern = re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER)
        new_content, n = re.subn(pattern, new_block, live_content, count=1, flags=re.S)
        if n != 1:
            die("Found START marker but couldn't cleanly match START...END -- aborting rather than guessing.")
        print("  Replacement path: steady-state (marker-bounded).")
        return new_content

    if ORIGINAL_ANCHOR_START in live_content:
        pattern = re.escape(ORIGINAL_ANCHOR_START) + r".*?</div>\s*</div>"
        new_content, n = re.subn(pattern, new_block, live_content, count=1, flags=re.S)
        if n != 1:
            die(f"Found the original scroller's opening comment but the anchored match found {n} "
                f"hits (expected 1) -- aborting rather than guessing at page structure.")
        print("  Replacement path: one-time migration (from hand-authored original).")
        return new_content

    die("Neither the marker-bounded block nor the original scroller's opening comment "
        "was found on the live page -- aborting. (Has the scroller been removed or "
        "significantly edited outside this pipeline?)")


def main():
    dry_run = "--dry-run" in sys.argv

    if not (WP_USER and WP_APP_PASSWORD):
        die("WP_USER / WP_APP_PASSWORD not set.")
    if not os.path.exists(SCROLLER_PATH):
        die(f"{SCROLLER_PATH} not found -- run build_club_scroller.py first.")

    new_block = open(SCROLLER_PATH).read()
    new_count = new_block.count('class="logo-scroller-item"') // 2  # primary + duplicate set
    if new_count == 0:
        die("Generated scroller has 0 clubs -- refusing to publish an empty scroller.")

    print(f"[1/3] Looking up page by slug '{FMC_SLUG}'")
    page = find_page()
    page_id = page["id"]
    live_content = page.get("content", {}).get("raw", "")
    print(f"  OK -- page {page_id}, status: {page.get('status')}, link: {page.get('link')}")

    old_count = live_content.count('class="logo-scroller-item"') // 2
    if old_count > 0 and new_count < old_count * 0.5:
        die(f"New scroller has {new_count} clubs vs. {old_count} currently live -- "
            f"more than a 50% drop. Refusing to publish; check clubs.json for corruption/truncation.")

    print(f"[2/3] {'Dry run -- would swap' if dry_run else 'Swapping'} scroller block "
          f"({old_count} -> {new_count} clubs)")
    new_page_content = swap_scroller(live_content, new_block)

    if dry_run:
        print("\nDry run complete -- nothing was written to WordPress.")
        print(f"  Page ID:    {page_id}")
        print(f"  Live URL:   {page.get('link')}")
        print(f"  Old length: {len(live_content):,} chars")
        print(f"  New length: {len(new_page_content):,} chars")
        return

    print(f"[3/3] Publishing to page {page_id}")
    r = requests.post(
        f"{PAGES_API}/{page_id}", json={"content": new_page_content},
        auth=HTTPBasicAuth(WP_USER, WP_APP_PASSWORD), timeout=60,
    )
    check_wp_error(r)
    result = r.json()

    print("\nPublished.")
    print(f"  Page ID:  {result['id']}")
    print(f"  URL:      {result.get('link', WP_SITE)}")
    print(f"  Clubs:    {new_count}")


if __name__ == "__main__":
    main()
