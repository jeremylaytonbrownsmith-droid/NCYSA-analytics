#!/usr/bin/env python3
"""One-off verification: render template vs rebuilt report headlessly,
screenshot both, and diff the key on-page numbers. Not part of the pipeline."""
import json
from playwright.sync_api import sync_playwright

PAGES = {
    "template": "templates/board_report_template.html",
    "rebuilt": "build/board_report.html",
}

EXTRACT_JS = """
() => {
  const txt = s => document.querySelector(s)?.textContent?.trim();
  const stats = [...document.querySelectorAll('.fmcr-stat b')].map(b => b.textContent.trim());
  const dataN = [...document.querySelectorAll('[data-n]')].map(e => e.getAttribute('data-n'));
  const dotCount = document.querySelectorAll('#fmcr-map-dots circle').length;
  const zipBars = [...document.querySelectorAll('.fmcr-main > .fmcr-sec')][1]
    .querySelectorAll('.fmcr-bar-row .fmcr-bar-val');
  const clubBars = [...document.querySelectorAll('.fmcr-main > .fmcr-sec')][2]
    .querySelectorAll('.fmcr-bar-row .fmcr-bar-val');
  return {
    stat_tiles: stats,
    data_n_values: dataN,
    dot_count: dotCount,
    zip_bar_vals: [...zipBars].map(e => e.textContent.trim()),
    club_bar_vals: [...clubBars].map(e => e.textContent.trim()),
    hero_sub: txt('.fmcr-sub'),
    spark_caption: txt('.fmcr-spark-caption'),
    campaign_p: txt('.fmcr-compare')?.length,
    campaign_para: document.querySelectorAll('.fmcr-sec p')[0]?.textContent.trim(),
    paid_search_card: txt('.fmcr-card:not(.fmcr-alt) small'),
    paid_social_card: txt('.fmcr-card.fmcr-alt small'),
    zip_intro: document.querySelectorAll('.fmcr-sec p')[1]?.textContent.trim(),
    map_caption: txt('.fmcr-map-caption'),
    click_para: document.querySelectorAll('.fmcr-sec p')[2]?.textContent.trim(),
    coverage_para: document.querySelectorAll('.fmcr-sec p')[3]?.textContent.trim(),
    pageviews_para: document.querySelectorAll('.fmcr-sec p')[4]?.textContent.trim(),
    footer: txt('.fmcr-foot'),
    marker_x: document.getElementById('fmcr-marker')?.getAttribute('x1'),
    polyline_point_count: document.querySelector('.fmcr-spark polyline')?.getAttribute('points')?.trim()?.split(/\\s+/)?.length,
  };
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", headless=True)
    results = {}
    for name, path in PAGES.items():
        page = browser.new_page(viewport={"width": 1100, "height": 2400})
        page.goto(f"file://{__import__('os').path.abspath(path)}")
        page.wait_for_timeout(600)
        # Force-reveal everything the IntersectionObserver would only trigger
        # on scroll, so the full-page screenshot shows real content.
        page.evaluate("""
            () => {
              document.querySelectorAll('.fmcr-sec').forEach(e => e.classList.add('fmcr-in'));
              document.querySelectorAll('.fmcr-bar-fill').forEach(e => e.style.width = e.getAttribute('data-w') + '%');
              document.querySelectorAll('.fmcr-count').forEach(e => e.textContent = Number(e.getAttribute('data-n')).toLocaleString());
            }
        """)
        page.wait_for_timeout(1600)  # let the reveal/width transitions finish
        page.screenshot(path=f"/tmp/claude-0/-home-user-NCYSA-analytics/2e1e79c8-0ba7-535b-899e-4c42783b0ea9/scratchpad/{name}_full.png", full_page=True)
        results[name] = page.evaluate(EXTRACT_JS)
        page.close()
    browser.close()

with open("/tmp/claude-0/-home-user-NCYSA-analytics/2e1e79c8-0ba7-535b-899e-4c42783b0ea9/scratchpad/verify_results.json", "w") as f:
    json.dump(results, f, indent=2)

print(json.dumps(results, indent=2))
