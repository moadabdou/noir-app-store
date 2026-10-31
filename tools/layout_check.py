#!/usr/bin/env python3
"""Measure horizontal overflow and column overlap across widths and routes."""
import json
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8084"
PATHS = [
    "/",
    "/apps",
    "/apps?type=all",
    "/apps?type=all&page=2",
    "/games",
    "/mods",
    "/categories",
    "/app/signal",
    "/app/newpipe-sample-mod",
    "/app/minecraft",
    "/search?q=fire",
    "/saved",
    "/about",
    "/nope",
]
WIDTHS = [360, 390, 768, 1024, 1440]


def measure(page, path, width):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(BASE + path, wait_until="load")
    return page.evaluate(
        """() => {
        const doc = document.documentElement;
        const win = window.innerWidth;
        const overflow = doc.scrollWidth - win;
        const wide = [];
        document.querySelectorAll('body *').forEach((el) => {
          const r = el.getBoundingClientRect();
          if (r.width === 0 || r.height === 0) return;
          if (r.right > win + 1 || r.left < -1) {
            const s = getComputedStyle(el);
            if (s.position === 'fixed') return;
            if (el.closest('.skip-link')) return;
            if (el.closest('[style*="overflow"], .shots, .subnav, .chips--scroll, .pager, .table-scroll')) return;
            wide.push(el.tagName.toLowerCase() + '.' + (el.className || '').toString().split(' ')[0] +
                      ' [' + Math.round(r.left) + '..' + Math.round(r.right) + ']');
          }
        });
        const layout = document.querySelector('.app__layout');
        let overlap = null;
        if (layout) {
          const main = layout.querySelector('.app__main');
          const side = layout.querySelector('.app__side');
          if (main && side) {
            const a = main.getBoundingClientRect();
            const b = side.getBoundingClientRect();
            const horiz = Math.min(a.right, b.right) - Math.max(a.left, b.left);
            const vert = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
            if (horiz > 2 && vert > 2) overlap = Math.round(horiz);
          }
        }
        const rawStars = document.body.innerText.includes('<span class="stars"');
        return {overflow, wide: wide.slice(0, 6), overlap, rawStars,
                title: document.title.slice(0, 40)};
      }"""
    )


def main():
    problems = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context()
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        for path in PATHS:
            for width in WIDTHS:
                r = measure(page, path, width)
                flags = []
                if r["overflow"] > 1:
                    flags.append("overflow=%dpx" % r["overflow"])
                if r["wide"]:
                    flags.append("wide=" + ", ".join(r["wide"]))
                if r["overlap"]:
                    flags.append("main/side overlap=%dpx" % r["overlap"])
                if r["rawStars"]:
                    flags.append("RAW STAR MARKUP VISIBLE")
                if flags:
                    problems += 1
                    print("[%5d] %-28s %s" % (width, path, " | ".join(flags)))
        if errors:
            print("\nconsole/page errors:")
            for e in sorted(set(errors)):
                print("  -", e)
        browser.close()
    print("\n%d problem(s) across %d pages x %d widths" % (problems, len(PATHS), len(WIDTHS)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
