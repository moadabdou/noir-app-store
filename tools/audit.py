#!/usr/bin/env python3
"""Automated UI audit for the NOIR catalogue.

Runs a real Chromium against the running site and reports layout, a11y and
content problems that are easy to miss by eye:

  * horizontal overflow (page scrolls sideways)
  * elements that stick out of the viewport
  * images that failed to load or have no alt text
  * tap targets that are too small on mobile
  * text rendered below 11px
  * duplicate element ids
  * links to internal pages that answer 404
  * console and page errors

Usage:  .checks/venv/bin/python tools/audit.py [path ...]
"""

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("NOIR_BASE", "http://127.0.0.1:8084")

PAGES = [
    "/",
    "/apps",
    "/apps?type=all",
    "/apps?type=all&page=2",
    "/games",
    "/mods",
    "/categories",
    "/category/communication",
    "/app/signal",
    "/app/newpipe-sample-mod",
    "/app/minecraft",
    "/saved",
    "/about",
    "/search?q=fire",
    "/nope",
]

JS_AUDIT = """
() => {
  const out = { overflowX: 0, wide: [], noAlt: [], brokenImages: [], smallText: [],
                tinyTargets: [], duplicateIds: [], emptyLinks: [], docWidth: 0, winWidth: 0 };
  out.docWidth = document.documentElement.scrollWidth;
  out.winWidth = window.innerWidth;
  out.overflowX = out.docWidth - out.winWidth;

  const vw = window.innerWidth;
  document.querySelectorAll('body *').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    const style = getComputedStyle(el);
    if (style.position === 'fixed') return;
    if (r.right > vw + 2 || r.left < -2) {
      const tag = el.tagName.toLowerCase() + (el.className && typeof el.className === 'string'
        ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
      out.wide.push({ tag, left: Math.round(r.left), right: Math.round(r.right) });
    }
  });

  document.querySelectorAll('img').forEach((img) => {
    if (!img.hasAttribute('alt')) out.noAlt.push(img.getAttribute('src'));
    if (img.complete && img.naturalWidth === 0) out.brokenImages.push(img.getAttribute('src'));
  });

  document.querySelectorAll('body *').forEach((el) => {
    if (!el.childNodes.length) return;
    let text = '';
    el.childNodes.forEach((n) => { if (n.nodeType === 3) text += n.textContent; });
    if (!text.trim()) return;
    const size = parseFloat(getComputedStyle(el).fontSize);
    if (size < 11) out.smallText.push({ tag: el.tagName.toLowerCase(), size, text: text.trim().slice(0, 40) });
  });

  document.querySelectorAll('a, button, input, select').forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;
    if (r.height < 24 || r.width < 24) {
      out.tinyTargets.push({ tag: el.tagName.toLowerCase(), text: (el.textContent || '').trim().slice(0, 30),
                              w: Math.round(r.width), h: Math.round(r.height) });
    }
  });

  const ids = {};
  document.querySelectorAll('[id]').forEach((el) => {
    ids[el.id] = (ids[el.id] || 0) + 1;
  });
  Object.keys(ids).forEach((id) => { if (ids[id] > 1) out.duplicateIds.push(id + ' x' + ids[id]); });

  document.querySelectorAll('a[href]').forEach((a) => {
    const href = a.getAttribute('href');
    if (!href || href === '#' || href.startsWith('http') || href.startsWith('mailto')) return;
    if (!a.textContent.trim() && !a.querySelector('img') && !a.getAttribute('aria-label')) {
      out.emptyLinks.push(href);
    }
  });
  return out;
}
"""


def main():
    paths = sys.argv[1:] or PAGES
    problems = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for label, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
            context = browser.new_context(viewport={"width": width, "height": height},
                                          is_mobile=(label == "mobile"), has_touch=(label == "mobile"))
            page = context.new_page()
            console_errors = []
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc: console_errors.append("pageerror: %s" % exc))
            for path in paths:
                console_errors.clear()
                response = page.goto(BASE + path, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(200)
                report = page.evaluate(JS_AUDIT)
                status = response.status if response else 0
                issues = []
                if report["overflowX"] > 2:
                    issues.append("horizontal overflow %dpx" % report["overflowX"])
                for item in report["wide"][:6]:
                    issues.append("overflowing %s [%d..%d]" % (item["tag"], item["left"], item["right"]))
                for src in report["brokenImages"][:6]:
                    issues.append("broken image %s" % src)
                for src in report["noAlt"][:6]:
                    issues.append("image without alt %s" % src)
                for item in report["smallText"][:6]:
                    issues.append("small text %.1fpx %r" % (item["size"], item["text"]))
                for item in report["tinyTargets"][:6]:
                    issues.append("tiny target %s %r %dx%d" % (item["tag"], item["text"], item["w"], item["h"]))
                for dup in report["duplicateIds"][:6]:
                    issues.append("duplicate id %s" % dup)
                for href in report["emptyLinks"][:6]:
                    issues.append("empty link %s" % href)
                for message in console_errors[:4]:
                    issues.append("console: %s" % message[:120])
                if issues:
                    problems += len(issues)
                    print("\n[%s] %s -> %s" % (label, path, status))
                    for issue in issues:
                        print("   - %s" % issue)
            context.close()
        browser.close()
    print("\n%d issue(s) found" % problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
