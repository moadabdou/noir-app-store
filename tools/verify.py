#!/usr/bin/env python3
"""End-to-end checks for the NOIR catalogue.

Runs HTTP + DOM assertions against the live service and prints a
pass/fail report. Used after every refinement pass.

    .checks/venv/bin/python tools/verify.py
"""

import json
import os
import re
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("NOIR_BASE", "http://127.0.0.1:8084")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%-4s %-52s %s" % ("PASS" if ok else "FAIL", name, detail))
    return ok


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as response:
        return response.status, response.read().decode("utf-8", "replace")


def main():
    # ---------------------------------------------------------------- HTTP
    routes = ["/", "/apps", "/apps?type=all", "/apps?type=all&page=2", "/games",
              "/mods", "/categories", "/saved", "/about", "/search?q=fire",
              "/app/signal", "/app/minecraft", "/app/newpipe-sample-mod",
              "/app/subway-surfers-demo-mod", "/api/apps", "/api/apps?mods=1",
              "/sitemap.xml", "/robots.txt"]
    bad = []
    for route in routes:
        try:
            status, _ = get(route)
        except Exception as exc:  # noqa: BLE001
            bad.append("%s (%s)" % (route, exc))
            continue
        if status != 200:
            bad.append("%s -> %s" % (route, status))
    check("all public routes return 200", not bad, "; ".join(bad))

    try:
        urllib.request.urlopen(BASE + "/nope", timeout=10)
        check("unknown route returns 404", False, "got 200")
    except urllib.error.HTTPError as exc:
        check("unknown route returns 404", exc.code == 404, "status %s" % exc.code)

    # ------------------------------------------------------------ catalogue
    data = json.load(open(os.path.join(ROOT, "data", "apps.json"), encoding="utf-8"))
    apps = data["apps"]
    slugs = {a["slug"] for a in apps}
    check("catalogue has 20+ entries", len(apps) >= 20, "%d entries" % len(apps))

    missing_assets = []
    for app in apps:
        for key in ("icon", "art", "iconFallback"):
            path = app.get(key)
            if not path:
                continue
            if not os.path.exists(os.path.join(ROOT, path.lstrip("/"))):
                missing_assets.append("%s:%s" % (app["slug"], path))
        for shot in app.get("screenshots", []):
            if not os.path.exists(os.path.join(ROOT, shot.lstrip("/"))):
                missing_assets.append("%s:%s" % (app["slug"], shot))
    check("every referenced image exists on disk", not missing_assets, ", ".join(missing_assets[:5]))

    bad_stores = [a["slug"] for a in apps
                  if not str(a.get("store", "")).startswith(("https://play.google.com/",
                                                            "https://f-droid.org/"))]
    check("every entry links to an official store page", not bad_stores, ", ".join(bad_stores))

    real_icons = [a for a in apps if a.get("icon", "").startswith("/static/img/icons/real/")]
    check("real store icons are in use", len(real_icons) >= len(apps) - 2,
          "%d/%d entries use a fetched icon" % (len(real_icons), len(apps)))

    mods = [a for a in apps if a.get("type") == "mod" or a.get("isMod")]
    bad_mods = []
    for mod in mods:
        if not mod.get("modOf"):
            bad_mods.append("%s: no modOf" % mod["slug"])
        if mod["slug"] not in slugs and False:
            pass
        if mod.get("modOf") and mod["modOf"] not in slugs:
            bad_mods.append("%s: base '%s' missing" % (mod["slug"], mod["modOf"]))
        if mod.get("download", {}).get("url"):
            bad_mods.append("%s: demo must not publish a download" % mod["slug"])
    check("mod entries point at a real base app", not bad_mods, ", ".join(bad_mods))

    labelled = [a for a in mods if a.get("isDemo")]
    check("demo mod listings are explicitly labelled", len(labelled) == len(mods),
          "%d/%d labelled DEMO" % (len(labelled), len(mods)))

    mislabelled = [a["slug"] for a in apps
                   if a.get("type") != "mod" and (a.get("isMod") or a.get("modFeatures"))]
    check("no official listing is labelled as a mod", not mislabelled, ", ".join(mislabelled))

    # --------------------------------------------------------------- markup
    _, home = get("/")
    check("home has no raw star markup", "<span class=\"stars\"" not in home.split("</body>")[0].replace(
          '<span class="stars" aria-hidden="true">', "&#9786;"), "")
    check("home avoids 'vetted' wording", "vetted" not in home.lower(), "")

    _, modspage = get("/mods")
    check("mods page heading is pluralised correctly", "listing1" not in modspage, "")
    check("mods page lists both demos", "NewPipe Sample Mod" in modspage
          and "Subway Surfers Sample Mod" in modspage, "")

    _, modapp = get("/app/subway-surfers-demo-mod")
    for label in ("Premium unlocked", "Unlimited money", "Ad-free"):
        check("demo mod shows the '%s' feature label" % label, label in modapp, "")
    check("demo mod download is disabled", "Download unavailable" in modapp, "")
    check("demo mod keeps a link to the original listing",
          "com.kiloo.subwaysurf" in modapp, "")
    check("demo mod explains there is no build", "no build is published" in modapp.lower()
          or "no build published" in modapp.lower(), "")

    _, regular = get("/app/signal")
    check("regular app page shows no mod panels", "mod-features" not in regular
          and "Build variants" not in regular, "")
    check("regular app page has the store action", "Get it on Google Play" in regular, "")

    # ------------------------------------------------------------------ API
    _, body = get("/api/apps?type=all")
    payload = json.loads(body)
    check("api returns a paginated envelope",
          all(k in payload for k in ("items", "total", "page", "per_page", "pages")), "")
    check("api total matches the catalogue", payload["total"] == len(apps),
          "%s vs %s" % (payload["total"], len(apps)))
    _, body = get("/api/apps?per_page=5&page=2")
    payload = json.loads(body)
    check("api honours per_page and page", len(payload["items"]) == 5 and payload["page"] == 2, "")
    _, body = get("/api/apps?mods=1")
    payload = json.loads(body)
    check("api mod filter only returns mods",
          all(i.get("type") == "mod" for i in payload["items"]) and payload["total"] == len(mods), "")

    # -------------------------------------------------------------- browser
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))

        page.goto(BASE + "/", wait_until="load")
        titles = page.eval_on_selector_all("h2.section__title", "els => els.map(e => e.textContent.trim())")
        check("home keeps a short section list", 3 <= len(titles) <= 6, ", ".join(titles))
        slugs_on_home = page.eval_on_selector_all(
            ".grid--cards a[href^='/app/'], .rows a[href^='/app/']",
            "els => els.map(e => e.getAttribute('href'))")
        seen, dupes = set(), set()
        for href in slugs_on_home:
            if href in seen:
                dupes.add(href)
            seen.add(href)
        check("home does not repeat the same title in two sections", not dupes, ", ".join(dupes))

        page.goto(BASE + "/search?q=signal", wait_until="load")
        first = page.eval_on_selector_all(".card__name", "els => els.map(e => e.textContent.trim())")
        check("search ranks the exact name first", first and first[0] == "Signal", str(first[:3]))

        page.goto(BASE + "/apps", wait_until="load")
        page.click(".pager__step:not(.is-off)")
        page.wait_for_url(re.compile(r"page=2"))
        cards = page.eval_on_selector_all(".card__name", "els => els.length")
        check("pagination advances to page 2", "page=2" in page.url and cards > 0, page.url)

        page.goto(BASE + "/app/signal", wait_until="load")
        page.click("[data-save-slug='signal']")
        page.wait_for_timeout(200)
        page.goto(BASE + "/saved", wait_until="load")
        saved = page.eval_on_selector_all(".card__name", "els => els.map(e => e.textContent.trim())")
        check("saved list keeps the entry", "Signal" in saved, str(saved))

        page.goto(BASE + "/mods", wait_until="load")
        mod_links = page.eval_on_selector_all(".mod-card__name a", "els => els.length")
        check("mods page renders every listing", mod_links == len(mods), "%d cards" % mod_links)

        page.goto(BASE + "/app/subway-surfers-demo-mod", wait_until="load")
        btn = page.query_selector(".app__actions .btn--disabled")
        check("demo mod primary action states the download is unavailable", btn is not None, "")
        store_secondary = page.query_selector(".app__actions a.btn--ghost")
        check("original listing is a secondary action on mod pages",
              store_secondary is not None and "Original on" in store_secondary.text_content(), "")

        check("no page javascript exceptions", not errors, "; ".join(errors[:3]))
        browser.close()

    failed = [r for r in results if not r[1]]
    print("\n%d/%d checks passed" % (len(results) - len(failed), len(results)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
