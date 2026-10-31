#!/usr/bin/env python3
"""NOIR publishing CLI - add, update and validate catalogue entries.

Examples:
    python3 tools/catalog.py list --type app
    python3 tools/catalog.py show signal
    python3 tools/catalog.py new "Example App" --category utilities
    python3 tools/catalog.py add --file entry.json
    python3 tools/catalog.py update signal --set tagline="Faster, quieter messaging"
    python3 tools/catalog.py update signal --set 'highlights=["One","Two"]'
    python3 tools/catalog.py validate
    python3 tools/catalog.py stats

The CLI edits data/apps.json in place. Every write is validated first: an entry
that breaks the schema is rejected with the exact problems listed.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import catalogue  # noqa: E402


def parse_value(raw):
    """Turn a command line value into JSON when it looks like JSON."""
    text = raw.strip()
    if text[:1] in "[{" or text in ("true", "false", "null"):
        try:
            return json.loads(text)
        except ValueError:
            return raw
    return raw


def parse_pairs(items, keys=("name", "detail"), separator="|"):
    """Parse repeated --flag "a|b|c" options into a list of dicts.

    Each positional part maps onto the matching key, so the same helper
    builds mod features (name/detail), build variants
    (name/version/size/arch) and FAQ entries (question/answer).
    """
    out = []
    for item in items or []:
        parts = [p.strip() for p in str(item).split(separator)]
        row = {}
        for index, key in enumerate(keys):
            if index < len(parts):
                row[key] = parts[index]
            else:
                row[key] = ""
        out.append(row)
    return out


def cmd_list(args):
    data = catalogue.load()
    items = data["apps"]
    if args.type:
        items = catalogue.filter_apps(items, kind=args.type)
    if args.mods:
        items = [a for a in items if catalogue.is_mod(a)]
    if args.json:
        print(json.dumps(items, indent=2, ensure_ascii=False))
        return 0
    print("%-24s %-5s %-16s %-6s %s" % ("SLUG", "TYPE", "CATEGORY", "RATE", "NAME"))
    for app in items:
        print("%-24s %-5s %-16s %-6s %s" % (
            app["slug"], app.get("type", ""), app.get("category", ""),
            app.get("rating", ""), app.get("name", ""),
        ))
    print("\n%d entries" % len(items))
    return 0


def cmd_show(args):
    app = catalogue.find_app(args.slug)
    if not app:
        print("no entry with slug '%s'" % args.slug, file=sys.stderr)
        return 1
    print(json.dumps(app, indent=2, ensure_ascii=False))
    return 0


def cmd_new(args):
    data = catalogue.load()
    existing = {a["slug"] for a in data["apps"]}
    slug = catalogue.unique_slug(args.name, existing)
    entry = catalogue.blank_entry(slug, args.name, kind=args.type, category=args.category)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(entry, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print("wrote starter entry to %s" % args.out)
    else:
        print(json.dumps(entry, indent=2, ensure_ascii=False))
    return 0


def build_entry(args, data):
    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            entry = json.load(handle)
    else:
        if not args.name:
            raise SystemExit("either --file or --name is required")
        existing = {a["slug"] for a in data["apps"]}
        slug = args.slug or catalogue.unique_slug(args.name, existing)
        entry = catalogue.blank_entry(slug, args.name, kind=args.type, category=args.category)
    for pair in (args.set or []):
        if "=" not in pair:
            raise SystemExit("--set expects key=value, got '%s'" % pair)
        name, raw = pair.split("=", 1)
        entry[name.strip()] = parse_value(raw)
    return entry


def apply_mod_options(entry, args):
    if args.mod:
        entry["type"] = "mod"
        entry["isMod"] = True
    if args.mod_of:
        entry["modOf"] = args.mod_of
    if args.mod_feature:
        entry["modFeatures"] = parse_pairs(args.mod_feature)
    if args.install_step:
        entry["modInstallSteps"] = list(args.install_step)
    if args.variant:
        entry["modVariants"] = parse_pairs(args.variant, ("name", "version", "size", "arch"))
    if args.faq:
        entry["modFaq"] = parse_pairs(args.faq, ("question", "answer"))
    if args.disclaimer:
        entry["modDisclaimer"] = args.disclaimer
    if args.package_id:
        entry["packageId"] = args.package_id
    if args.build_type:
        entry["buildType"] = args.build_type
    if args.download_url:
        entry["download"] = {"url": args.download_url, "label": args.download_label or "Download build"}
    elif args.unavailable_reason:
        entry["download"] = {"url": "", "label": "No build published", "unavailableReason": args.unavailable_reason}
    if entry.get("type") == "mod" and "isMod" not in entry:
        entry["isMod"] = True
    return entry


def cmd_add(args):
    data = catalogue.load()
    entry = apply_mod_options(build_entry(args, data), args)
    if not entry.get("slug"):
        entry["slug"] = catalogue.unique_slug(entry.get("name", "entry"), {a["slug"] for a in data["apps"]})
    if not entry.get("icon"):
        entry["icon"] = "/static/img/icons/%s.svg" % entry["slug"]
    problems = catalogue.validate_entry(entry, data)
    if problems:
        print("entry rejected, fix these first:", file=sys.stderr)
        for problem in problems:
            print("  - %s" % problem, file=sys.stderr)
        return 2
    if entry["slug"] in {a["slug"] for a in data["apps"]}:
        print("entry rejected: slug '%s' already exists" % entry["slug"], file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(entry, indent=2, ensure_ascii=False))
        return 0
    data["apps"].append(entry)
    data["apps"].sort(key=lambda a: a["slug"])
    catalogue.save(data)
    print("added '%s' (%d entries total)" % (entry["slug"], len(data["apps"])))
    print("next: python3 tools/fetch_icons.py --only %s" % entry["slug"])
    return 0


def cmd_update(args):
    data = catalogue.load()
    app = catalogue.find_app(args.slug)
    if not app:
        print("no entry with slug '%s'" % args.slug, file=sys.stderr)
        return 1
    changes = {}
    for pair in (args.set or []):
        if "=" not in pair:
            raise SystemExit("--set expects key=value, got '%s'" % pair)
        name, raw = pair.split("=", 1)
        changes[name.strip()] = parse_value(raw)
    if args.file:
        with open(args.file, "r", encoding="utf-8") as handle:
            patch = json.load(handle)
        changes.update(patch)
    mod_options = ("mod", "mod_of", "mod_feature", "install_step", "variant", "faq",
                   "disclaimer", "package_id", "build_type", "download_url", "unavailable_reason")
    if not changes and not any(getattr(args, name, None) for name in mod_options):
        print("nothing to update - pass --set key=value, --file or a mod flag", file=sys.stderr)
        return 1
    for key, value in changes.items():
        app[key] = value
    app = apply_mod_options(app, args)
    problems = catalogue.validate_entry(app, data)
    if problems:
        print("update rejected, fix these first:", file=sys.stderr)
        for problem in problems:
            print("  - %s" % problem, file=sys.stderr)
        return 2
    if args.dry_run:
        print(json.dumps(app, indent=2, ensure_ascii=False))
        return 0
    catalogue.save(data)
    for key in changes:
        print("updated %s.%s" % (args.slug, key))
    for name in mod_options:
        if getattr(args, name, None):
            print("updated %s.%s" % (args.slug, name))
    return 0


def cmd_remove(args):
    data = catalogue.load()
    before = len(data["apps"])
    data["apps"] = [a for a in data["apps"] if a["slug"] != args.slug]
    if len(data["apps"]) == before:
        print("no entry with slug '%s'" % args.slug, file=sys.stderr)
        return 1
    catalogue.save(data)
    print("removed '%s'" % args.slug)
    return 0


def cmd_validate(args):
    data = catalogue.load()
    issues = catalogue.validate(data)
    if args.json:
        print(json.dumps([
            {"slug": slug, "problems": problems} for slug, problems in issues
        ], indent=2, ensure_ascii=False))
    else:
        if not issues:
            print("catalogue is valid: %d entries, %d categories"
                  % (len(data["apps"]), len(data["categories"])))
        else:
            print("%d entries with problems:" % len(issues))
            for slug, problems in issues:
                print("  %s" % slug)
                for problem in problems:
                    print("    - %s" % problem)
    return 1 if issues else 0


def cmd_stats(args):
    data = catalogue.load()
    apps = data["apps"]
    mods = [a for a in apps if catalogue.is_mod(a)]
    by_category = {}
    for app in apps:
        by_category[app.get("category", "?")] = by_category.get(app.get("category", "?"), 0) + 1
    print("entries      : %d" % len(apps))
    print("apps         : %d" % len([a for a in apps if a.get("type") == "app"]))
    print("games        : %d" % len([a for a in apps if a.get("type") == "game"]))
    print("mods         : %d" % len(mods))
    print("categories   : %d" % len(data["categories"]))
    print("real icons   : %d" % len([a for a in apps if a.get("icon", "").startswith("/static/img/icons/real/")]))
    print("\nper category:")
    for slug, count in sorted(by_category.items(), key=lambda kv: -kv[1]):
        print("  %-18s %d" % (slug, count))
    return 0


def main():
    parser = argparse.ArgumentParser(description="NOIR catalogue publishing CLI")
    parser.add_argument("--data", default=None, help="path to apps.json (default: data/apps.json)")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="list catalogue entries")
    p_list.add_argument("--type", choices=("app", "game", "mod"), default=None)
    p_list.add_argument("--mods", action="store_true", help="only mod entries")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="print one entry as JSON")
    p_show.add_argument("slug")
    p_show.set_defaults(func=cmd_show)

    p_new = sub.add_parser("new", help="print a starter entry")
    p_new.add_argument("name")
    p_new.add_argument("--type", choices=("app", "game", "mod"), default="app")
    p_new.add_argument("--category", default="utilities")
    p_new.add_argument("--out", default=None, help="write the starter entry to a file")
    p_new.set_defaults(func=cmd_new)

    p_add = sub.add_parser("add", help="add an entry to the catalogue")
    p_add.add_argument("--file", default=None, help="JSON file with the entry")
    p_add.add_argument("--name", default=None)
    p_add.add_argument("--slug", default=None)
    p_add.add_argument("--type", choices=("app", "game", "mod"), default="app")
    p_add.add_argument("--category", default="utilities")
    p_add.add_argument("--set", action="append", metavar="KEY=VALUE")
    p_add.add_argument("--mod", action="store_true", help="mark the entry as a mod")
    p_add.add_argument("--mod-of", dest="mod_of", default=None, help="slug of the base app")
    p_add.add_argument("--mod-feature", dest="mod_feature", action="append", metavar="NAME|DETAIL")
    p_add.add_argument("--install-step", dest="install_step", action="append")
    p_add.add_argument("--variant", action="append", metavar="NAME|VERSION|SIZE|ARCH")
    p_add.add_argument("--faq", action="append", metavar="QUESTION|ANSWER")
    p_add.add_argument("--disclaimer", default=None)
    p_add.add_argument("--package-id", dest="package_id", default=None)
    p_add.add_argument("--build-type", dest="build_type", default=None)
    p_add.add_argument("--download-url", dest="download_url", default=None)
    p_add.add_argument("--download-label", dest="download_label", default=None)
    p_add.add_argument("--unavailable-reason", dest="unavailable_reason", default=None)
    p_add.add_argument("--dry-run", dest="dry_run", action="store_true")
    p_add.set_defaults(func=cmd_add)

    p_update = sub.add_parser("update", help="update fields of an existing entry")
    p_update.add_argument("slug")
    p_update.add_argument("--set", action="append", metavar="KEY=VALUE")
    p_update.add_argument("--file", default=None, help="JSON file with a partial entry")
    p_update.add_argument("--mod", action="store_true")
    p_update.add_argument("--mod-of", dest="mod_of", default=None)
    p_update.add_argument("--mod-feature", dest="mod_feature", action="append", metavar="NAME|DETAIL")
    p_update.add_argument("--install-step", dest="install_step", action="append")
    p_update.add_argument("--variant", action="append", metavar="NAME|VERSION|SIZE|ARCH")
    p_update.add_argument("--faq", action="append", metavar="QUESTION|ANSWER")
    p_update.add_argument("--disclaimer", default=None)
    p_update.add_argument("--package-id", dest="package_id", default=None)
    p_update.add_argument("--build-type", dest="build_type", default=None)
    p_update.add_argument("--download-url", dest="download_url", default=None)
    p_update.add_argument("--download-label", dest="download_label", default=None)
    p_update.add_argument("--unavailable-reason", dest="unavailable_reason", default=None)
    p_update.add_argument("--dry-run", dest="dry_run", action="store_true")
    p_update.set_defaults(func=cmd_update)

    p_remove = sub.add_parser("remove", help="remove an entry")
    p_remove.add_argument("slug")
    p_remove.set_defaults(func=cmd_remove)

    p_validate = sub.add_parser("validate", help="validate every entry")
    p_validate.add_argument("--json", action="store_true")
    p_validate.set_defaults(func=cmd_validate)

    p_stats = sub.add_parser("stats", help="catalogue statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    if args.data:
        os.environ["NOIR_DATA"] = os.path.abspath(args.data)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
