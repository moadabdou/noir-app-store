# NOIR app store

An AMOLED black Android app, game, and mod-listing catalog. Python serves pages from shared HTML templates and a structured JSON catalog, with responsive CSS and browser-side search and bookmarks.

## Run locally

Python 3.10 or newer is recommended. The application itself uses only the Python standard library.

```sh
python3 server.py
```

Open http://localhost:8084. Configure the bind address and port with `NOIR_HOST` and `NOIR_PORT`:

```sh
NOIR_HOST=127.0.0.1 NOIR_PORT=8084 python3 server.py
```

## Add and update apps

All app entries live in `data/apps.json`. Add entries through the publishing CLI; routes, search, and categories read the same catalog without new page templates.

```sh
python3 tools/catalog.py new "Example App" --category utilities --out entry.json
# Edit entry.json with the app's metadata, official listing URL, and assets.
python3 tools/catalog.py add --file entry.json
python3 tools/catalog.py validate
python3 tools/catalog.py show example-app
python3 tools/catalog.py update example-app --set tagline="A useful Android utility"
```

Use `python3 tools/catalog.py --help` and the help for each subcommand for more options, including mod features, build variants, installation steps, and FAQ entries. Catalog writes are validated and atomic. A cached catalog loader handles reads; for a substantially larger catalog or concurrent editors, migrate that layer to a database.

## Images and demo content

```sh
python3 tools/fetch_icons.py --only signal vlc
python3 tools/gen_art.py
```

The icon fetcher downloads and validates images from official listing sources and records provenance in `static/img/icons/real/manifest.json`. Existing generated icons are fallbacks. Generated app previews are illustrations, not actual app screenshots. Third-party names and images belong to their respective owners.

The included mod entries are clearly labeled demonstrations. Their feature labels and metadata demonstrate the template; they do not represent available modified packages. Downloads remain unavailable until an appropriate build URL is configured. Official app entries link to their original store listings. Treat seed versions, ratings, dates, and descriptions as sample editorial data to verify before publishing.

## Project structure

- `server.py`: HTTP routes and page rendering.
- `catalogue.py`: catalog loading, filtering, caching, and validation.
- `data/apps.json`: app, category, and mod metadata.
- `templates/`: shared page templates.
- `static/`: styles, scripts, cached icons, and illustrations.
- `tools/`: publishing, asset refresh, browser checks, and screenshots.
- `systemd/amoled-store.service`: example persistent service for the original Ubuntu deployment.

## Checks

```sh
python3 tools/catalog.py validate
python3 -m compileall -q server.py catalogue.py tools
python3 -m venv .checks/venv
.checks/venv/bin/pip install playwright
.checks/venv/bin/python -m playwright install chromium
# Run the server in another terminal first.
.checks/venv/bin/python tools/verify.py
.checks/venv/bin/python tools/shoot.py
.checks/venv/bin/python tools/layout_check.py
```

Browser checks and screenshots are optional development tools. Their output and environments belong in `.checks/` and are excluded from Git.

## Ubuntu deployment

The example service assumes user `ubuntu`, project directory `/home/ubuntu/amoled-store`, and port 8084. Adjust these values for another host. Create the log directory before starting it:

```sh
mkdir -p .checks
sudo cp systemd/amoled-store.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now amoled-store.service
```

Allow TCP 8084 through the host and cloud firewalls as appropriate. After code changes, restart with `sudo systemctl restart amoled-store.service`. Use a reverse proxy for a domain and HTTPS.
