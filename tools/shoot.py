#!/usr/bin/env python3
"""Capture NOIR screenshots for visual review.

Usage:  .checks/venv/bin/python tools/shoot.py [name=path ...]
Screenshots land in .checks/shots/.
"""

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("NOIR_BASE", "http://127.0.0.1:8084")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".checks", "shots")

PAGES = [
    ("home", "/"),
    ("apps", "/apps"),
    ("apps-all", "/apps?type=all"),
    ("games", "/games"),
    ("mods", "/mods"),
    ("categories", "/categories"),
    ("app-mod", "/app/newpipe-sample-mod"),
    ("app-mod-game", "/app/subway-surfers-demo-mod"),
    ("app-modtable", "/app/subway-surfers-demo-mod"),
    ("app-regular", "/app/signal"),
    ("app-game", "/app/minecraft"),
    ("search", "/search?q=fire"),
    ("notfound", "/nope"),
]

VIEWPORTS = [
    ("desktop", 1440, 900),
    ("mobile", 390, 844),
]


def main():
    wanted = dict(item.split("=", 1) for item in sys.argv[1:]) if len(sys.argv) > 1 else {}
    os.makedirs(OUT, exist_ok=True)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, width, height in VIEWPORTS:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=2 if label == "mobile" else 1,
                is_mobile=label == "mobile",
                has_touch=label == "mobile",
            )
            page = context.new_page()
            page.on("console", lambda msg: errors.append("console %s: %s" % (msg.type, msg.text))
                    if msg.type == "error" else None)
            page.on("pageerror", lambda exc: errors.append("pageerror: %s" % exc))
            for name, path in PAGES:
                if wanted and name not in wanted:
                    continue
                url = BASE + path
                response = page.goto(url, wait_until="networkidle", timeout=30000)
                status = response.status if response else 0
                page.wait_for_timeout(350)
                target = os.path.join(OUT, "%s-%s.png" % (name, label))
                page.screenshot(path=target, full_page=(label == "desktop"))
                print("%-14s %-9s %s %s" % (name, label, status, target))
            context.close()
        browser.close()
    if errors:
        print("\nBrowser errors:")
        for error in errors[:20]:
            print("  " + error)
        return 1
    print("\nno console errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
