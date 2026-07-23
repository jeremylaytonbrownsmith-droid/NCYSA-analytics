#!/usr/bin/env python3
"""
NCYSA Find My Club - board report publisher (Phase B Step 3 + Phase C Step 4).

Two independently-invoked stages, run at different points in the pipeline:

  python publish.py media   -- upload the rebuilt .docx/.xlsx to the WP media
                                library and write build/media_urls.json.
                                Runs BEFORE build_report.py, so the HTML's
                                download buttons can point at the fresh URLs.

  python publish.py page    -- publish the rebuilt HTML (built by
                                build_report.py) to either the preview/draft
                                page or the live page (PUBLISH_TARGET env
                                var, default "preview"). Runs AFTER
                                build_report.py.

Neither stage ever touches WP_LIVE_PAGE_ID's password protection or logo --
"live" publishing only ever PATCHes the page's `content` field.

Gated sequences -- each step must succeed before the next runs; a 401/403/
rest_cannot_edit anywhere STOPs immediately with a rebuild-and-paste
fallback message:

  media stage:
    1. A tiny throwaway test upload to /wp/v2/media, deleted immediately,
       to confirm the app password can write through the media endpoint
       specifically (VIP can restrict this differently from page edits).
    2. Upload the real .docx and .xlsx; only after both succeed, delete
       whatever media the previous run left behind (found by a stable,
       predictable title match) -- so the download links are never broken
       by a mid-run failure.

  page stage:
    1. Authenticated GET of the live page (proves read access and gives
       ground truth for whether its Custom HTML block holds a full
       document or just the inner fragment).
    2. preview target: a harmless test write to the preview page
       (create-if-missing, draft), then the real publish.
       live target: publish directly -- content only, nothing else on
       the page is touched.

Env vars: WP_SITE, WP_USER, WP_APP_PASSWORD (required), WP_LIVE_PAGE_ID
(default 10514), WP_PREVIEW_SLUG (default board-meeting-8-5-preview),
PUBLISH_TARGET (preview|live, default preview), REPORT_HTML (default
build/board_report.html), REPORT_DOCX (default build/board_report.docx),
REPORT_XLSX (default build/data_workbook.xlsx).
"""

import os
import re
import sys
import json

import requests
from requests.auth import HTTPBasicAuth

WP_SITE = os.environ.get("WP_SITE", "https://www.ncsoccer.org").rstrip("/")
WP_USER = os.environ["WP_USER"]
WP_APP_PASSWORD = os.environ["WP_APP_PASSWORD"]
LIVE_PAGE_ID = int(os.environ.get("WP_LIVE_PAGE_ID", "10514"))
PREVIEW_SLUG = os.environ.get("WP_PREVIEW_SLUG", "board-meeting-8-5-preview")
PUBLISH_TARGET = os.environ.get("PUBLISH_TARGET", "preview")
REPORT_HTML_PATH = os.environ.get("REPORT_HTML", "build/board_report.html")
REPORT_DOCX_PATH = os.environ.get("REPORT_DOCX", "build/board_report.docx")
REPORT_XLSX_PATH = os.environ.get("REPORT_XLSX", "build/data_workbook.xlsx")
MEDIA_URLS_PATH = "build/media_urls.json"

PAGES_API = f"{WP_SITE}/wp-json/wp/v2/pages"
MEDIA_API = f"{WP_SITE}/wp-json/wp/v2/media"
auth = HTTPBasicAuth(WP_USER, WP_APP_PASSWORD)

# Stable titles so a future run can find and clean up what THIS run uploads,
# without needing any separate state file -- the WP media library IS the
# state.
DOCX_TITLE = "NCYSA Find My Club Board Report"
XLSX_TITLE = "NCYSA Find My Club Data Workbook"


def die(msg):
    print(f"\nSTOP: {msg}")
    print("Falling back to rebuild-and-paste: use the files in build/ manually in the WP editor.")
    sys.exit(1)


def check_wp_error(resp):
    if resp.status_code in (401, 403):
        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:500]}
        die(f"WordPress rejected the request ({resp.status_code} {body.get('code', '')}): "
            f"{body.get('message', body)}")


# ===========================================================================
# Media stage
# ===========================================================================
def media_test_upload():
    print("[1/3] Media pre-flight: tiny test upload to /wp/v2/media")
    # Use a real (if minimal) .docx rather than a .txt: some WP setups
    # restrict uploads to an allowlist of file types, and plain text isn't
    # always on it even when Word/Excel are -- probing with a mismatched
    # type would misreport a filetype restriction as an auth failure. This
    # exercises the exact type we're about to actually upload.
    import io
    from docx import Document as _ProbeDocument
    probe = _ProbeDocument()
    probe.add_paragraph("NCYSA automation media-upload probe -- safe to delete.")
    buf = io.BytesIO()
    probe.save(buf)
    headers = {
        "Content-Disposition": 'attachment; filename="ncysa-automation-probe.docx"',
        "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    r = requests.post(MEDIA_API, headers=headers, data=buf.getvalue(), auth=auth, timeout=30)
    check_wp_error(r)
    if r.status_code not in (200, 201):
        die(f"Media test upload failed: {r.status_code} {r.text[:500]}")
    media_id = r.json()["id"]
    print(f"  OK -- test upload succeeded (media id {media_id}) -- VIP allows app-password media uploads.")
    # Clean up immediately; this was only a permissions probe.
    dr = requests.delete(f"{MEDIA_API}/{media_id}", params={"force": "true"}, auth=auth, timeout=30)
    if dr.status_code not in (200, 201):
        print(f"  [!] Could not delete the probe upload (media id {media_id}, status {dr.status_code}) -- harmless, but a leftover 'ncysa-automation-probe.docx' will remain in the media library.")


def find_prior_media(title):
    r = requests.get(MEDIA_API, params={"search": title, "per_page": 20}, auth=auth, timeout=30)
    check_wp_error(r)
    if r.status_code != 200:
        die(f"Unexpected status searching media library: {r.status_code} {r.text[:500]}")
    return [m for m in r.json() if m.get("title", {}).get("rendered") == title]


def upload_media_file(path, title, content_type):
    filename = os.path.basename(path)
    with open(path, "rb") as f:
        content = f.read()
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": content_type,
    }
    r = requests.post(MEDIA_API, headers=headers, data=content, auth=auth, timeout=120)
    check_wp_error(r)
    if r.status_code not in (200, 201):
        die(f"Upload of {filename} failed: {r.status_code} {r.text[:500]}")
    media = r.json()
    # Set a stable, searchable title (separate call -- the upload itself
    # can't set title reliably across all WP configs).
    requests.post(f"{MEDIA_API}/{media['id']}", json={"title": title}, auth=auth, timeout=30)
    print(f"  OK -- uploaded {filename} -> {media['source_url']} (media id {media['id']})")
    return media["id"], media["source_url"]


def media_stage():
    media_test_upload()

    if not os.path.exists(REPORT_DOCX_PATH):
        die(f"{REPORT_DOCX_PATH} not found -- run generate_docx.py first.")
    if not os.path.exists(REPORT_XLSX_PATH):
        die(f"{REPORT_XLSX_PATH} not found -- run generate_xlsx.py first.")

    prior_docx = find_prior_media(DOCX_TITLE)
    prior_xlsx = find_prior_media(XLSX_TITLE)

    print("[2/3] Uploading rebuilt .docx and .xlsx")
    docx_id, docx_url = upload_media_file(
        REPORT_DOCX_PATH, DOCX_TITLE,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    xlsx_id, xlsx_url = upload_media_file(
        REPORT_XLSX_PATH, XLSX_TITLE,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    print(f"[3/3] Cleaning up {len(prior_docx) + len(prior_xlsx)} prior-run upload(s)")
    for m in prior_docx + prior_xlsx:
        if m["id"] in (docx_id, xlsx_id):
            continue  # safety: never delete what we just uploaded
        dr = requests.delete(f"{MEDIA_API}/{m['id']}", params={"force": "true"}, auth=auth, timeout=30)
        status = "deleted" if dr.status_code in (200, 201) else f"FAILED ({dr.status_code})"
        print(f"  {status}: media id {m['id']} ({m.get('source_url', '?')})")

    os.makedirs("build", exist_ok=True)
    with open(MEDIA_URLS_PATH, "w") as f:
        json.dump({"docx_url": docx_url, "xlsx_url": xlsx_url}, f, indent=2)
    print(f"\nWrote {MEDIA_URLS_PATH}")
    print(f"  Board Report (Word):     {docx_url}")
    print(f"  Full Data Workbook:      {xlsx_url}")


# ===========================================================================
# Page stage
# ===========================================================================
def preflight_read_live():
    print(f"[1/3] Pre-flight: GET {PAGES_API}/{LIVE_PAGE_ID}?context=edit")
    r = requests.get(f"{PAGES_API}/{LIVE_PAGE_ID}", params={"context": "edit"}, auth=auth, timeout=30)
    check_wp_error(r)
    if r.status_code != 200:
        die(f"Unexpected status reading live page: {r.status_code} {r.text[:500]}")
    page = r.json()
    title = page.get("title", {}).get("raw", "")
    print(f"  OK -- page {LIVE_PAGE_ID} title: {title!r}, "
          f"status: {page.get('status')}, password-protected: {bool(page.get('password'))}")
    return page.get("content", {}).get("raw", ""), title


# Kill-switch for live publishing, controlled entirely from WordPress: the
# board can prepend this to the live page's title (e.g. "[PAUSED] Board
# Meeting 8/5") in the normal WP editor to pause automated live updates,
# with no code/GitHub access needed, and remove it to resume. The title
# field works for this because publish_live() below never writes to title
# -- only content -- so the marker can't be silently overwritten by the
# very automation it's meant to pause. Case-insensitive; only checked for
# PUBLISH_TARGET=live (the preview publish always overwrites its own
# title anyway, so a marker there wouldn't survive regardless).
PAUSE_MARKER = "[PAUSED]"


def is_paused(title):
    return PAUSE_MARKER.lower() in (title or "").lower()


def extract_fragment(full_html):
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
          f"a <!DOCTYPE html> wrapper -- matching that shape for the payload.")
    return rebuilt_full_html if live_has_doctype else extract_fragment(rebuilt_full_html)


def find_preview_page():
    r = requests.get(PAGES_API, params={"slug": PREVIEW_SLUG, "status": "draft", "context": "edit"},
                      auth=auth, timeout=30)
    check_wp_error(r)
    if r.status_code != 200:
        die(f"Unexpected status looking up preview page: {r.status_code} {r.text[:500]}")
    results = r.json()
    return results[0] if results else None


def test_write_preview(existing):
    print(f"[2/3] Test write: {'update' if existing else 'create'} draft page '{PREVIEW_SLUG}'")
    payload = {
        "title": "NCYSA Find My Club — Board Meeting Preview (auto-refresh test)",
        "slug": PREVIEW_SLUG,
        "status": "draft",
        "content": "<!-- wp:paragraph --><p>Preflight test write -- content will be replaced.</p><!-- /wp:paragraph -->",
    }
    url = f"{PAGES_API}/{existing['id']}" if existing else PAGES_API
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
    r = requests.post(f"{PAGES_API}/{page_id}", json=payload, auth=auth, timeout=60)
    check_wp_error(r)
    if r.status_code not in (200, 201):
        die(f"Publish to preview failed: {r.status_code} {r.text[:500]}")
    return r.json()


def publish_live(content):
    # Content only -- never title, status, password, or any other page
    # setting (that's where the logo and password protection live).
    print(f"[2/2] Publishing rebuilt report to LIVE page {LIVE_PAGE_ID}")
    wrapped = f"<!-- wp:html -->\n{content}\n<!-- /wp:html -->"
    r = requests.post(f"{PAGES_API}/{LIVE_PAGE_ID}", json={"content": wrapped}, auth=auth, timeout=60)
    check_wp_error(r)
    if r.status_code not in (200, 201):
        die(f"Live publish failed: {r.status_code} {r.text[:500]}")
    return r.json()


def page_stage():
    if not os.path.exists(REPORT_HTML_PATH):
        die(f"{REPORT_HTML_PATH} not found -- run build_data.py and build_report.py first.")
    rebuilt_html = open(REPORT_HTML_PATH).read()

    live_raw, live_title = preflight_read_live()
    payload_content = decide_wrapping(live_raw, rebuilt_html)

    if PUBLISH_TARGET == "live":
        if is_paused(live_title):
            print(f"\nLive publish SKIPPED -- page title contains {PAUSE_MARKER!r}: {live_title!r}")
            print(f"To resume automated live updates, remove {PAUSE_MARKER!r} from the page title in WordPress.")
            return
        page = publish_live(payload_content)
        print("\nPublished to the LIVE page.")
        print(f"  Page ID:  {page['id']}")
        print(f"  URL:      {page.get('link', WP_SITE)}")
        return

    if PUBLISH_TARGET != "preview":
        die(f"Unknown PUBLISH_TARGET {PUBLISH_TARGET!r} -- expected 'preview' or 'live'.")

    existing = find_preview_page()
    page = test_write_preview(existing)  # STOPs internally on any auth/write failure
    page = publish_preview(page["id"], payload_content)

    link = page.get("link", "")
    edit_link = f"{WP_SITE}/wp-admin/post.php?post={page['id']}&action=edit"
    if link:
        sep = "&" if "?" in link else "?"
        preview_link = f"{link}{sep}preview=true"
    else:
        preview_link = f"{WP_SITE}/?page_id={page['id']}&preview=true"
    print("\nPublished to preview/draft page -- the live page was NOT touched.")
    print(f"  Page ID:      {page['id']}")
    print(f"  Slug:         {page.get('slug')}")
    print(f"  Status:       {page.get('status')}")
    print(f"  Preview URL:  {preview_link}")
    print(f"  Edit in WP:   {edit_link}")
    print(f"  Live page {LIVE_PAGE_ID}: untouched.")


def main():
    stage = sys.argv[1] if len(sys.argv) > 1 else "page"
    if stage == "media":
        media_stage()
    elif stage == "page":
        page_stage()
    else:
        print(f"Usage: python publish.py [media|page]  (got: {stage!r})")
        sys.exit(2)


if __name__ == "__main__":
    main()
