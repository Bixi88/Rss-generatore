#!/usr/bin/env python3
"""Genera feed.xml (RSS 2.0) con i giochi più recenti di AnkerGames.net.

- Cerca nella pagina tutti i link che puntano a /game/<slug>
- Tiene uno storico in seen.json, così ogni gioco ha una data di
  pubblicazione stabile (la prima volta che lo script lo ha visto)
- Se non trova nulla esce con errore: il vecchio feed.xml NON viene toccato
"""

import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# ----------------------------------------------------------------------------
# CONFIGURAZIONE
# ----------------------------------------------------------------------------
BASE_URL = "https://ankergames.net/"

# Pagine da leggere: "Recent Updates" è la fonte più pulita per le novità
# (la home mescola Trending, Top e aggiornamenti).
SOURCES = [
    "https://ankergames.net/recent-updates",
]

FEED_TITLE = "AnkerGames - Feed non ufficiale"
FEED_DESC = "Ultimi giochi pubblicati su AnkerGames.net (feed non ufficiale)"
FEED_LANG = "en"

MAX_ITEMS = 100  # quanti giochi tenere nel feed / nello storico
FEED_FILE = Path("feed.xml")
STATE_FILE = Path("seen.json")

SITE_HOST = urlparse(BASE_URL).netloc.lower().removeprefix("www.")
GAME_PATH_RE = re.compile(r"^/game/[^/?#]+/?$")
GENERIC_TITLES = {
    "download", "download now", "play", "view", "details", "more",
    "read more", "free download", "view game", "see more",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}


# ----------------------------------------------------------------------------
# DOWNLOAD
# ----------------------------------------------------------------------------
def fetch(url):
    """Scarica la pagina (3 tentativi). Ritorna i bytes dell'HTML."""
    last_error = "errore sconosciuto"
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200:
                return resp.content
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code in (403, 429, 503):
                last_error += " (il sito potrebbe bloccare i server di GitHub / Cloudflare)"
        except requests.RequestException as exc:
            last_error = str(exc)
        print(f"[{attempt}/3] {url} -> {last_error}")
        if attempt < 3:
            time.sleep(5 * attempt)
    raise RuntimeError(f"Impossibile scaricare {url}: {last_error}")


# ----------------------------------------------------------------------------
# PARSING
# ----------------------------------------------------------------------------
def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def slug_title(link):
    slug = urlparse(link).path.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").title()


def img_url(img, page_url):
    """URL dell'immagine, preferendo gli attributi lazy-load a src."""
    for attr in ("data-src", "data-lazy-src", "data-original", "src"):
        value = (img.get(attr) or "").strip()
        if value and not value.startswith("data:"):
            return urljoin(page_url, value)
    srcset = (img.get("data-srcset") or img.get("srcset") or "").strip()
    if srcset:
        first = srcset.split(",")[0].strip().split(" ")[0]
        if first and not first.startswith("data:"):
            return urljoin(page_url, first)
    return ""


def extract_title(a):
    heading = a.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    img = a.find("img")
    candidates = [
        heading.get_text(" ") if heading else "",
        a.get("title", ""),
        img.get("alt", "") if img else "",
        a.get_text(" "),
    ]
    for cand in candidates:
        cand = clean(cand)
        if cand and len(cand) <= 120 and cand.lower() not in GENERIC_TITLES:
            return cand
    return ""


def parse_games(content, page_url):
    """Ritorna la lista dei giochi trovati, nell'ordine della pagina."""
    soup = BeautifulSoup(content, "html.parser")

    def game_link(href):
        if not href:
            return None
        parsed = urlparse(urljoin(page_url, href.strip()))
        host = parsed.netloc.lower().removeprefix("www.")
        if host != SITE_HOST or not GAME_PATH_RE.match(parsed.path):
            return None
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"

    def find_image(a):
        # Cerca l'immagine dentro il link, poi nel contenitore (max 3 livelli)
        # ma solo finché il contenitore riguarda un solo gioco.
        node = a
        for _ in range(3):
            img = node.find("img")
            if img:
                url = img_url(img, page_url)
                if url:
                    return url
            node = node.parent
            if node is None or node.name in ("body", "html"):
                break
            links = {game_link(x["href"]) for x in node.find_all("a", href=True)}
            links.discard(None)
            if len(links) > 1:
                break
        return ""

    games = {}
    for a in soup.find_all("a", href=True):
        link = game_link(a["href"])
        if not link:
            continue
        game = games.setdefault(link, {"link": link, "title": "", "image": ""})
        if not game["title"]:
            game["title"] = extract_title(a)
        if not game["image"]:
            game["image"] = find_image(a)

    for game in games.values():
        if not game["title"]:
            game["title"] = slug_title(game["link"])
    return list(games.values())


def print_debug(content, page_url):
    """Stampa nel log informazioni utili per capire cosa non va."""
    text = content.decode("utf-8", "replace")
    soup = BeautifulSoup(content, "html.parser")
    hrefs = [a["href"] for a in soup.find_all("a", href=True)]
    print(f"--- DEBUG {page_url} ---")
    print(f"Dimensione HTML: {len(content)} bytes | link totali: {len(hrefs)}")
    print("Primi 25 link trovati:")
    for href in hrefs[:25]:
        print("  ", href)
    print("Primi 1500 caratteri dell'HTML:")
    print(text[:1500])
    print("--- FINE DEBUG ---")


# ----------------------------------------------------------------------------
# STORICO
# ----------------------------------------------------------------------------
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            print(f"Attenzione: {STATE_FILE} illeggibile ({exc}), riparto da zero.")
    return {}


def update_state(state, games):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    new_count = 0
    for i, game in enumerate(games):
        entry = state.get(game["link"])
        if entry is None:
            # -i secondi: il primo della pagina risulta il più recente
            first_seen = (now - timedelta(seconds=i)).isoformat()
            state[game["link"]] = {
                "title": game["title"],
                "image": game["image"],
                "first_seen": first_seen,
            }
            new_count += 1
        else:
            entry["title"] = game["title"] or entry.get("title", "")
            entry["image"] = game["image"] or entry.get("image", "")

    ordered = sorted(state.items(), key=lambda kv: kv[1]["first_seen"], reverse=True)
    return dict(ordered[:MAX_ITEMS]), new_count


# ----------------------------------------------------------------------------
# FEED
# ----------------------------------------------------------------------------
def get_feed_url():
    explicit = os.environ.get("FEED_URL", "").strip()
    if explicit:
        return explicit
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        base = f"https://{owner.lower()}.github.io/"
        if name.lower() != f"{owner.lower()}.github.io":
            base += f"{name}/"
        return base + "feed.xml"
    return ""


def build_feed(state):
    fg = FeedGenerator()
    fg.title(FEED_TITLE)
    fg.link(href=BASE_URL, rel="alternate")
    feed_url = get_feed_url()
    if feed_url:
        fg.link(href=feed_url, rel="self", type="application/rss+xml")
    fg.description(FEED_DESC)
    fg.language(FEED_LANG)
    fg.ttl(360)

    items = sorted(state.items(), key=lambda kv: kv[1]["first_seen"], reverse=True)
    if items:
        # Data fissa = ultimo gioco: se non ci sono novità il file non cambia
        # e il workflow non crea commit inutili.
        fg.lastBuildDate(datetime.fromisoformat(items[0][1]["first_seen"]))

    for link, data in items:
        title = data.get("title") or slug_title(link)
        fe = fg.add_entry(order="append")
        fe.guid(link, permalink=True)
        fe.title(title)
        fe.link(href=link)
        fe.published(datetime.fromisoformat(data["first_seen"]))
        safe_title = html.escape(title)
        if data.get("image"):
            fe.description(
                f'<img src="{html.escape(data["image"], quote=True)}" '
                f'style="max-width:100%;"><br/><p>{safe_title}</p>'
            )
        else:
            fe.description(safe_title)

    fg.rss_file(str(FEED_FILE), pretty=True)
    return len(items)


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    games = []
    errors = 0
    for source in SOURCES:
        try:
            content = fetch(source)
        except RuntimeError as exc:
            print(exc)
            errors += 1
            continue
        found = parse_games(content, source)
        print(f"{source}: {len(found)} giochi trovati")
        if not found:
            print_debug(content, source)
        games.extend(found)

    # Rimuove duplicati mantenendo l'ordine
    unique = {}
    for game in games:
        unique.setdefault(game["link"], game)
    games = list(unique.values())

    if not games:
        print("ERRORE: nessun gioco trovato. feed.xml non è stato modificato.")
        sys.exit(1)

    state, new_count = update_state(load_state(), games)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    total = build_feed(state)
    print(f"Feed generato: {total} giochi nel feed, {new_count} nuovi in questa esecuzione.")
    if errors:
        print(f"Attenzione: {errors} sorgente/i non raggiungibile/i.")


if __name__ == "__main__":
    main()
