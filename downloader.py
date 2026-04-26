import logging
from io import BytesIO

import requests
from PIL import Image, ImageEnhance, ImageFilter
from requests.adapters import HTTPAdapter

from config import IMAGE_DIR, PRINTER_MAX_WIDTH

SCRYFALL = "https://api.scryfall.com"

session = requests.Session()
adapter = HTTPAdapter(pool_connections=12, pool_maxsize=12)
session.mount("http://", adapter)
session.mount("https://", adapter)


def has_internet():
    try:
        session.get(SCRYFALL, timeout=5)
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

    if has_internet():
        log("Internet connection available. Using live Scryfall lookups and on-demand image caching.")
    else:
        log("No internet connection yet. The web UI is available, but card lookups need internet.")


def _card_image_url(card):
    if "image_uris" in card:
        return card["image_uris"].get("large") or card["image_uris"].get("normal")

    for face in card.get("card_faces", []):
        if "image_uris" in face:
            return face["image_uris"].get("large") or face["image_uris"].get("normal")

    return None


def _process_and_save_image_bytes(content, path):
    tmp = path.with_name(path.stem + ".tmp.jpg")

    img = Image.open(BytesIO(content)).convert("L")

    scale = PRINTER_MAX_WIDTH / img.width
    w = max(1, int(img.width * scale * 1.19))
    h = max(1, int(img.height * scale * 1.19))

    img = img.resize((w, h), Image.LANCZOS)
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = img.filter(ImageFilter.SHARPEN)
    img = img.convert("1", dither=Image.FLOYDSTEINBERG)

    img.save(tmp)
    tmp.replace(path)


def download_card_image(card_id, url):
    path = IMAGE_DIR / f"{card_id}.jpg"
    if path.exists():
        return str(path)

    response = session.get(url, timeout=30)
    response.raise_for_status()
    _process_and_save_image_bytes(response.content, path)
    return str(path)


def ensure_card_image(card_id):
    path = IMAGE_DIR / f"{card_id}.jpg"
    if path.exists():
        return str(path)

    if not has_internet():
        return None

    try:
        response = session.get(f"{SCRYFALL}/cards/{card_id}", timeout=20)
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
