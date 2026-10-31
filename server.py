#!/usr/bin/env python3
"""NOIR - a self-contained AMOLED-black catalogue of Android apps and games.

Standard library only: a threaded HTTP server with real route handling that
renders every page from templates/ and data/apps.json.

Run:  python3 server.py            (honours $NOIR_PORT, default 8084)
"""

import gzip
import json
import os
import re
import sys
import time
import urllib.parse
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import catalogue as catalog_data  # noqa: E402  (module alias: the helper below is also called catalogue)

TEMPLATE_DIR = os.path.join(ROOT, "templates")
STATIC_DIR = os.path.join(ROOT, "static")
DATA_FILE = os.path.join(ROOT, "data", "apps.json")

HOST = os.environ.get("NOIR_HOST", "0.0.0.0")
PORT = int(os.environ.get("NOIR_PORT", "8084"))

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml; charset=utf-8",
}

TEMPLATE_CACHE = {}


# --------------------------------------------------------------------------- data


def load_data():
    return catalog_data.load()


def catalogue_apps():
    return catalog_data.apps()


def catalogue():
    return catalog_data.apps()


def categories():
    return catalog_data.categories()


def category_map():
    return catalog_data.category_map()


def find_app(slug):
    return catalog_data.find_app(slug)


def apps_by_type(kind):
    return [a for a in catalogue() if a["type"] == kind]


def mod_entries():
    return [a for a in catalogue() if catalog_data.is_mod(a)]


def is_mod(app):
    return catalog_data.is_mod(app)


def sort_apps(apps, sort):
    return catalog_data.sort_apps(apps, sort)


def search_apps(query):
    return catalog_data.filter_apps(catalogue(), query=query)


# --------------------------------------------------------------------------- helpers


def esc(value):
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def plural(count, singular, many=None):
    """Return a count with a correctly pluralised noun."""
    many = many or singular + "s"
    return "%s %s" % (count, singular if count == 1 else many)


def stars(rating):
    rating = float(rating)
    full = int(rating)
    half = 1 if rating - full >= 0.4 else 0
    empty = 5 - full - half
    out = '<span class="stars" aria-hidden="true">'
    out += '<span class="stars__on">&#9733;</span>' * full
    if half:
        out += '<span class="stars__half">&#9733;</span>'
    out += '<span class="stars__off">&#9733;</span>' * empty
    out += "</span>"
    return Safe(out)


def compact_number(value):
    value = int(value)
    if value >= 1000000:
        return "%.1fM".replace(".0", "") % (value / 1000000) if False else ("{:.1f}M".format(value / 1000000).replace(".0M", "M"))
    if value >= 1000:
        return "{:.1f}K".format(value / 1000).replace(".0K", "K")
    return str(value)


def format_date(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return value or "—"
    return parsed.strftime("%d %b %Y")


def days_ago(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return 999
    return max(0, (date.today() - parsed).days)


def rating_distribution(rating, total):
    weights = [max(0.0, (rating - offset)) for offset in (0, 1, 2, 3, 4)]
    total_weight = sum(weights) or 1.0
    shares = []
    for weight in weights:
        shares.append(int(round(total * (weight / total_weight) * 0.55)))
    shares[0] += max(0, total - sum(shares))
    buckets = [
        ("5", shares[0]), ("4", shares[1]), ("3", shares[2]), ("2", shares[3]), ("1", shares[4]),
    ]
    return buckets


# --------------------------------------------------------------------------- fragments


def app_card(app, cats=None):
    cats = cats if cats is not None else category_map()
    cat = cats.get(app["category"], {})
    cat_name = cat.get("name", app["category"].title())
    if is_mod(app):
        kind = "Mod"
    else:
        kind = "Game" if app["type"] == "game" else "App"
    badges = ""
    if is_mod(app):
        badges += '<span class="card__flag card__flag--mod">MOD</span>'
    if app.get("isDemo"):
        badges += '<span class="card__flag card__flag--demo">DEMO</span>'
    return f"""
<a class="card" href="/app/{esc(app['slug'])}" data-slug="{esc(app['slug'])}"
   data-name="{esc(app['name'].lower())}" data-type="{esc(app['type'])}"
   data-category="{esc(app['category'])}" data-rating="{app['rating']}"
   data-updated="{esc(app['updated'])}" data-size="{esc(app['size'])}"
   data-mod="{1 if is_mod(app) else 0}"
   data-search="{esc((app['name'] + ' ' + app['developer'] + ' ' + cat_name + ' ' + app['tagline']).lower())}">
  <div class="card__top">
    <img class="card__icon" src="{esc(app['icon'])}" alt="{esc(app['name'])} icon" width="64" height="64" loading="lazy">
    <span class="card__kind">{kind}</span>
    {badges}
  </div>
  <h3 class="card__name">{esc(app['name'])}</h3>
  <p class="card__dev">{esc(app['developer'])}</p>
  <div class="card__foot">
    <span class="pill pill--rating">{stars(app['rating'])}<b>{app['rating']}</b></span>
    <span class="pill">{esc(app['size'])}</span>
  </div>
  <div class="card__tags">
    <span class="tag">{esc(cat_name)}</span>
    <span class="tag">{esc(app['android'])}</span>
  </div>
</a>
"""


def compact_row(app, index=None):
    rank = ""
    if index is not None:
        rank = f'<span class="row__rank">{index + 1}</span>'
    return f"""
<a class="row" href="/app/{esc(app['slug'])}">
  {rank}
  <img class="row__icon" src="{esc(app['icon'])}" alt="" width="52" height="52" loading="lazy">
  <span class="row__body">
    <span class="row__name">{esc(app['name'])}</span>
    <span class="row__dev">{esc(app['developer'])}</span>
  </span>
  <span class="row__meta">
    <span class="row__rating">{stars(app['rating'])}<b>{app['rating']}</b></span>
    <span class="row__cat">{esc(app['category'].title())}</span>
  </span>
</a>
"""


def category_chip(cat, active=None, count=None):
    cls = "chip is-active" if active == cat["slug"] else "chip"
    label = esc(cat["name"])
    if count is not None:
        label += f'<span class="chip__count">{count}</span>'
    return f'<a class="{cls}" href="/category/{esc(cat["slug"])}">{label}</a>'


# --------------------------------------------------------------------------- templates


def load_template(name):
    path = os.path.join(TEMPLATE_DIR, name)
    stamp = os.path.getmtime(path)
    cached = TEMPLATE_CACHE.get(name)
    if cached and cached[0] == stamp:
        return cached[1]
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read()
    TEMPLATE_CACHE[name] = (stamp, content)
    return content


class Safe(str):
    """Marker for template fragments that must not be escaped."""


TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][A-Za-z0-9_\.]*)\s*\}\}")
BLOCK_RE = re.compile(r"\{\{#([a-zA-Z_][A-Za-z0-9_]*)\}\}(.*?)\{\{/\1\}\}", re.S)


def resolve(path, context):
    parts = path.split(".")
    value = context.get(parts[0])
    for part in parts[1:]:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            value = getattr(value, part, None)
    return value


def truthy(value):
    if value is None or value is False:
        return False
    if isinstance(value, (str, list, tuple, dict, set)):
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0
    return True


def render(template, context):
    text = load_template(template)

    def expand(match):
        name = match.group(1)
        body = match.group(2)
        if truthy(resolve(name, context)):
            return body
        return ""

    # Conditional blocks first, then plain tokens.
    for _ in range(6):
        text, count = BLOCK_RE.subn(expand, text)
        if not count:
            break

    def substitute(match):
        value = resolve(match.group(1), context)
        if value is None:
            return ""
        if isinstance(value, Safe):
            return str(value)
        return esc(value)

    return TOKEN_RE.sub(substitute, text)


def render_page(template, context):
    body = render(template, context)
    context = dict(context)
    context["content"] = Safe(body)
    return render("base.html", context)


# --------------------------------------------------------------------------- pages


def build_home():
    cats = category_map()
    apps = catalogue()
    hero = next((a for a in apps if a.get("hero")), apps[0])
    mods = sort_apps(mod_entries(), "popular")
    # Sections must not repeat the same title, so every list below is
    # de-duplicated against the ones rendered before it.
    pool = [a for a in apps if a["type"] != "mod"]
    trending = [a for a in sort_apps([a for a in pool if a.get("trending")], "popular")
                if a["slug"] != hero["slug"]][:8]
    charts = [a for a in sort_apps(pool, "popular")
              if a["slug"] not in {t["slug"] for t in trending}][:6]
    games = [a for a in pool if a["type"] == "game"]
    game_hero = games[0] if games else None
    seen = ({a["slug"] for a in trending} | {a["slug"] for a in charts}
            | {hero["slug"]} | ({game_hero["slug"]} if game_hero else set()))
    latest = [a for a in sorted(pool, key=lambda a: a["updated"], reverse=True)
              if a["slug"] not in seen][:6]

    context = {
        "title": "NOIR - Android apps, games and mod listings",
        "description": "NOIR is an independent catalogue of Android apps, games and clearly labelled mod listings. Read the notes, compare versions and jump straight to the official store listing.",
        "active_nav": "home",
        "body_class": "page-home",
        "hero": hero,
        "hero_stars": stars(hero["rating"]),
        "hero_cats": cats,
        "trending": Safe("".join(app_card(a, cats) for a in trending)),
        "latest": Safe("".join(app_card(a, cats) for a in latest)),
        "charts": Safe("".join(compact_row(a, i) for i, a in enumerate(charts))),
        "mod_strip": Safe("".join(mod_card_html(a) for a in mods[:2])),
        "mod_count": len(mods),
        "mod_count_label": plural(len(mods), "mod listing"),
        "has_mods": bool(mods),
        "game_hero": game_hero,
        "game_hero_stars": stars(game_hero["rating"]) if game_hero else "",
        "chips": Safe("".join(category_chip(c, count=None) for c in categories())),
        "app_count": len([a for a in apps if a["type"] == "app"]),
        "game_count": len(games),
        "total_downloads": sum(int(a["downloads"].replace("B+", "000000000").replace("M+", "000000").replace("K+", "000")) for a in apps),
    }
    return render_page("home.html", context)


def build_pager(meta, base_path, params=None):
    """Render a pager for the current catalogue view."""
    if not meta or meta["pages"] <= 1:
        return ""
    query = dict(params or {})
    query.pop("page", None)

    def link(number):
        pairs = ["%s=%s" % (k, urllib.parse.quote(str(v))) for k, v in query.items() if v not in (None, "")]
        pairs.append("page=%d" % number)
        return "%s?%s" % (base_path, "&amp;".join(pairs))

    numbers = []
    for number in range(1, meta["pages"] + 1):
        classes = "pager__page"
        if number == meta["page"]:
            classes += " is-active"
        numbers.append('<a class="%s" href="%s"%s>%d</a>' % (
            classes, link(number),
            ' aria-current="page"' if number == meta["page"] else "",
            number,
        ))

    prev_link = '<a class="pager__step" href="%s">Previous</a>' % link(meta["prev"]) if meta["has_prev"] else '<span class="pager__step is-off">Previous</span>'
    next_link = '<a class="pager__step" href="%s">Next</a>' % link(meta["next"]) if meta["has_next"] else '<span class="pager__step is-off">Next</span>'
    return (
        '%s<span class="pager__pages">%s</span>%s'
        '<span class="pager__count">Page %d of %d</span>'
        % (prev_link, "".join(numbers), next_link, meta["page"], meta["pages"])
    )


def build_catalog(kind="app", category=None, query=None, sort="popular", page=1,
                  mods=False, per_page=catalog_data.PER_PAGE):
    cats = category_map()
    apps = catalogue()
    title = "Apps"
    eyebrow = "Catalogue"
    blurb = "Every application in the NOIR shelf, in one searchable list."
    if kind == "game" and not category:
        title = "Games"
        eyebrow = "Catalogue"
        blurb = "Hand-picked games for Android, from arcade score chasers to slow puzzles."
    elif kind == "all" and not category and not query:
        title = "Everything"
        eyebrow = "Catalogue"
        blurb = "The full NOIR shelf: every app and every game in one list."
    if category:
        cat = cats.get(category)
        if not cat:
            return None
        title = cat["name"]
        eyebrow = "Category"
        blurb = cat.get("blurb", "")
        apps = [a for a in apps if a["category"] == category]
    elif kind == "game":
        apps = [a for a in apps if a["type"] == "game"]
    elif kind == "app":
        apps = [a for a in apps if a["type"] == "app"]
    if mods:
        apps = [a for a in apps if is_mod(a)]
        title = "Mods"
        eyebrow = "Mods"
        blurb = "Community builds of the apps you already use, with the changes spelled out."
    if query:
        matched = search_apps(query)
        allowed = {a["slug"] for a in apps}
        apps = [a for a in matched if a["slug"] in allowed]
        title = "Search results"
        eyebrow = "Search"
        blurb = "{0} result{1} for “{2}”".format(len(apps), "" if len(apps) == 1 else "s", query)

    total_matched = len(apps)
    apps = sort_apps(apps, sort)
    counts = {}
    for app in apps:
        counts[app["category"]] = counts.get(app["category"], 0) + 1

    visible_cats = [c for c in categories() if counts.get(c["slug"])]
    app_total = len([a for a in catalogue() if a["type"] == "app"])
    game_total = len([a for a in catalogue() if a["type"] == "game"])
    mod_total = len(mod_entries())
    all_total = app_total + game_total + mod_total
    active_kind = "game" if kind == "game" else ("app" if kind == "app" else "all")
    tab_defs = [
        ("all", "Everything", "/apps?type=all", all_total),
        ("app", "Apps", "/apps", app_total),
        ("game", "Games", "/games", game_total),
    ]
    tabs = "".join(
        '<a class="tab{cls}" href="{href}">{label}<span class="tab__count">{count}</span></a>'.format(
            cls=" is-active" if key == active_kind else "",
            href=href,
            label=label,
            count=count,
        )
        for key, label, href, count in tab_defs
    )
    page_items, meta = catalog_data.paginate(apps, page=page, per_page=per_page)
    base_path = "/category/%s" % category if category else ("/games" if kind == "game" else "/apps")
    pager_params = {"type": kind if kind != "all" else "all", "sort": sort}
    if query:
        pager_params["q"] = query
    if mods:
        pager_params["mods"] = 1
    context = {
        "title": "%s - NOIR" % title,
        "description": blurb,
        "active_nav": "games" if kind == "game" else "apps",
        "body_class": "page-catalog",
        "heading": title,
        "eyebrow": eyebrow,
        "blurb": blurb,
        "result_count": total_matched,
        "cards": Safe("".join(app_card(a, cats) for a in page_items)),
        "chips": Safe("".join(category_chip(c, active=category, count=counts.get(c["slug"], 0)) for c in visible_cats)),
        "tabs": Safe(tabs),
        "query": query or "",
        "sort": sort,
        "kind": kind,
        "active_category": category or "",
        "empty": not page_items,
        "search_hint": "Search {0} titles, developers and categories".format(len(catalogue())),
        "pager": Safe(build_pager(meta, base_path, pager_params)),
        "page_meta": meta,
        "page_size": meta.get("per_page", catalog_data.PER_PAGE),
        "mods_only": bool(mods),
        "mod_count": mod_total,
        "mods_class": " is-active" if mods else "",
    }
    return render_page("catalog.html", context)


def build_category(slug):
    cats = category_map()
    if slug not in cats:
        return None
    cat = cats[slug]
    kind = "game" if cat["kind"] == "game" else "app"
    return build_catalog(kind=kind, category=slug)


def build_app(slug):
    app = find_app(slug)
    if not app:
        return None
    cats = category_map()
    cat = cats.get(app["category"], {})
    mod = is_mod(app)
    # Demo listings are examples, not recommendations: they stay out of the
    # "similar" rail of official apps (a mod page may still point at one).
    def recommendable(entry):
        if entry.get("isDemo") and not mod:
            return False
        return True

    same_cat = [a for a in catalogue() if a["category"] == app["category"]
                and a["slug"] != slug and recommendable(a)]
    similar = same_cat[:6]
    more = []
    if len(similar) < 3:
        # The category is thin: keep the category rail honest and show the
        # general picks in a clearly separate rail instead of mixing them in.
        more = [a for a in catalogue() if a["category"] != app["category"]
                and a["slug"] != slug and recommendable(a)][:6]
    similar_title = "Similar in %s" % cat.get("name", app["category"].title())
    similar_link = "/category/%s" % app["category"]
    similar_link_label = "See the category"
    newest = sorted(catalogue(), key=lambda a: a["updated"], reverse=True)
    updated_days = days_ago(app["updated"])

    jsonld = {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": app["name"],
        "applicationCategory": cat.get("name", app["category"].title()),
        "operatingSystem": "Android " + app["android"].replace("Android ", ""),
        "softwareVersion": app["version"],
        "description": app["description"],
        "aggregateRating": {
            "@type": "AggregateRating",
            "ratingValue": app["rating"],
            "ratingCount": app["ratings"],
        },
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
        "url": "https://play.google.com/store/apps/details?id=" + app["store"].split("id=")[-1],
    }

    base_app = find_app(app.get("modOf", "")) if app.get("modOf") else None
    download = app.get("download") or {}
    download_url = download.get("url") or ""
    context = {
        "title": "%s - %s - NOIR" % (app["name"], cat.get("name", "Android")),
        "description": "%s by %s. %s" % (app["name"], app["developer"], app["tagline"]),
        "active_nav": "mods" if mod else ("apps" if app["type"] == "app" else "games"),
        "body_class": "page-app page-app--mod" if mod else "page-app",
        "app": app,
        "cat_name": cat.get("name", app["category"].title()),
        "cat_slug": app["category"],
        "stars": stars(app["rating"]),
        "highlights": Safe("".join(
            '<li class="highlight"><span class="highlight__tick">&#10003;</span><span>%s</span></li>' % esc(h)
            for h in app["highlights"]
        )),
        "shots": Safe("".join(
            '<figure class="shot"><img src="%s" alt="%s screenshot %d" width="540" height="1080" loading="lazy"></figure>'
            % (esc(src), esc(app["name"]), i + 1)
            for i, src in enumerate(app["screenshots"])
        )),
        "permissions": Safe("".join('<span class="pill pill--soft">%s</span>' % esc(p) for p in app.get("permissions", []))),
        "rating_bars": Safe("".join(
            '<div class="bar"><span class="bar__label">%s</span><span class="bar__track"><span class="bar__fill" style="width:%d%%"></span></span><span class="bar__value">%s</span></div>'
            % (star, int(round(share / max(1, app["ratings"]) * 100)), compact_number(share))
            for star, share in rating_distribution(app["rating"], app["ratings"])
        )),
        "similar": Safe("".join(app_card(a, cats) for a in similar)),
        "more": Safe("".join(app_card(a, cats) for a in more)),
        "has_more": bool(more),
        "similar_title": similar_title,
        "similar_link": similar_link,
        "similar_link_label": similar_link_label,
        "is_original": not mod,
        "latest_same": Safe("".join(
            app_card(a, cats) for a in newest
            if a["slug"] != slug and not a.get("isDemo")
        )[:6]),
        "jsonld": Safe(json.dumps(jsonld)),
        "updated_days": updated_days,
        "store_name": app.get("storeName", "Google Play"),
        "is_game": app["type"] == "game",
        "is_mod": mod,
        "is_demo": bool(app.get("isDemo")),
        "is_not_demo": not bool(app.get("isDemo")),
        "mod_base": base_app,
        "mod_base_name": base_app["name"] if base_app else "",
        "mod_base_slug": base_app["slug"] if base_app else "",
        "mod_features": Safe("".join(
            '<li class="mod-feature"><span class="mod-feature__name">%s</span>'
            '<span class="mod-feature__detail">%s</span></li>' % (esc(f.get("name", "")), esc(f.get("detail", "")))
            for f in app.get("modFeatures", []) or []
        )),
        "mod_feature_count": len(app.get("modFeatures", []) or []),
        "mod_variants": Safe("".join(
            '<tr><th scope="row">%s</th><td>%s</td><td>%s</td><td>%s</td></tr>' % (
                esc(v.get("name", "")), esc(v.get("version", "—")), esc(v.get("size", "—")), esc(v.get("arch", "—")))
            for v in app.get("modVariants", []) or []
        )),
        "mod_has_variants": bool(app.get("modVariants")),
        "mod_install_steps": Safe("".join(
            '<li class="mod-step"><span class="mod-step__num">%d</span><span>%s</span></li>' % (i + 1, esc(step))
            for i, step in enumerate(app.get("modInstallSteps", []) or [])
        )),
        "mod_has_steps": bool(app.get("modInstallSteps")),
        "mod_faq": Safe("".join(
            '<details class="mod-faq__item"><summary>%s</summary><p>%s</p></details>' % (
                esc(f.get("name") or f.get("question") or ""), esc(f.get("detail") or f.get("answer") or ""))
            for f in app.get("modFaq", []) or []
        )),
        "mod_has_faq": bool(app.get("modFaq")),
        "mod_disclaimer": app.get("modDisclaimer", ""),
        "package_id": app.get("packageId", ""),
        "build_type": app.get("buildType", ""),
        "download_url": download_url,
        "download_label": download.get("label", "Download build"),
        "download_unavailable": download.get("unavailableReason", ""),
        "download_sha": download.get("sha256", ""),
        "has_download": bool(download_url),
    }
    return render_page("app.html", context)


def mod_card_html(app):
    """Render a mod listing card. Shared by /mods and the home page strip."""
    base = find_app(app.get("modOf", "")) if app.get("modOf") else None
    features = app.get("modFeatures", []) or []
    download = app.get("download") or {}
    return (
        '<article class="mod-card{cls}">'
        '<a class="mod-card__icon" href="/app/{slug}"><img src="{icon}" alt="{name} icon" width="72" height="72" loading="lazy"></a>'
        '<div class="mod-card__body">'
        '<div class="mod-card__head"><h3 class="mod-card__name"><a href="/app/{slug}">{name}</a></h3>{flags}</div>'
        '<p class="mod-card__dev">{dev}</p>'
        '<p class="mod-card__tagline">{tagline}</p>'
        '<ul class="mod-card__features">{features}</ul>'
        '<p class="mod-card__base">{base}</p>'
        '<p class="mod-card__state">{state}</p>'
        '</div></article>'.format(
            slug=esc(app["slug"]),
            icon=esc(app["icon"]),
            name=esc(app["name"]),
            dev=esc(app["developer"]),
            tagline=esc(app["tagline"]),
            cls=" mod-card--demo" if app.get("isDemo") else "",
            flags=('<span class="card__flag card__flag--mod">MOD</span>'
                   + ('<span class="card__flag card__flag--demo">DEMO</span>' if app.get("isDemo") else "")),
            features="".join(
                '<li><span class="mod-feature__name">%s</span><span class="mod-feature__detail">%s</span></li>'
                % (esc(f.get("name", "")), esc(f.get("detail", ""))) for f in features[:4]
            ),
            base=('Based on <a href="/app/%s">%s</a>' % (esc(base["slug"]), esc(base["name"]))) if base else "Standalone build",
            state=("Build available" if download.get("url")
                   else esc(download.get("unavailableReason", "No build published"))),
        )
    )


def build_mods():
    """Landing page for mod listings."""
    entries = sort_apps(mod_entries(), "popular")
    blocks = [mod_card_html(app) for app in entries]
    context = {
        "title": "Mods - NOIR",
        "description": "Community builds of the apps you already use, with every change spelled out before you install.",
        "active_nav": "mods",
        "body_class": "page-mods",
        "mod_cards": Safe("".join(blocks)),
        "mod_count": len(entries),
        "mod_count_label": plural(len(entries), "mod listing"),
    }
    return render_page("mods.html", context)


def build_categories():
    cats = category_map()
    apps = catalogue()
    blocks = []
    for cat in categories():
        items = [a for a in apps if a["category"] == cat["slug"]]
        if not items:
            continue
        blocks.append(
            '<a class="cat-card" href="/category/{slug}">'
            '<span class="cat-card__icon cat-card__icon--{kind}">{icon}</span>'
            '<span class="cat-card__body"><span class="cat-card__name">{name}</span>'
            '<span class="cat-card__count">{count} titles</span></span>'
            '<span class="cat-card__blurb">{blurb}</span></a>'.format(
                slug=esc(cat["slug"]),
                kind=esc(cat["kind"]),
                icon=category_glyph(cat.get("icon", "cube")),
                name=esc(cat["name"]),
                count=len(items),
                blurb=esc(cat.get("blurb", "")),
            )
        )
    context = {
        "title": "Categories - NOIR",
        "description": "Browse the NOIR catalogue by category, from communication tools to pocket-sized puzzles.",
        "active_nav": "categories",
        "body_class": "page-categories",
        "categories": Safe("".join(blocks)),
        "category_count": len(categories()),
        "catalog_json": Safe(catalog_json()),
    }
    return render_page("categories.html", context)


def category_glyph(name):
    glyphs = {
        "chat": '<path d="M6 10a4 4 0 0 1 4-4h12a4 4 0 0 1 4 4v7a4 4 0 0 1-4 4h-6l-6 5v-5h-4a4 4 0 0 1-4-4z"/>',
        "globe": '<path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 0c3 3 3 15 0 18M3.6 9h16.8M3.6 15h16.8"/>',
        "play": '<path d="M9 7l8 5-8 5z"/>',
        "layers": '<path d="M12 3l9 5-9 5-9-5 9-5zm9 9l-9 5-9-5m18 4.5l-9 5-9-5"/>',
        "shield": '<path d="M12 3l8 3v6c0 4.5-3.2 7.8-8 9-4.8-1.2-8-4.5-8-9V6z"/>',
        "tool": '<path d="M14.5 4.5a4 4 0 0 1 5 5l-8 8-5-5z"/><path d="M4 20l3-1-2-2z"/>',
        "code": '<path d="M9 7l-5 5 5 5M15 7l5 5-5 5"/>',
        "brush": '<path d="M7 21c-2 0-3-1.5-2-3.5C6 15 7 13 9 12l5-8 4 3-8 6c-1 2-1 8-3 8z"/>',
        "map": '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zm0 0v14m6-12v14"/>',
        "bolt": '<path d="M13 2L4 14h6l-1 8 9-12h-6z"/>',
        "flame": '<path d="M12 3c1 4-3 5-3 9a3 3 0 0 0 6 0c0-2-1-3-1-3 3 2 4 5 4 7a6 6 0 0 1-12 0c0-6 6-8 6-13z"/>',
        "gem": '<path d="M12 2l8 7-8 13L4 9z"/>',
        "tower": '<path d="M9 22V9h3V4h3v5h3v13z"/>',
        "rocket": '<path d="M12 2c4 3 6 7 6 11l-3 3H9l-3-3c0-4 2-8 6-11zm-3 16v3h6v-3"/>',
        "cube": '<path d="M12 2l9 5v10l-9 5-9-5V7z"/>',
        "leaf": '<path d="M20 4C10 4 4 9 4 16c0 2 1 4 2 4 8 0 12-6 12-16z"/>',
        "target": '<path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 5a4 4 0 1 0 0 8 4 4 0 0 0 0-8z"/>',
        "cube2": '<path d="M12 2l9 5v10l-9 5-9-5V7z"/>',
    }
    path = glyphs.get(name, glyphs["cube"])
    return (
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" '
        'stroke-linecap="round" stroke-linejoin="round" width="22" height="22" aria-hidden="true">%s</svg>' % path
    )


def catalog_json():
    names = {c["slug"]: c["name"] for c in categories()}
    return json.dumps([catalog_data.slim(a, names) for a in catalogue()], ensure_ascii=False).replace("</", "<\\/")


def build_saved():
    context = {
        "title": "Saved - NOIR",
        "description": "Your bookmarked NOIR picks, stored privately in this browser.",
        "active_nav": "saved",
        "body_class": "page-saved",
        "catalog_json": Safe(catalog_json()),
    }
    return render_page("saved.html", context)


def build_about():
    context = {
        "title": "About - NOIR",
        "description": "How NOIR curates its catalogue and why every link points to an official store listing.",
        "active_nav": "about",
        "body_class": "page-about",
        "app_count": len(apps_by_type("app")),
        "game_count": len(apps_by_type("game")),
    }
    return render_page("about.html", context)


def build_404(path):
    cats = category_map()
    popular = sort_apps(catalogue(), "popular")[:6]
    context = {
        "title": "Page not found - NOIR",
        "description": "That page does not exist in the NOIR catalogue.",
        "active_nav": "",
        "body_class": "page-404",
        "missing_path": path,
        "status": "404",
        "popular": Safe("".join(app_card(a, cats) for a in popular)),
        "catalog_json": Safe(catalog_json()),
    }
    return render_page("404.html", context)


# --------------------------------------------------------------------------- handler


class Handler(BaseHTTPRequestHandler):
    server_version = "NOIR/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self):
        self.respond(body=True)

    def do_HEAD(self):
        self.respond(body=False)

    def respond(self, body=True):
        try:
            parsed = urllib.parse.urlparse(self.path)
            path = urllib.parse.unquote(parsed.path)
            query = urllib.parse.parse_qs(parsed.query)
            status, content_type, payload = self.route(path, query)
        except Exception:
            sys.stderr.write("error handling %s\n" % self.path)
            import traceback
            traceback.print_exc()
            status, content_type, payload = 500, "text/html; charset=utf-8", self.error_page("Internal error")

        body_bytes = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        headers = {
            "Content-Type": content_type,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "strict-origin-when-cross-origin",
        }
        if status == 200:
            headers["Cache-Control"] = "public, max-age=300"
        else:
            headers["Cache-Control"] = "no-store"

        accepts_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
        if accepts_gzip and len(body_bytes) > 900 and content_type.startswith(("text/", "application/json", "image/svg")):
            body_bytes = gzip.compress(body_bytes, 6)
            headers["Content-Encoding"] = "gzip"
            headers["Vary"] = "Accept-Encoding"

        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        if body:
            try:
                self.wfile.write(body_bytes)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def error_page(self, message):
        return build_404(message)

    # -- query helpers ------------------------------------------------------
    def page_number(self, query):
        try:
            return max(1, int(query.get("page", ["1"])[0]))
        except (TypeError, ValueError):
            return 1

    def flag(self, query, name):
        value = query.get(name, [""])[0]
        return str(value).lower() in ("1", "true", "yes", "on")

    # -- routing ------------------------------------------------------------
    def route(self, path, query):
        if path.startswith("/static/"):
            return self.serve_static(path)
        if path in ("/", "/index.html"):
            return 200, "text/html; charset=utf-8", build_home()
        if path in ("/apps", "/apps/"):
            kind = query.get("type", ["app"])[0]
            if kind not in ("app", "game", "all"):
                kind = "app"
            return 200, "text/html; charset=utf-8", build_catalog(
                kind=kind,
                sort=(query.get("sort", ["popular"])[0]),
                page=self.page_number(query),
                mods=self.flag(query, "mods"),
            )
        if path in ("/games", "/games/"):
            return 200, "text/html; charset=utf-8", build_catalog(
                kind="game",
                sort=(query.get("sort", ["popular"])[0]),
                page=self.page_number(query),
                mods=self.flag(query, "mods"),
            )
        if path in ("/mods", "/mods/"):
            return 200, "text/html; charset=utf-8", build_mods()
        if path == "/categories":
            return 200, "text/html; charset=utf-8", build_categories()
        if path == "/saved":
            return 200, "text/html; charset=utf-8", build_saved()
        if path == "/about":
            return 200, "text/html; charset=utf-8", build_about()
        if path == "/search":
            q = (query.get("q", [""])[0] or "").strip()
            kind = query.get("type", ["all"])[0]
            if kind not in ("app", "game", "all"):
                kind = "all"
            sort = query.get("sort", ["popular"])[0]
            category = query.get("category", [""])[0] or None
            if q:
                html = build_catalog(kind=kind, category=category, query=q, sort=sort,
                                     page=self.page_number(query))
                if html is None:
                    return 404, "text/html; charset=utf-8", build_404(path)
                return 200, "text/html; charset=utf-8", html
            target = "/games" if kind == "game" else "/apps"
            if category:
                target = "/category/" + category
            return 302, "text/html; charset=utf-8", self.redirect(target)
        match = re.match(r"^/category/([a-z0-9\-]+)/?$", path)
        if match:
            html = build_category(match.group(1))
            if html is None:
                return 404, "text/html; charset=utf-8", build_404(path)
            return 200, "text/html; charset=utf-8", html
        match = re.match(r"^/app/([a-z0-9\-]+)/?$", path)
        if match:
            html = build_app(match.group(1))
            if html is None:
                return 404, "text/html; charset=utf-8", build_404(path)
            return 200, "text/html; charset=utf-8", html
        if path == "/api/apps":
            kind = query.get("type", ["all"])[0]
            if kind not in ("app", "game", "all"):
                kind = "all"
            items = catalog_data.filter_apps(
                catalogue(),
                kind=kind,
                category=(query.get("category", [""])[0] or None),
                query=(query.get("q", [""])[0] or None),
                mods=True if self.flag(query, "mods") else None,
            )
            items = catalog_data.sort_apps(items, query.get("sort", ["popular"])[0])
            per_page = int(query.get("per_page", [catalog_data.PER_PAGE])[0] or catalog_data.PER_PAGE)
            page_items, meta = catalog_data.paginate(items, page=self.page_number(query), per_page=per_page)
            names = {c["slug"]: c["name"] for c in categories()}
            payload = {
                "items": [catalog_data.slim(a, names) for a in page_items],
                "total": meta["total"],
                "page": meta["page"],
                "per_page": meta["per_page"],
                "pages": meta["pages"],
                "has_next": meta["has_next"],
                "has_prev": meta["has_prev"],
            }
            return 200, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False)
        match = re.match(r"^/api/apps/([a-z0-9\-]+)$", path)
        if match:
            app = find_app(match.group(1))
            if not app:
                return 404, "application/json; charset=utf-8", json.dumps({"error": "not found"})
            return 200, "application/json; charset=utf-8", json.dumps(app, ensure_ascii=False)
        if path == "/robots.txt":
            return 200, "text/plain; charset=utf-8", "User-agent: *\nAllow: /\n"
        if path == "/sitemap.xml":
            urls = ["<url><loc>http://localhost:%d/</loc></url>" % PORT]
            urls.append("<url><loc>http://localhost:%d/apps</loc></url>" % PORT)
            urls.append("<url><loc>http://localhost:%d/games</loc></url>" % PORT)
            urls.append("<url><loc>http://localhost:%d/categories</loc></url>" % PORT)
            for app in catalogue():
                urls.append("<url><loc>http://localhost:%d/app/%s</loc></url>" % (PORT, app["slug"]))
            xml = ('<?xml version="1.0" encoding="UTF-8"?>'
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % "".join(urls))
            return 200, "application/xml; charset=utf-8", xml
        if path == "/favicon.ico":
            icon = os.path.join(STATIC_DIR, "img", "favicon.svg")
            if os.path.exists(icon):
                with open(icon, "rb") as handle:
                    return 200, "image/svg+xml", handle.read()
        return 404, "text/html; charset=utf-8", build_404(path)

    def redirect(self, location):
        body = '<!doctype html><meta http-equiv="refresh" content="0; url=%s"><a href="%s">Continue</a>' % (location, location)
        return body

    # -- static -------------------------------------------------------------
    def serve_static(self, path):
        relative = path[len("/static/"):]
        relative = urllib.parse.unquote(relative)
        target = os.path.normpath(os.path.join(STATIC_DIR, relative))
        if not target.startswith(STATIC_DIR) or not os.path.isfile(target):
            return 404, "text/html; charset=utf-8", build_404(path)
        extension = os.path.splitext(target)[1].lower()
        content_type = MIME_TYPES.get(extension, "application/octet-stream")
        with open(target, "rb") as handle:
            payload = handle.read()
        stamp = int(os.path.getmtime(target))
        etag = '"%x-%x"' % (stamp, len(payload))
        if self.headers.get("If-None-Match") == etag:
            return 304, "text/plain", b""
        return 200, content_type, payload


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    server = Server((HOST, PORT), Handler)
    sys.stderr.write("NOIR serving on http://%s:%d\n" % (HOST, PORT))
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
