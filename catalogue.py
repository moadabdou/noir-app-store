#!/usr/bin/env python3
"""NOIR catalogue core: loading, validation, filtering, sorting and paging.

Standard library only. This module is the single source of truth for how
`data/apps.json` is read, so the web server (server.py) and the publishing
CLI (tools/catalog.py) always agree on the schema and the rules.
"""

import json
import os
import re
import unicodedata

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(ROOT, "data", "apps.json")

APP_TYPES = ("app", "game", "mod")
PER_PAGE = 12
MAX_PER_PAGE = 60

REQUIRED_FIELDS = (
    "slug", "name", "tagline", "type", "category", "developer", "version",
    "size", "android", "rating", "ratings", "downloads", "updated", "price",
    "description", "highlights", "store", "icon", "screenshots",
)

OPTIONAL_FIELDS = (
    "art", "motif", "palette", "permissions", "whatsNew", "released",
    "contentRating", "trending", "featured", "editorChoice", "hero",
    "iconFallback", "iconSource", "storeResolvedFrom", "storeName", "tags",
    "isMod", "isDemo",
    "modOf", "modFeatures", "modVariants", "modInstallSteps", "modFaq",
    "modDisclaimer", "packageId", "buildType", "download", "notes",
)

CACHE = {}


# --------------------------------------------------------------------- loading


def data_path(path=None):
    return path or os.environ.get("NOIR_DATA") or DEFAULT_DATA_FILE


def load(path=None):
    """Return the parsed catalogue, re-reading only when the file changes."""
    target = data_path(path)
    stamp = os.path.getmtime(target)
    cached = CACHE.get(target)
    if cached and cached[0] == stamp:
        return cached[1]
    with open(target, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("meta", {})
    data.setdefault("categories", [])
    data.setdefault("apps", [])
    CACHE[target] = (stamp, data)
    return data


def save(data, path=None):
    target = data_path(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    CACHE.pop(target, None)


def apps(path=None):
    return load(path)["apps"]


def categories(path=None):
    return load(path)["categories"]


def category_map(path=None):
    return {c["slug"]: c for c in categories(path)}


def find_app(slug, path=None):
    for app in apps(path):
        if app["slug"] == slug:
            return app
    return None


def is_mod(app):
    return bool(app.get("isMod")) or app.get("type") == "mod"


def mod_base(app):
    """Slug of the official app a mod is based on (if it is known)."""
    return app.get("modOf") or ""


# -------------------------------------------------------------------- filtering


def haystack(app, category_names=None):
    parts = [
        app.get("name", ""),
        app.get("developer", ""),
        app.get("category", ""),
        app.get("tagline", ""),
        app.get("description", ""),
        app.get("type", ""),
        " ".join(app.get("tags", []) or []),
        " ".join(app.get("highlights", []) or []),
    ]
    if category_names:
        parts.append(category_names.get(app.get("category", ""), ""))
    return " ".join(str(p) for p in parts).lower()


def matches_query(app, query, category_names=None):
    query = (query or "").strip().lower()
    if not query:
        return True
    text = haystack(app, category_names)
    return all(term in text for term in query.split())


def match_rank(app, query, category_names=None):
    """Score how well an entry matches a query.

    Exact and prefix name matches must come first - a search for "signal"
    should show Signal before an app that only mentions it in the copy.
    Returns -1 when the entry does not match at all.
    """
    query = (query or "").strip().lower()
    if not query:
        return 0
    name = (app.get("name") or "").lower()
    developer = (app.get("developer") or "").lower()
    tagline = (app.get("tagline") or "").lower()
    words = name.split()
    score = 0
    for term in query.split():
        if name == term:
            score += 100
        elif name.startswith(term):
            score += 60
        elif term in words:
            score += 40
        elif term in name:
            score += 20
        elif term in developer:
            score += 12
        elif term in tagline:
            score += 8
        elif term in haystack(app, category_names):
            score += 3
        else:
            return -1
    return score


def filter_apps(items, kind=None, category=None, query=None, mods=None, path=None):
    """Filter a list of entries by type, category, free text and mod state."""
    category_names = {c["slug"]: c["name"] for c in categories(path)} if path is not None else None
    out = []
    for app in items:
        if kind in ("app", "game") and app.get("type") != kind:
            continue
        if kind == "mod" and not is_mod(app):
            continue
        if category and app.get("category") != category:
            continue
        if mods is True and not is_mod(app):
            continue
        if mods is False and is_mod(app):
            continue
        if not matches_query(app, query, category_names):
            continue
        out.append(app)
    if query:
        out.sort(key=lambda a: -match_rank(a, query, category_names))
    return out


def size_in_mb(size):
    match = re.match(r"([\d.]+)\s*(KB|MB|GB)", str(size or ""))
    if not match:
        return 0.0
    value = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "GB":
        return value * 1024
    if unit == "KB":
        return value / 1024
    return value


def sort_apps(items, sort=None):
    key = sort or "popular"
    if key == "newest":
        return sorted(items, key=lambda a: a.get("updated", ""), reverse=True)
    if key == "rating":
        return sorted(items, key=lambda a: (a.get("rating", 0), a.get("ratings", 0)), reverse=True)
    if key == "name":
        return sorted(items, key=lambda a: a.get("name", "").lower())
    if key == "size":
        return sorted(items, key=lambda a: size_in_mb(a.get("size")), reverse=True)
    if key == "updated":
        return sorted(items, key=lambda a: a.get("updated", ""), reverse=True)
    return sorted(
        items,
        key=lambda a: (bool(a.get("trending")), a.get("rating", 0), a.get("ratings", 0)),
        reverse=True,
    )


def paginate(items, page=1, per_page=PER_PAGE):
    """Return (page_items, meta) for a 1-based page number."""
    per_page = max(1, min(int(per_page or PER_PAGE), MAX_PER_PAGE))
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(int(page or 1), pages))
    start = (page - 1) * per_page
    return items[start:start + per_page], {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "start": start + 1 if total else 0,
        "end": min(start + per_page, total),
        "has_prev": page > 1,
        "has_next": page < pages,
        "prev": page - 1 if page > 1 else None,
        "next": page + 1 if page < pages else None,
    }


def slim(app, category_names=None):
    """Compact payload used by the client side renderer and the JSON API."""
    return {
        "slug": app.get("slug"),
        "name": app.get("name"),
        "type": app.get("type"),
        "category": app.get("category"),
        "categoryName": (category_names or {}).get(app.get("category"), app.get("category", "")),
        "developer": app.get("developer"),
        "rating": app.get("rating"),
        "ratings": app.get("ratings"),
        "size": app.get("size"),
        "version": app.get("version"),
        "updated": app.get("updated"),
        "icon": app.get("icon"),
        "art": app.get("art"),
        "tagline": app.get("tagline"),
        "android": app.get("android"),
        "downloads": app.get("downloads"),
        "price": app.get("price"),
        "trending": bool(app.get("trending")),
        "isMod": is_mod(app),
        "isDemo": bool(app.get("isDemo")),
        "modOf": mod_base(app),
    }


# ------------------------------------------------------------------- validation


def slugify(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "entry"


def unique_slug(text, existing):
    base = slugify(text)
    slug = base
    counter = 2
    while slug in existing:
        slug = "%s-%d" % (base, counter)
        counter += 1
    return slug


def _is_url(value):
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def validate_entry(entry, data=None, slug_set=None):
    """Return a list of human readable problems for a single entry."""
    problems = []
    if not isinstance(entry, dict):
        return ["entry is not an object"]

    for field in REQUIRED_FIELDS:
        if field not in entry or entry[field] in (None, "", []):
            problems.append("missing required field '%s'" % field)

    slug = entry.get("slug", "")
    if slug and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(slug)):
        problems.append("slug '%s' must be lowercase kebab-case" % slug)
    if slug_set is not None and slug in slug_set:
        problems.append("duplicate slug '%s'" % slug)

    kind = entry.get("type")
    if kind and kind not in APP_TYPES:
        problems.append("type '%s' must be one of %s" % (kind, ", ".join(APP_TYPES)))

    if data is not None:
        known = {c["slug"] for c in data.get("categories", [])}
        if entry.get("category") and known and entry["category"] not in known:
            problems.append("unknown category '%s'" % entry["category"])

    rating = entry.get("rating")
    if isinstance(rating, (int, float)) and not (0 <= rating <= 5):
        problems.append("rating %s is outside 0-5" % rating)

    updated = entry.get("updated")
    if updated and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(updated)):
        problems.append("updated must be YYYY-MM-DD")

    store = entry.get("store")
    if store and not _is_url(store):
        problems.append("store must be an absolute http(s) URL")
    if store and "play.google.com" not in store and "f-droid.org" not in store:
        problems.append("store must point at an official store (Google Play or F-Droid)")

    if entry.get("isMod") or kind == "mod":
        if not entry.get("modFeatures"):
            problems.append("mod entries need at least one modFeatures item")
        if not entry.get("modInstallSteps"):
            problems.append("mod entries need modInstallSteps")
        if not entry.get("modDisclaimer"):
            problems.append("mod entries need a modDisclaimer")
        download = entry.get("download") or {}
        url = download.get("url")
        if url and not _is_url(url):
            problems.append("download.url must be an absolute http(s) URL")
        if not url and not download.get("unavailableReason"):
            problems.append("mod entries without a download need download.unavailableReason")
        base = entry.get("modOf")
        if base and data is not None:
            if not any(a.get("slug") == base for a in data.get("apps", [])):
                problems.append("modOf points at unknown app '%s'" % base)

    for field, value in entry.items():
        if field in OPTIONAL_FIELDS or field in REQUIRED_FIELDS:
            continue
        problems.append("unknown field '%s'" % field)

    return problems


def validate(data=None, path=None):
    """Validate the whole catalogue; returns a list of (slug, problems)."""
    data = data or load(path)
    issues = []
    seen = set()
    for entry in data.get("apps", []):
        slug = entry.get("slug", "?") if isinstance(entry, dict) else "?"
        slug_set = set()
        problems = validate_entry(entry, data, slug_set)
        if slug in seen:
            problems.append("duplicate slug '%s'" % slug)
        seen.add(slug)
        if problems:
            issues.append((slug, problems))
    return issues


# ------------------------------------------------------------------- templates


def blank_entry(slug, name, kind="app", category="utilities"):
    """A starter entry for the publishing CLI."""
    return {
        "slug": slug,
        "name": name,
        "tagline": "One line that sells the app",
        "type": kind,
        "category": category,
        "developer": "Developer name",
        "version": "1.0.0",
        "size": "10 MB",
        "android": "Android 8.0+",
        "rating": 4.0,
        "ratings": 0,
        "downloads": "1K+",
        "updated": "2026-01-01",
        "released": "2026-01-01",
        "price": "Free",
        "contentRating": "Everyone",
        "motif": "cube",
        "palette": ["#12141c", "#c8f542"],
        "icon": "/static/img/icons/%s.svg" % slug,
        "iconFallback": "/static/img/icons/%s.svg" % slug,
        "art": "/static/img/art/%s.svg" % slug,
        "screenshots": [
            "/static/img/shots/%s-1.svg" % slug,
            "/static/img/shots/%s-2.svg" % slug,
            "/static/img/shots/%s-3.svg" % slug,
            "/static/img/shots/%s-4.svg" % slug,
        ],
        "description": "Describe what the app does, who it is for and what stands out.",
        "highlights": [
            "First thing the reader should know",
            "Second thing the reader should know",
        ],
        "whatsNew": "What changed in this release.",
        "permissions": ["Internet", "Storage"],
        "store": "https://play.google.com/store/apps/details?id=",
        "storeName": "Google Play",
        "trending": False,
        "featured": False,
        "editorChoice": False,
    }
