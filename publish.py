#!/usr/bin/env python3
"""
NCYSA Find My Club - board report publisher (Phase B, Step 3).

Publishes the rebuilt board report HTML to a WordPress DRAFT/preview page
via the WP REST API (application-password Basic auth). This script never
writes to the live board page (WP_LIVE_PAGE_ID) -- it only ever reads it,
to confirm auth and to match its Custom HTML block's structure. All writes
go to the scratch preview page (WP_PREVIEW_SLUG).

Gated sequence -- each step must succeed before the next runs:
  1. Authenticated GET of the live page (proves the app password can read
     through whatever auth/VIP layer sits in front of WordPress, and gives
     ground truth for whether its Custom HTML block holds a full document
     or just the inner fragment, so the preview payload matches it).
  2. A harmless test write to the preview page (create-if-missing, draft).
     A 401/403/rest_cannot_edit here means the app password can't write
     through that layer -- STOP, do not attempt the real publish.
  3. Only if both pass: push the full rebuilt HTML to the preview page and
     print its preview URL.

Never touches WP_LIVE_PAGE_ID's content, password protection, or logo.

Env vars: WP_SITE, WP_USER, WP_APP_PASSWORD (required), WP_LIVE_PAGE_ID
(default 10514), WP_PREVIEW_SLUG (default board-meeting-8-5-preview),
REPORT_HTML (default build/board_report.html).
"""

import os
import re
import sys

import requests
from requests.auth import HTTPBasicAuth

WP_SITE = os.environ.get("WP_SITE", "https://www.ncsoccer.org").rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_APP_PASSWORD = os.environ["WP_APP_PASSWORD"]
LIVE_PAGE_ID = int(os.environ.get("WP_LIVE_PAGE_ID", "10514"))
PREVIEW_SLUG = os.environ.get("WP_PREVIEW_SLUG", "board-meeting-8-5-preview")
REPORT_HTML_PATH = os.environ.get("REPORT_HTML", "build/board_report.html")

API = f"{WP_SITE}/wp-json/wp/v2/pages"
auth = HTTPBasicAuth(WP_USER, WP_APP_PASSWORD)


def die(msg):
    print(f"\nSTOP: {msg}")
    print("Falling back to rebuild-and-paste: use build/board_report.html manually in the WP editor.")
    sys.exit(1)


def check_wp_error(resp):
    if resp.status_code in (401, 403):
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:500]}
        die(f"WordPress rejected the request ({resp.status_code} {body.get('code', '')}): "
            f"{body.get('message', body)}")


def preflight_read_live():
    print(f"[1/3] Pre-flight: GET {API}/{LIVE_PAGE_ID}?context=edit")
    r = requests.get(f"{API}/{LIVE_PAGE_ID}", params={"context": "edit"}, auth=auth, timeout=30)
    check_wp_error(r)
    if r.status_code != 200:
        die(f"Unexpected status reading live page: {r.status_code} {r.text[:500]}")
    page = r.json()
    print(f"  OK -- page {LIVE_PAGE_ID} title: {page.get('title', {}).get('raw', '')!r}, "
          f"status: {page.get('status')}, password-protected: {bool(page.get('password'))}")
    return page.get("content", {}).get("raw", "")


def extract_fragment(full_html):
    """Given the rebuild (a full standalone HTML document), return just the
    payload that belongs inside a Gutenberg Custom HTML block: everything
    from the first font/style tag through the final </script>, dropping the
    doctype/html/head/body wrapper the template file carries but a WP theme
    already supplies."""
    start_m = re.search(r'<link rel="preconnect"|<style>', full_html)
    end_matches = list(re.finditer(r'</script>', full_html))
    if not start_m or not end_matches:
        print("  [!] Could not find expected <style>/</script> anchors -- shipping full document as-is.")
        return full_html
    return full_html[start_m.start():end_matches[-1].end()]


def decide_wrapping(live_raw, rebuilt_full_html):
    inner = re.sub(r"<!--\s*/?wp:html\s*-->", "", live_raw).strip()
    live_has_doctype = bool(re.search(r"<!DOCTYPE html>", inner, re.I))
    print(f"  Live block currently {'includes' if live_has_doctype else 'does NOT include'} "
          f"a <!DOCTYPE html> wrapper -- matching that shape for the preview payload.")
    return rebuilt_full_html if live_has_doctype else extract_fragment(rebuilt_full_html)


def find_preview_page():
    r = requests.get(API, params={"slug": PREVIEW_SLUG, "status": "draft", "context": "edit"},
                      auth=auth, timeout=30)
    check_wp_error(r)
    if r.status_code != 200:
        die(f"Unexpected status looking up preview page: {r.status_code} {r.text[:500]}")
    results = r.json()
    return results[0] if results else None


def test_write(existing):
    print(f"[2/3] Test write: {'update' if existing else 'create'} draft page '{PREVIEW_SLUG}'")
    payload = {
        "title": "NCYSA Find My Club — Board Meeting Preview (auto-refresh test)",
        "slug": PREVIEW_SLUG,
        "status": "draft",
        "content": "<!-- wp:paragraph --><p>Preflight test write -- content will be replaced.</p><!-- /wp:paragraph -->",
    }
    url = f"{API}/{existing['id']}" if existing else API
    r = requests.post(url, json=payload, auth=auth, timeout=30)
    check_wp_error(r)
    if r.status_code not in (200, 201):
        die(f"Test write failed: {r.status_code} {r.text[:500]}")
    page = r.json()
    print(f"  OK -- write succeeded (page id {page['id']}, status {page['status']}) -- VIP honors app-password writes.")
    return page


def publish_preview(page_id, content):
    print(f"[3/3] Publishing rebuilt report to preview page {page_id}")
    wrapped = f"<!-- wp:html -->\n{content}\n<!-- /wp:html -->"
    payload = {
        "title": "NCYSA Find My Club — Board Meeting Preview",
        "status": "draft",
        "content": wrapped,
    }
    r = requests.post(f"{API}/{page_id}", json=payload, auth=auth, timeout=60)
    check_wp_error(r)
    if r.status_code not in (200, 201):
        die(f"Publish to preview failed: {r.status_code} {r.text[:500]}")
    return r.json()


def main():
    if not os.path.exists(REPORT_HTML_PATH):
        die(f"{REPORT_HTML_PATH} not found -- run build_data.py and build_report.py first.")
    rebuilt_html = open(REPORT_HTML_PATH).read()

    live_raw = preflight_read_live()
    payload_content = decide_wrapping(live_raw, rebuilt_html)

    existing = find_preview_page()
    page = test_write(existing)  # STOPs internally (sys.exit) on any auth/write failure

    page = publish_preview(page["id"], payload_content)

    link = page.get("link", "")
    edit_link = f"{WP_SITE}/wp-admin/post.php?post={page['id']}&action=edit"
    preview_link = f"{link}?preview=true" if link else f"{WP_SITE}/?page_id={page['id']}&preview=true"
    print("\nPublished to preview/draft page -- the live page was NOT touched.")
    print(f"  Page ID:      {page['id']}")
    print(f"  Slug:         {page.get('slug')}")
    print(f"  Status:       {page.get('status')}")
    print(f"  Preview URL:  {preview_link}")
    print(f"  Edit in WP:   {edit_link}")
    print(f"  Live page {LIVE_PAGE_ID}: untouched.")


if __name__ == "__main__":
    main()
