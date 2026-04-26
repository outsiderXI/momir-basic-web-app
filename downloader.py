import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageEnhance, ImageFilter
from requests.adapters import HTTPAdapter
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from config import BULK_JSON, DATA_DIR, DB_FILE, IMAGE_DIR, PRINTER_MAX_WIDTH, SCRYFALL_BULK_URL

TOKEN_FILE = DATA_DIR / "tokens.json"
VERSION_FILE = DATA_DIR / "scryfall_version.txt"

session = requests.Session()
adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50)
session.mount("http://", adapter)
session.mount("https://", adapter)


def has_internet():
    try:
        session.get("https://api.scryfall.com", timeout=5)
        return True
    except Exception:
        return False


def initialize_database(log_callback=None):
    def log(message):
        print(message)
        if log_callback:
            try:
                log_callback(message)
            except Exception:
                pass

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    if not has_internet():
        log("No internet connection yet. The web UI is available, but card lookups need internet.")
        return

    log("Internet connection available. Using live Scryfall lookups and on-demand image caching.")


def bulk_dataset_updated():
    meta = session.get(SCRYFALL_BULK_URL, timeout=30).json()
    default_cards = next(x for x in meta["data"] if x["type"] == "default_cards")
    new_date = default_cards["updated_at"]

    if VERSION_FILE.exists():
        old_date = VERSION_FILE.read_text(encoding="utf-8").strip()
        if old_date == new_date:
            return False

    VERSION_FILE.write_text(new_date, encoding="utf-8")
    return True


def download_bulk_database():
    meta = session.get(SCRYFALL_BULK_URL, timeout=30).json()
    default_cards = next(x for x in meta["data"] if x["type"] == "default_cards")

    response = session.get(default_cards["download_uri"], stream=True, timeout=60)
    response.raise_for_status()

    total_bytes = int(response.headers.get("content-length", 0))

    with BULK_JSON.open("wb") as f:
        if total_bytes > 0:
            with Progress(
                TextColumn("[bold green]Downloading Scryfall dataset"),
                BarColumn(),
                TaskProgressColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task("download", total=total_bytes)
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    progress.advance(task, len(chunk))
        else:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    print("Scryfall dataset downloaded.")


def _card_image_url(card):
    if "image_uris" in card:
        return (
            card["image_uris"].get("large")
            or card["image_uris"].get("normal")
        )

    for face in card.get("card_faces", []):
        if "image_uris" in face:
            return (
                face["image_uris"].get("large")
                or face["image_uris"].get("normal")
            )

    return None


def _is_printable_paper_card(card):
    if card.get("digital"):
        return False
    if card.get("games") and "paper" not in card.get("games", []):
        return False
    if card.get("set_type") == "minigame":
        return False
    if card.get("oversized"):
        return False
    return _card_image_url(card) is not None


def build_sqlite_index():
    with BULK_JSON.open("r", encoding="utf-8") as f:
        cards = json.load(f)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS cards")
    cur.execute("DROP TABLE IF EXISTS cards_fts")

    cur.execute(
        """
        CREATE TABLE cards (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cmc INTEGER,
            type_line TEXT,
            image TEXT,
            is_creature INTEGER NOT NULL DEFAULT 0,
            is_token INTEGER NOT NULL DEFAULT 0,
            released_at TEXT,
            set_code TEXT,
            set_name TEXT,
            rarity TEXT,
            lang TEXT,
            promo INTEGER NOT NULL DEFAULT 0,
            border_color TEXT,
            frame TEXT,
            full_art INTEGER NOT NULL DEFAULT 0,
            textless INTEGER NOT NULL DEFAULT 0,
            oversized INTEGER NOT NULL DEFAULT 0,
            digital INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE VIRTUAL TABLE cards_fts USING fts5(
            name,
            id UNINDEXED
        )
        """
    )

    insert_cards = []
    insert_fts = []

    for card in cards:
        if not _is_printable_paper_card(card):
            continue

        cid = card["id"]
        name = card["name"]
        type_line = card.get("type_line", "")
        cmc = int(card.get("cmc", 0))
        image_url = _card_image_url(card)

        is_creature = 1 if "Creature" in type_line else 0
        is_token = 1 if card.get("layout") == "token" else 0

        insert_cards.append(
            (
                cid,
                name,
                cmc,
                type_line,
                image_url,
                is_creature,
                is_token,
                card.get("released_at"),
                card.get("set", "").upper(),
                card.get("set_name", ""),
                card.get("rarity", ""),
                card.get("lang", ""),
                1 if card.get("promo") else 0,
                card.get("border_color", ""),
                card.get("frame", ""),
                1 if card.get("full_art") else 0,
                1 if card.get("textless") else 0,
                1 if card.get("oversized") else 0,
                1 if card.get("digital") else 0,
            )
        )
        insert_fts.append((name, cid))

    cur.executemany(
        """
        INSERT OR REPLACE INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        insert_cards,
    )
    cur.executemany("INSERT INTO cards_fts VALUES (?,?)", insert_fts)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_cards_name ON cards(name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cards_cmc_creature ON cards(cmc, is_creature)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cards_token_name ON cards(is_token, name)")

    conn.commit()
    conn.close()

    print(f"Indexed {len(insert_cards)} printable cards.")


def build_token_database():
    print("Extracting tokens from Scryfall dataset...")

    with BULK_JSON.open("r", encoding="utf-8") as f:
        cards = json.load(f)

    tokens = []
    for card in cards:
        if card.get("layout") != "token":
            continue

        image = _card_image_url(card)
        if not image:
            continue

        token = {
            "id": card["id"],
            "name": card["name"],
            "power": card.get("power"),
            "toughness": card.get("toughness"),
            "colors": card.get("colors", []),
            "oracle_text": card.get("oracle_text", ""),
            "image": image,
            "local_image": None,
            "set_name": card.get("set_name", ""),
            "set_code": card.get("set", "").upper(),
        }
        tokens.append(token)

    with TOKEN_FILE.open("w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)

    print(f"{len(tokens)} tokens extracted.")


def _process_and_save_image_bytes(content, path):
    tmp = path.with_name(path.stem + ".tmp.jpg")

    img = Image.open(BytesIO(content)).convert("L")

    scale = PRINTER_MAX_WIDTH / img.width
    w = max(1, int(img.width * scale * 1.19))
    h = max(1, int(img.height * scale * 1.19))

    # High-quality resize
    img = img.resize((w, h), Image.LANCZOS)

    # Boost contrast for better text readability
    img = ImageEnhance.Contrast(img).enhance(1.8)

    # Slight sharpen helps rules text a LOT
    img = img.filter(ImageFilter.SHARPEN)

    # Convert to thermal black/white
    img = img.convert("1", dither=Image.FLOYDSTEINBERG)

    img.save(tmp)
    tmp.replace(path)

def download_card_image(card_id, url):
    path = IMAGE_DIR / f"{card_id}.jpg"
    if path.exists():
        return str(path)

    r = session.get(url, timeout=30)
    r.raise_for_status()
    _process_and_save_image_bytes(r.content, path)
    return str(path)


def ensure_card_image(card_id):
    path = IMAGE_DIR / f"{card_id}.jpg"
    if path.exists():
        return str(path)

    if not has_internet():
        return None

    try:
        response = session.get(f"https://api.scryfall.com/cards/{card_id}", timeout=20)
        response.raise_for_status()
        image_url = _card_image_url(response.json())
    except Exception as e:
        logging.warning("Card lookup failed for %s: %s", card_id, e)
        return None

    if not image_url:
        return None

    try:
        return download_card_image(card_id, image_url)
    except Exception as e:
        logging.warning("Card image download failed for %s: %s", card_id, e)
        return None


def download_all_card_images():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, image
        FROM cards
        WHERE is_token = 0
          AND image IS NOT NULL
          AND image != ''
        """
    )
    rows = cur.fetchall()
    conn.close()

    missing_rows = [(cid, url) for cid, url in rows if not (IMAGE_DIR / f"{cid}.jpg").exists()]
    total = len(missing_rows)

    if total == 0:
        print("All card images already cached.")
        return

    with Progress(
        TextColumn("[bold green]Downloading all card images"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task("download", total=total)

        with ThreadPoolExecutor(max_workers=12) as pool:
            futures = [pool.submit(download_card_image, cid, url) for cid, url in missing_rows]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logging.warning("Card image download failed: %s", e)
                progress.advance(task)


def download_token_images():
    if not TOKEN_FILE.exists():
        return

    with TOKEN_FILE.open("r", encoding="utf-8") as f:
        tokens = json.load(f)

    missing_tokens = []
    for token in tokens:
        path = IMAGE_DIR / f"{token['id']}.jpg"
        if path.exists():
            token["local_image"] = str(path)
        else:
            missing_tokens.append(token)

    total = len(missing_tokens)

    if total > 0:
        with Progress(
            TextColumn("[bold cyan]Downloading token images"),
            BarColumn(),
            TaskProgressColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeRemainingColumn(),
        ) as progress:
            task = progress.add_task("download", total=total)

            for token in missing_tokens:
                try:
                    path = download_card_image(token["id"], token["image"])
                    token["local_image"] = path
                except Exception as e:
                    logging.warning("Token image download failed for %s: %s", token["name"], e)
                    token["local_image"] = None
                progress.advance(task)

    with TOKEN_FILE.open("w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)
