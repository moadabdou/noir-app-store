#!/usr/bin/env python3
"""Generate original SVG artwork for the NOIR catalogue.

Reads data/apps.json and writes:
  static/img/icons/<slug>.svg    app icon (128x128)
  static/img/art/<slug>.svg      featured artwork (1200x800)
  static/img/shots/<slug>-N.svg  app screenshots (540x1080)

All artwork is original abstract geometry derived from the entry palette and
motif name. No third-party logos or trademarked imagery are used.
"""

import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "apps.json")
OUT = os.path.join(ROOT, "static", "img")


def hex_to_rgb(value):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    return "#%02x%02x%02x" % (
        int(ra + (rb - ra) * t),
        int(ga + (gb - ga) * t),
        int(ba + (bb - ba) * t),
    )


def shade(color, amount):
    r, g, b = hex_to_rgb(color)
    if amount > 0:
        r = int(r + (255 - r) * amount)
        g = int(g + (255 - g) * amount)
        b = int(b + (255 - b) * amount)
    else:
        r = int(r * (1 + amount))
        g = int(g * (1 + amount))
        b = int(b * (1 + amount))
    return "#%02x%02x%02x" % (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


MOTIFS = {
    "shield": '<path d="M32 7 L52 15 V31 C52 44 43 55 32 59 C21 55 12 44 12 31 V15 Z" fill="url(#fg)"/><path d="M23 32 L29.5 39 L42 25" fill="none" stroke="#0b0b0d" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>',
    "paperplane": '<path d="M32 8 L55 54 L32 42 L9 54 Z" fill="url(#fg)"/><path d="M32 42 L32 8" stroke="#0b0b0d" stroke-width="2.5" opacity=".55"/><path d="M32 42 L55 54" stroke="#0b0b0d" stroke-width="2.5" opacity=".55"/>',
    "phone": '<rect x="19" y="8" width="26" height="48" rx="6" fill="url(#fg)"/><rect x="24" y="14" width="16" height="32" rx="2" fill="#0b0b0d" opacity=".35"/><circle cx="32" cy="51" r="2.4" fill="#0b0b0d" opacity=".5"/>',
    "lion": '<g fill="url(#fg)"><circle cx="32" cy="32" r="11"/><circle cx="32" cy="15" r="6"/><circle cx="32" cy="49" r="6"/><circle cx="15" cy="32" r="6"/><circle cx="49" cy="32" r="6"/><circle cx="20" cy="20" r="5"/><circle cx="44" cy="20" r="5"/><circle cx="20" cy="44" r="5"/><circle cx="44" cy="44" r="5"/></g><circle cx="32" cy="32" r="5" fill="#0b0b0d" opacity=".45"/>',
    "globe": '<circle cx="32" cy="32" r="23" fill="none" stroke="url(#fg)" stroke-width="4"/><ellipse cx="32" cy="32" rx="10" ry="23" fill="none" stroke="url(#fg)" stroke-width="3" opacity=".7"/><path d="M10 24 H54 M10 40 H54" stroke="url(#fg)" stroke-width="3" opacity=".7" stroke-linecap="round"/>',
    "duck": '<ellipse cx="30" cy="38" rx="18" ry="13" fill="url(#fg)"/><circle cx="44" cy="23" r="10" fill="url(#fg)"/><path d="M52 22 L60 25 L52 29 Z" fill="url(#fg)"/><circle cx="46" cy="21" r="2" fill="#0b0b0d" opacity=".6"/>',
    "cone": '<path d="M32 10 L49 46 H15 Z" fill="url(#fg)"/><rect x="11" y="46" width="42" height="8" rx="3" fill="url(#fg)" opacity=".75"/><path d="M22 40 H42" stroke="#0b0b0d" stroke-width="2" opacity=".35"/>',
    "play": '<path d="M22 13 L52 32 L22 51 Z" fill="url(#fg)"/>',
    "wave": '<g fill="none" stroke="url(#fg)" stroke-width="5" stroke-linecap="round"><path d="M10 24 Q22 14 32 24 T54 24"/><path d="M10 36 Q22 26 32 36 T54 36"/><path d="M10 48 Q22 38 32 48 T54 48"/></g>',
    "server": '<g fill="url(#fg)"><rect x="12" y="14" width="40" height="11" rx="3"/><rect x="12" y="28" width="40" height="11" rx="3"/><rect x="12" y="42" width="40" height="11" rx="3"/></g><g fill="#0b0b0d" opacity=".5"><circle cx="19" cy="19.5" r="2.4"/><circle cx="19" cy="33.5" r="2.4"/><circle cx="19" cy="47.5" r="2.4"/></g>',
    "box": '<path d="M32 8 L54 20 V44 L32 56 L10 44 V20 Z" fill="url(#fg)"/><path d="M32 32 L54 20 M32 32 V56 M32 32 L10 20" stroke="#0b0b0d" stroke-width="2.5" opacity=".45" fill="none"/>',
    "folder": '<path d="M10 20 Q10 14 16 14 H28 L34 21 H48 Q54 21 54 27 V46 Q54 52 48 52 H16 Q10 52 10 46 Z" fill="url(#fg)"/><path d="M10 28 H54" stroke="#0b0b0d" stroke-width="2.5" opacity=".35"/>',
    "bolt": '<path d="M36 6 L16 36 H29 L25 58 L48 26 H34 Z" fill="url(#fg)"/>',
    "terminal": '<rect x="9" y="13" width="46" height="38" rx="5" fill="url(#fg)"/><path d="M18 26 L25 32 L18 38" fill="none" stroke="#0b0b0d" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/><path d="M30 40 H42" stroke="#0b0b0d" stroke-width="3.4" stroke-linecap="round" opacity=".7"/>',
    "brush": '<rect x="29" y="7" width="6" height="22" rx="3" fill="url(#fg)"/><rect x="25" y="27" width="14" height="8" rx="2" fill="url(#fg)"/><path d="M27 35 Q32 52 32 58 Q20 54 22 44 Z" fill="url(#fg)"/>',
    "note": '<path d="M14 8 H40 L50 18 V56 H14 Z" fill="url(#fg)"/><path d="M40 8 V18 H50" fill="#0b0b0d" opacity=".28"/><g stroke="#0b0b0d" stroke-width="3" opacity=".45" stroke-linecap="round"><path d="M22 30 H42"/><path d="M22 38 H42"/><path d="M22 46 H34"/></g>',
    "key": '<circle cx="20" cy="24" r="11" fill="none" stroke="url(#fg)" stroke-width="5"/><path d="M27 31 L50 54" stroke="url(#fg)" stroke-width="5" stroke-linecap="round"/><path d="M42 46 L36 40 M48 52 L42 46" stroke="url(#fg)" stroke-width="5" stroke-linecap="round"/>',
    "vault": '<circle cx="32" cy="32" r="24" fill="none" stroke="url(#fg)" stroke-width="4.5"/><circle cx="32" cy="32" r="9" fill="none" stroke="url(#fg)" stroke-width="4"/><g stroke="url(#fg)" stroke-width="4" stroke-linecap="round"><path d="M32 8 V18 M32 46 V56 M8 32 H18 M46 32 H56"/></g>',
    "map": '<path d="M8 16 L24 10 L40 16 L56 10 V48 L40 54 L24 48 L8 54 Z" fill="url(#fg)"/><path d="M24 10 V48 M40 16 V54" stroke="#0b0b0d" stroke-width="2.5" opacity=".4"/><circle cx="32" cy="32" r="6" fill="#0b0b0d" opacity=".55"/>',
    "mic": '<rect x="22" y="7" width="20" height="32" rx="10" fill="url(#fg)"/><path d="M13 30 A19 19 0 0 0 51 30" fill="none" stroke="url(#fg)" stroke-width="4.5" stroke-linecap="round"/><path d="M32 49 V58 M22 58 H42" stroke="url(#fg)" stroke-width="4.5" stroke-linecap="round"/>',
    "train": '<rect x="14" y="8" width="36" height="38" rx="9" fill="url(#fg)"/><rect x="20" y="15" width="24" height="15" rx="4" fill="#0b0b0d" opacity=".42"/><circle cx="23" cy="46" r="5" fill="url(#fg)"/><circle cx="41" cy="46" r="5" fill="url(#fg)"/><path d="M10 56 H54" stroke="url(#fg)" stroke-width="4" stroke-linecap="round" opacity=".7"/>',
    "crew": '<ellipse cx="32" cy="38" rx="16" ry="18" fill="url(#fg)"/><rect x="12" y="26" width="12" height="20" rx="5" fill="url(#fg)"/><rect x="24" y="22" width="22" height="12" rx="6" fill="#0b0b0d" opacity=".45"/><rect x="27" y="25" width="16" height="6" rx="3" fill="url(#fg)" opacity=".9"/><path d="M32 20 V9" stroke="url(#fg)" stroke-width="5" stroke-linecap="round"/>',
    "tower": '<g fill="url(#fg)"><rect x="12" y="42" width="16" height="16" rx="2"/><rect x="30" y="30" width="16" height="28" rx="2"/><rect x="48" y="18" width="10" height="40" rx="2"/></g><path d="M12 34 L38 14 L58 26" fill="none" stroke="url(#fg)" stroke-width="3" stroke-linecap="round" opacity=".55"/>',
    "shadow": '<circle cx="26" cy="18" r="11" fill="url(#fg)"/><path d="M14 56 Q16 32 30 32 Q44 32 46 56 Z" fill="url(#fg)"/><path d="M34 56 L56 56" stroke="url(#fg)" stroke-width="4" stroke-linecap="round" opacity=".5"/>',
    "sword": '<path d="M32 6 L41 22 V42 H23 V22 Z" fill="url(#fg)"/><rect x="12" y="42" width="40" height="6" rx="3" fill="url(#fg)"/><rect x="28" y="48" width="8" height="11" rx="3" fill="url(#fg)"/>',
    "cube": '<path d="M32 8 L56 21 L32 34 L8 21 Z" fill="url(#fg)"/><path d="M8 21 L32 34 V58 L8 45 Z" fill="url(#fg)" opacity=".72"/><path d="M56 21 L32 34 V58 L56 45 Z" fill="url(#fg)" opacity=".48"/>',
    "bird": '<circle cx="30" cy="34" r="17" fill="url(#fg)"/><path d="M45 30 L58 34 L45 40 Z" fill="url(#fg)"/><path d="M15 28 L4 20 L8 34 Z" fill="url(#fg)" opacity=".8"/><circle cx="36" cy="28" r="2.6" fill="#0b0b0d" opacity=".6"/><path d="M24 48 L18 58 L30 54" fill="url(#fg)"/>',
    "car": '<path d="M10 44 V36 L20 22 H44 L54 36 V44 H10 Z" fill="url(#fg)"/><rect x="22" y="25" width="20" height="11" rx="2" fill="#0b0b0d" opacity=".42"/><circle cx="21" cy="47" r="7" fill="url(#fg)"/><circle cx="43" cy="47" r="7" fill="url(#fg)"/><circle cx="21" cy="47" r="3" fill="#0b0b0d" opacity=".5"/><circle cx="43" cy="47" r="3" fill="#0b0b0d" opacity=".5"/>',
    "target": '<circle cx="32" cy="32" r="23" fill="none" stroke="url(#fg)" stroke-width="4"/><circle cx="32" cy="32" r="14" fill="none" stroke="url(#fg)" stroke-width="4" opacity=".75"/><circle cx="32" cy="32" r="5" fill="url(#fg)"/><path d="M44 20 L56 8 M50 8 H56 V14" stroke="url(#fg)" stroke-width="4" fill="none" stroke-linecap="round"/>',
    "leaf": '<path d="M12 52 Q12 14 52 10 Q54 48 12 52 Z" fill="url(#fg)"/><path d="M12 52 Q28 40 50 16" stroke="#0b0b0d" stroke-width="3" fill="none" opacity=".45"/>',
}


def icon_svg(app):
    c1, c2 = app["palette"]
    uid = app["slug"].replace("-", "")
    motif = MOTIFS.get(app.get("motif", "cube"), MOTIFS["cube"])
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="128" height="128" role="img" aria-label="{app['name']} icon">
<defs>
<linearGradient id="bg{uid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{shade(c2, 0.1)}"/><stop offset="1" stop-color="{c1}"/></linearGradient>
<linearGradient id="fg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff"/><stop offset="1" stop-color="{shade(c2, 0.72)}"/></linearGradient>
<radialGradient id="gl{uid}" cx="0.3" cy="0.2" r="0.9"><stop offset="0" stop-color="{shade(c2, 0.55)}" stop-opacity=".85"/><stop offset="1" stop-color="#000" stop-opacity="0"/></radialGradient>
</defs>
<rect width="64" height="64" rx="15" fill="url(#bg{uid})"/>
<rect width="64" height="64" rx="15" fill="url(#gl{uid})"/>
<g transform="translate(0,0)">{motif}</g>
</svg>
"""


def art_svg(app, index):
    c1, c2 = app["palette"]
    uid = app["slug"].replace("-", "")
    motif = MOTIFS.get(app.get("motif", "cube"), MOTIFS["cube"])
    rnd = random_for(app["slug"])
    blobs = []
    for i in range(7):
        angle = rnd[i] * math.tau
        radius = 120 + rnd[i + 7] * 340
        cx = 600 + math.cos(angle) * radius
        cy = 400 + math.sin(angle) * radius * 0.66
        r = 130 + rnd[i + 14] * 250
        col = c2 if i % 2 == 0 else shade(c1, 0.25)
        blobs.append(
            f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="{col}" opacity="{0.14 + rnd[i + 21] * 0.2:.2f}"/>'
        )
    grid = []
    for x in range(0, 1201, 60):
        grid.append(f'<line x1="{x}" y1="0" x2="{x}" y2="800"/>')
    for y in range(0, 801, 60):
        grid.append(f'<line x1="0" y1="{y}" x2="1200" y2="{y}"/>')
    rings = "".join(
        f'<circle cx="930" cy="180" r="{90 + i * 70}" fill="none" stroke="{shade(c2, 0.35)}" stroke-width="1.4" opacity="{0.3 - i * 0.05:.2f}"/>'
        for i in range(4)
    )
    tiles = []
    for i in range(26):
        tx = 40 + (i % 7) * 62
        ty = 520 + (i // 7) * 64
        tiles.append(
            f'<rect x="{tx}" y="{ty}" width="46" height="46" rx="10" fill="none" stroke="{shade(c2, 0.4)}" stroke-width="1.2" opacity=".28"/>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" width="1200" height="800" role="img" aria-label="{app['name']} artwork">
<defs>
<radialGradient id="a{uid}" cx="0.72" cy="0.28" r="0.85"><stop offset="0" stop-color="{shade(c1, 0.18)}"/><stop offset="1" stop-color="#050506"/></radialGradient>
<linearGradient id="m{uid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity=".95"/><stop offset="1" stop-color="{shade(c2, 0.6)}" stop-opacity=".9"/></linearGradient>
<linearGradient id="fade{uid}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000000" stop-opacity=".92"/><stop offset=".55" stop-color="#000000" stop-opacity=".35"/><stop offset="1" stop-color="#000000" stop-opacity="0"/></linearGradient>
</defs>
<rect width="1200" height="800" fill="url(#a{uid})"/>
<g>{''.join(blobs)}</g>
<g stroke="#ffffff" stroke-width="1" opacity=".05">{''.join(grid)}</g>
{''.join(tiles)}
<g transform="translate(830,240) scale(4.2)" opacity=".9">
<g transform="translate(-32,-32)">{motif}</g>
</g>
<rect x="0" y="0" width="640" height="800" fill="url(#fade{uid})"/>
</svg>
"""


def random_for(seed):
    values = []
    h = 2166136261
    for ch in seed:
        h = ((h ^ ord(ch)) * 16777619) & 0xFFFFFFFF
    for _ in range(40):
        h = (h * 1103515245 + 12345) & 0x7FFFFFFF
        values.append(h / 0x7FFFFFFF)
    return values


def shot_svg(app, n):
    c1, c2 = app["palette"]
    uid = "%s%d" % (app["slug"].replace("-", ""), n)
    accent = shade(c2, 0.45)
    head = f"""<rect width="540" height="1080" fill="#08080a"/>
<rect x="0" y="0" width="540" height="1080" fill="url(#g{uid})" opacity=".9"/>
<g opacity=".35">{''.join(f'<circle cx="{40 + (i * 97) % 500}" cy="{120 + (i * 211) % 900}" r="{90 + (i * 37) % 130}" fill="{c2}"/>' for i in range(5))}</g>
<rect x="0" y="0" width="540" height="60" fill="#000" opacity=".35"/>
<g fill="#ffffff" opacity=".85"><rect x="28" y="26" width="46" height="8" rx="4"/><rect x="432" y="24" width="80" height="11" rx="5" opacity=".6"/></g>"""
    title = f"""<g>
<text x="28" y="122" font-family="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif" font-size="30" font-weight="700" fill="#ffffff">{app['name']}</text>
<text x="28" y="152" font-family="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif" font-size="16" fill="#ffffff" opacity=".6">{app['tagline']}</text>
<rect x="28" y="172" width="120" height="34" rx="17" fill="{accent}" opacity=".18"/>
<text x="88" y="194" text-anchor="middle" font-family="system-ui, sans-serif" font-size="14" font-weight="600" fill="{accent}">{app['category'].title()}</text>
</g>"""

    def card(x, y, w, h, radius=18, op=1.0):
        return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="#111114" opacity="{op}" '
                f'stroke="#ffffff" stroke-opacity=".09" stroke-width="1"/>')

    def row(y, i):
        c = accent if i % 3 == 0 else shade(c2, 0.1)
        return f"""{card(24, y, 492, 92)}
<rect x="44" y="{y + 20}" width="52" height="52" rx="16" fill="{c}" opacity=".85"/>
<rect x="116" y="{y + 26}" width="{190 - i * 12}" height="12" rx="6" fill="#ffffff" opacity=".78"/>
<rect x="116" y="{y + 50}" width="{120 - i * 6}" height="10" rx="5" fill="#ffffff" opacity=".32"/>
<rect x="440" y="{y + 34}" width="56" height="24" rx="12" fill="{c}" opacity=".25"/>"""

    body = ""
    if n == 1:
        body = "".join(row(210 + i * 104, i) for i in range(6))
        body += card(24, 210 + 6 * 104, 492, 150) + f'<rect x="44" y="{210 + 6 * 104 + 30}" width="220" height="14" rx="7" fill="#ffffff" opacity=".6"/>'
    elif n == 2:
        for r in range(3):
            for c in range(2):
                x = 24 + c * 250
                y = 210 + r * 232
                body += card(x, y, 226, 208)
                body += (f'<rect x="{x + 20}" y="{y + 20}" width="186" height="110" rx="16" fill="{accent}" opacity=".32"/>'
                         f'<rect x="{x + 20}" y="{y + 146}" width="{150 - r * 20}" height="12" rx="6" fill="#ffffff" opacity=".7"/>'
                         f'<rect x="{x + 20}" y="{y + 170}" width="90" height="10" rx="5" fill="#ffffff" opacity=".3"/>')
    elif n == 3:
        body += card(24, 210, 492, 420, 26)
        body += f'<rect x="44" y="230" width="452" height="250" rx="18" fill="{accent}" opacity=".3"/>'
        body += f'<path d="M44 400 L160 320 L250 372 L340 300 L496 396 V480 H44 Z" fill="{shade(c2, 0.2)}" opacity=".45"/>'
        body += f'<circle cx="270" cy="355" r="42" fill="#0b0b0d" opacity=".55"/><path d="M258 336 L296 355 L258 374 Z" fill="#ffffff" opacity=".85"/>'
        body += f'<rect x="44" y="504" width="160" height="14" rx="7" fill="#ffffff" opacity=".5"/>'
        body += f'<rect x="44" y="536" width="110" height="11" rx="6" fill="#ffffff" opacity=".28"/>'
        body += "".join(row(660 + i * 104, i) for i in range(3))
    else:
        body += card(24, 210, 492, 300, 24)
        body += f'<rect x="44" y="230" width="452" height="120" rx="18" fill="{accent}" opacity=".28"/>'
        body += f'<g stroke="{accent}" stroke-width="6" fill="none" stroke-linecap="round" opacity=".9">'
        body += f'<path d="M60 330 Q130 250 200 300 T340 280 T480 320"/>'
        body += f'<path d="M60 370 Q140 320 210 360 T350 340 T480 380"/></g>'
        body += f'<rect x="44" y="380" width="452" height="2" fill="#ffffff" opacity=".08"/>'
        for i in range(7):
            body += f'<rect x="{60 + i * 62}" y="{440 + (i % 3) * 18}" width="26" height="{26 + (i % 4) * 16}" rx="7" fill="{accent}" opacity="{0.35 + (i % 3) * 0.2:.2f}"/>'
        body += "".join(row(540 + i * 104, i) for i in range(4))
    body += '<rect x="24" y="1010" width="492" height="6" rx="3" fill="#ffffff" opacity=".2"/>'
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 540 1080" width="540" height="1080" role="img" aria-label="{app['name']} screenshot {n}">
<defs><radialGradient id="g{uid}" cx="0.8" cy="0.1" r="0.9"><stop offset="0" stop-color="{shade(c1, 0.2)}" stop-opacity=".8"/><stop offset="1" stop-color="#08080a" stop-opacity="0"/></radialGradient></defs>
{head}
{title}
{body}
</svg>
"""


def main():
    with open(DATA, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    for folder in ("icons", "art", "shots"):
        os.makedirs(os.path.join(OUT, folder), exist_ok=True)
    for index, app in enumerate(data["apps"]):
        slug = app["slug"]
        with open(os.path.join(OUT, "icons", slug + ".svg"), "w", encoding="utf-8") as handle:
            handle.write(icon_svg(app))
        with open(os.path.join(OUT, "art", slug + ".svg"), "w", encoding="utf-8") as handle:
            handle.write(art_svg(app, index))
        for n in range(1, 5):
            with open(os.path.join(OUT, "shots", "%s-%d.svg" % (slug, n)), "w", encoding="utf-8") as handle:
                handle.write(shot_svg(app, n))
    print("generated artwork for %d apps" % len(data["apps"]))


if __name__ == "__main__":
    main()
