#!/usr/bin/env python3
"""
NCYSA member-club logo scroller builder.

Regenerates the "Our Member Clubs" logo scroller embedded on
https://www.ncsoccer.org/find-my-club/ from clubs.json -- the CSS and
wrapper markup are fixed (copied verbatim from the version already live on
that page), only the per-club <div> items are generated from data.

To add/remove/update a club: edit clubs.json (name, url, logo, alt -- url
may be null for a club with no site link), then run this script and publish
the output via publish_club_scroller.py.

Usage: python3 build_club_scroller.py [clubs.json] [out.html]
"""

import sys
import json

CLUBS_PATH = sys.argv[1] if len(sys.argv) > 1 else "clubs.json"
OUT_PATH = sys.argv[2] if len(sys.argv) > 2 else "build/club_scroller.html"

START_MARKER = "<!-- NCYSA-CLUB-SCROLLER:START -->"
END_MARKER = "<!-- NCYSA-CLUB-SCROLLER:END -->"

STYLE = """<style>
.logo-scroller-container {
  max-width: 800px;
  margin: 30px auto 0;
  padding: 20px;
  background: #ffffff;
  border-radius: 14px;
  border: 3px solid #b82f2f;
  box-shadow: 0 10px 30px rgba(0,0,0,0.2);
  overflow: hidden;
  position: relative;
}

.logo-scroller-container::before,
.logo-scroller-container::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  width: 60px;
  z-index: 2;
  pointer-events: none;
}

.logo-scroller-container::before {
  left: 0;
  background: linear-gradient(to right, #ffffff 0%, transparent 100%);
}

.logo-scroller-container::after {
  right: 0;
  background: linear-gradient(to left, #ffffff 0%, transparent 100%);
}

.logo-scroller-title {
  text-align: center;
  color: #b82f2f;
  font-family: system-ui, sans-serif;
  font-size: 18px;
  font-weight: 700;
  margin-bottom: 15px;
  text-transform: uppercase;
  letter-spacing: 1px;
  position: relative;
  z-index: 3;
}

.logo-scroller-track {
  display: flex;
  width: max-content;
  animation: scroll 90s linear infinite;
}

.logo-scroller-container:hover .logo-scroller-track,
.logo-scroller-track:focus-within {
  animation-play-state: paused;
}

.logo-scroller-item {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  margin: 0 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}

.logo-scroller-item a {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  border-radius: 6px;
}

.logo-scroller-item a:focus-visible {
  outline: 2px solid #10045a;
  outline-offset: 3px;
}

.logo-scroller-item img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  opacity: 0.9;
  transition: all 0.3s ease;
}

.logo-scroller-item img:hover,
.logo-scroller-item a:focus-visible img {
  opacity: 1;
  transform: scale(1.1);
}

@keyframes scroll {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}

@media (prefers-reduced-motion: reduce) {
  .logo-scroller-track { animation: none; overflow-x: auto; -webkit-overflow-scrolling: touch; }
}

@media (max-width: 600px) {
  .logo-scroller-container { margin: 15px 10px 0; padding: 12px; max-width: 95%; box-sizing: border-box; }
  .logo-scroller-title { font-size: 14px; margin-bottom: 10px; }
  .logo-scroller-item { width: 36px; height: 36px; margin: 0 6px; }
  .logo-scroller-container::before,
  .logo-scroller-container::after { width: 25px; }
}
</style>"""


def item_html(club, hidden):
    img = f'<img src="{club["logo"]}" alt="{club["alt"]}" loading="lazy">'
    if club["url"]:
        if hidden:
            a = f'<a href="{club["url"]}" aria-hidden="true" tabindex="-1">{img}</a>'
        else:
            a = f'<a href="{club["url"]}" target="_blank" rel="noopener">{img}</a>'
        return f'    <div class="logo-scroller-item">{a}</div>'
    return f'    <div class="logo-scroller-item">{img}</div>'


def build():
    clubs = json.load(open(CLUBS_PATH))
    if not clubs:
        raise RuntimeError("clubs.json is empty -- refusing to publish an empty scroller")

    primary = "\n".join(item_html(c, hidden=False) for c in clubs)
    duplicate = "\n".join(item_html(c, hidden=True) for c in clubs)

    html = f"""{START_MARKER}
<!-- NCYSA Member Clubs Logo Scroller - Embed below Find My Club tool -->
{STYLE}

<div class="logo-scroller-container">
  <div class="logo-scroller-title">Our Member Clubs</div>
  <div class="logo-scroller-track">
    <!-- First set of logos -->
{primary}

    <!-- Duplicate set for seamless loop (hidden from assistive tech) -->
{duplicate}
  </div>
</div>
{END_MARKER}"""

    import os
    os.makedirs("build", exist_ok=True)
    with open(OUT_PATH, "w") as f:
        f.write(html)
    print(f"Wrote {OUT_PATH} ({len(clubs)} clubs)")


if __name__ == "__main__":
    build()
