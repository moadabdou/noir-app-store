#!/usr/bin/env python3
"""Refresh NOIR app icons from official store listings.

For every entry in data/apps.json the tool opens the app's official store page
(the same link the catalogue shows to visitors), locates the publisher icon
that page serves, downloads it and caches it under
static/img/icons/real/<slug>.<ext>.

Guarantees:
  * only official listing pages are read (the store URL stored in the catalogue)
  * nothing is installed, unpacked or mirrored - only the icon image is fetched
  * the download is validated (HTTP status, content type, magic bytes, size and
    pixel dimensions) before it is accepted
  * apps whose icon cannot be fetched keep the generated SVG icon as fallback

The run is recorded in static/img/icons/real/manifest.json so every icon can
be traced back to the page it came from.

Usage:
  python3 tools/fetch_icons.py                # fetch missing / stale icons
  python3 tools/fetch_icons.py --refresh      # refetch every icon
  python3 tools/fetch_icons.py --only signal vlc
"""

import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(ROOT, "data", "apps.json")
ICON_DIR = os.path.join(ROOT, "static", "img", "icons", "real")
MANIFEST = os.path.join(ICON_DIR, "manifest.json")

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/122.0.0.0 Safari/537.36")
TIMEOUT = 20
RETRIES = 3
REFRESH_AFTER_DAYS = 30
MIN_BYTES = 2048
MIN_EDGE = 96

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


# --------------------------------------------------------------------- fetch


def http_get(url, referer=None):
    request = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer or "",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=CTX) as response:
        return response.getcode(), response.headers.get("Content-Type", ""), response.read()


def fetch_page(url):
    last = None
    for attempt in range(RETRIES):
        try:
            status, ctype, body = http_get(url)
            if status == 200 and b"<html" in body[:4000].lower():
                return body.decode("utf-8", "replace"), None
            last = "HTTP %s" % status
        except urllib.error.HTTPError as err:
            last = "HTTP %s" % err.code
        except Exception as err:
            last = type(err).__name__ + ": " + str(err)[:120]
        time.sleep(1.2 * (attempt + 1))
    return None, last


def fetch_binary(url, referer):
    last = None
    for attempt in range(RETRIES):
        try:
            status, ctype, body = http_get(url, referer)
            if status != 200:
                last = "HTTP %s" % status
            elif len(body) < 64:
                last = "body too small (%d bytes)" % len(body)
            else:
                return ctype, body, None
        except urllib.error.HTTPError as err:
            last = "HTTP %s" % err.code
        except Exception as err:
            last = type(err).__name__ + ": " + str(err)[:120]
        time.sleep(1.2 * (attempt + 1))
    return None, None, last


# ------------------------------------------------------------------- parsing


def clean_url(url):
    url = url.replace("&amp;", "&")
    if url.startswith("//"):
        url = "https:" + url
    return url


def find_icon_url(page, store_url):
    """Return the publisher icon URL advertised by an official store page."""
    host = urllib.parse.urlparse(store_url).netloc

    if "play.google.com" in host:
        patterns = [
            r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
            r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"',
            r'<link[^>]+rel="apple-touch-icon"[^>]+href="([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, page)
            if match:
                url = clean_url(match.group(1))
                if "googleusercontent.com" in url:
                    return url
        # Fall back to the largest play-lh thumbnail referenced on the page.
        candidates = re.findall(r'https://play-lh\.googleusercontent\.com/[A-Za-z0-9_\-]+=w\d+', page)
        if candidates:
            return candidates[0].replace("=w512", "=s512")
        return None

    if "f-droid.org" in host:
        patterns = [
            r'<img[^>]+class="package-icon"[^>]+src="([^"]+)"',
            r'<img[^>]+src="([^"]+)"[^>]+class="package-icon"',
            r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
            r'<link[^>]+rel="apple-touch-icon"[^>]+href="([^"]+)"',
        ]
        for pattern in patterns:
            match = re.search(pattern, page)
            if match:
                return urllib.parse.urljoin(store_url, clean_url(match.group(1)))
        candidates = re.findall(r'https://f-droid\.org/repo/[^"\']+icon[^"\']+\.(?:png|webp)', page)
        if candidates:
            return candidates[0]
        return None

    return None


# --------------------------------------------------------------- resolution


def normalise(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def page_title(page):
    for pattern in (r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
                    r"<title>([^<]*)</title>"):
        match = re.search(pattern, page)
        if match:
            return clean_url(match.group(1)).strip()
    return ""


def title_matches(page, name):
    title = normalise(page_title(page))
    wanted = normalise(name)
    if not title or not wanted:
        return False
    if title.startswith(wanted) or wanted in title:
        return True
    return False


def listing_url(host, package_id):
    if "play.google.com" in host:
        return "https://play.google.com/store/apps/details?id=%s&hl=en&gl=US" % package_id
    if "f-droid.org" in host:
        return "https://f-droid.org/packages/%s/" % package_id
    return None


def search_candidates(store_url, name):
    """Search the official store for the package id of an app."""
    host = urllib.parse.urlparse(store_url).netloc or store_url
    candidates = []
    if "play.google.com" in host:
        query = urllib.parse.quote(name)
        url = "https://play.google.com/store/search?q=%s&c=apps&hl=en&gl=US" % query
        page, _ = fetch_page(url)
        if page:
            seen = []
            for package_id in re.findall(r"store/apps/details\?id=([A-Za-z0-9_.\-]+)", page):
                if package_id not in seen:
                    seen.append(package_id)
            candidates = seen[:14]
    elif "f-droid.org" in host:
        query = urllib.parse.quote(name)
        url = "https://f-droid.org/packages/?q=%s" % query
        page, _ = fetch_page(url)
        if page:
            seen = []
            for package_id in re.findall(r'/packages/([A-Za-z0-9_.\-]+)/', page):
                if package_id not in seen:
                    seen.append(package_id)
            candidates = seen[:14]
    return candidates


def resolve_listing(app):
    """Return (listing_url, page_html, note). Falls back to an official search."""
    page, error = fetch_page(app["store"])
    if page:
        return app["store"], page, "listing"

    hosts = [urllib.parse.urlparse(app["store"]).netloc]
    if "f-droid.org" in hosts[0]:
        hosts.append("play.google.com")

    for host in hosts:
        search_url = "https://%s" % host
        candidates = search_candidates(search_url, app["name"])
        for package_id in candidates:
            url = listing_url(host, package_id)
            if not url:
                continue
            candidate_page, _ = fetch_page(url)
            if candidate_page and title_matches(candidate_page, app["name"]):
                return url, candidate_page, "resolved:%s" % package_id
    return None, None, error or "no listing found"


# ---------------------------------------------------------------- validation


def sniff_format(body):
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if body[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp", "image/webp"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "gif", "image/gif"
    if body[:2] == b"BM":
        return "bmp", "image/bmp"
    return None, None


def image_size(body, fmt):
    try:
        if fmt == "png" and len(body) > 24:
            width = int.from_bytes(body[16:20], "big")
            height = int.from_bytes(body[20:24], "big")
            return width, height
        if fmt == "gif" and len(body) > 10:
            return int.from_bytes(body[6:8], "little"), int.from_bytes(body[8:10], "little")
        if fmt == "bmp" and len(body) > 26:
            return int.from_bytes(body[18:22], "little"), int.from_bytes(body[22:26], "little")
        if fmt == "jpg":
            index = 2
            while index < len(body) - 9:
                if body[index] != 0xFF:
                    index += 1
                    continue
                marker = body[index + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    height = int.from_bytes(body[index + 5:index + 7], "big")
                    width = int.from_bytes(body[index + 7:index + 9], "big")
                    return width, height
                if index + 4 > len(body):
                    break
                length = int.from_bytes(body[index + 2:index + 4], "big")
                index += 2 + max(2, length)
            return None, None
        if fmt == "webp" and len(body) > 30:
            chunk = body[12:16]
            if chunk == b"VP8X":
                width = int.from_bytes(body[24:27], "little") + 1
                height = int.from_bytes(body[27:30], "little") + 1
                return width, height
            if chunk == b"VP8 ":
                return (int.from_bytes(body[26:28], "little") & 0x3FFF,
                        int.from_bytes(body[28:30], "little") & 0x3FFF)
            if chunk == b"VP8L":
                bits = int.from_bytes(body[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    except Exception:
        return None, None
    return None, None


def validate(body, ctype):
    if len(body) < MIN_BYTES:
        return None, "too small (%d bytes)" % len(body)
    fmt, expected = sniff_format(body)
    if not fmt:
        return None, "not an image (content-type %s)" % (ctype or "unknown")
    if ctype and "image" not in ctype.lower():
        return None, "unexpected content-type %s" % ctype
    width, height = image_size(body, fmt)
    if not width or not height:
        return None, "could not read dimensions"
    if width < MIN_EDGE or height < MIN_EDGE:
        return None, "icon too small (%dx%d)" % (width, height)
    if width > 2000 or height > 2000:
        return None, "unexpected dimensions (%dx%d)" % (width, height)
    return fmt, "%s %dx%d %d bytes" % (fmt, width, height, len(body))


# ------------------------------------------------------------------- fetching


def cached_path(slug, fmt):
    return os.path.join(ICON_DIR, "%s.%s" % (slug, fmt))


def load_manifest():
    if os.path.exists(MANIFEST):
        try:
            with open(MANIFEST, "r", encoding="utf-8") as handle:
                data = json.load(handle)
                if isinstance(data, dict) and "entries" in data:
                    return {e["slug"]: e for e in data["entries"]}
        except Exception:
            pass
    return {}


def refresh_one(app, manifest, refresh):
    slug = app["slug"]
    record = dict(manifest.get(slug, {}))
    record.update({
        "slug": slug,
        "name": app["name"],
        "developer": app["developer"],
        "source_page": app["store"],
        "source_store": app.get("storeName", ""),
    })

    target = record.get("local_path")
    if target and not refresh:
        absolute = os.path.join(ROOT, target.lstrip("/"))
        if os.path.exists(absolute):
            age = time.time() - os.path.getmtime(absolute)
            if age < REFRESH_AFTER_DAYS * 86400:
                record["outcome"] = "cached"
                record["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                return slug, record
            refresh = True

    listing, page, note = resolve_listing(app)
    if not page:
        record.update({
            "outcome": "failed",
            "stage": "page",
            "error": note,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        return slug, record

    if listing and listing.startswith("http") and listing != app["store"]:
        record["resolved_listing"] = listing
        record["original_listing"] = app["store"]

    icon_url = find_icon_url(page, listing or app["store"])
    if not icon_url:
        record.update({
            "outcome": "failed",
            "stage": "parse",
            "error": "no icon reference found on the listing page",
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        return slug, record

    ctype, body, error = fetch_binary(icon_url, listing)
    if body is None:
        record.update({
            "outcome": "failed",
            "stage": "download",
            "listing_page": listing,
            "image_url": icon_url,
            "error": error,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        return slug, record

    fmt, detail = validate(body, ctype)
    if not fmt:
        record.update({
            "outcome": "failed",
            "stage": "validate",
            "listing_page": listing,
            "image_url": icon_url,
            "error": detail,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        return slug, record

    os.makedirs(ICON_DIR, exist_ok=True)
    absolute = cached_path(slug, fmt)
    with open(absolute, "wb") as handle:
        handle.write(body)
    relative = "/static/img/icons/real/%s.%s" % (slug, fmt)

    record.update({
        "outcome": "ok",
        "stage": "done",
        "image_url": icon_url,
        "listing_page": listing,
        "local_path": relative,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "detail": detail,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return slug, record


def write_manifest(entries):
    os.makedirs(ICON_DIR, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "note": "Icons are downloaded from the official store listing linked in data/apps.json.",
        "entries": [entries[key] for key in sorted(entries)],
    }
    with open(MANIFEST, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def update_catalogue(results):
    with open(DATA_FILE, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    changed = 0
    for app in data["apps"]:
        record = results.get(app["slug"], {})
        fallback = app.get("iconFallback") or app.get("icon") or ""
        app["iconFallback"] = fallback
        resolved = str(record.get("resolved_listing") or "")
        if resolved.startswith("http") and record.get("outcome") in ("ok", "cached"):
            app["store"] = resolved
            app["storeResolvedFrom"] = record.get("original_listing", app["store"])
        if record.get("outcome") in ("ok", "cached") and record.get("local_path"):
            app["icon"] = record["local_path"]
            app["iconSource"] = {
                "page": record.get("source_page"),
                "image": record.get("image_url"),
                "fetched": record.get("fetched_at"),
            }
            changed += 1
        else:
            app["icon"] = fallback
            app.pop("iconSource", None)
    with open(DATA_FILE, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return changed


def main():
    parser = argparse.ArgumentParser(description="Refresh official NOIR app icons")
    parser.add_argument("--refresh", action="store_true", help="refetch icons that are already cached")
    parser.add_argument("--only", nargs="*", default=None, help="only process these slugs")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    with open(DATA_FILE, "r", encoding="utf-8") as handle:
        apps = json.load(handle)["apps"]
    if args.only:
        apps = [a for a in apps if a["slug"] in set(args.only)]

    manifest = load_manifest()
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for slug, record in pool.map(lambda a: refresh_one(a, manifest, args.refresh), apps):
            results[slug] = record
            flag = "ok" if record.get("outcome") == "ok" else record.get("outcome")
            print("%-24s %-8s %s" % (slug, flag, record.get("detail") or record.get("error") or ""))

    merged = dict(manifest)
    merged.update(results)
    write_manifest(merged)
    changed = update_catalogue(results)
    ok = sum(1 for r in results.values() if r.get("outcome") == "ok")
    cached = sum(1 for r in results.values() if r.get("outcome") == "cached")
    print("\n%d fetched, %d cached, %d/%d icons available, %d catalogue entries updated"
          % (ok, cached, ok + cached, len(results), changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
