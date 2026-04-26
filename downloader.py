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


def _card_face_image_urls(card):
    urls = []
    for face in card.get("card_faces", []):
        image_uris = face.get("image_uris")
        if not image_uris:
            continue
        url = image_uris.get("large") or image_uris.get("normal")
        if url:
            urls.append(url)
    return urls


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


def download_card_image(card_id, url, suffix=None):
    filename = f"{card_id}-{suffix}.jpg" if suffix is not None else f"{card_id}.jpg"
    path = IMAGE_DIR / filename
    if path.exists():
        return str(path)

    response = session.get(url, timeout=30)
    response.raise_for_status()
    _process_and_save_image_bytes(response.content, path)
    return str(path)


def get_card_print_image_paths(card_id):
    if not has_internet():
        face_paths = sorted(IMAGE_DIR.glob(f"{card_id}-*.jpg"))
        if len(face_paths) >= 2:
            return [str(path) for path in face_paths]
        path = IMAGE_DIR / f"{card_id}.jpg"
        return [str(path)] if path.exists() else []

    try:
        response = session.get(f"{SCRYFALL}/cards/{card_id}", timeout=20)
        response.raise_for_status()
        card = response.json()
    except Exception as e:
        logging.warning("Card lookup failed for %s: %s", card_id, e)
        face_paths = sorted(IMAGE_DIR.glob(f"{card_id}-*.jpg"))
        if len(face_paths) >= 2:
            return [str(path) for path in face_paths]
        path = IMAGE_DIR / f"{card_id}.jpg"
        return [str(path)] if path.exists() else []

    face_urls = _card_face_image_urls(card)
    if len(face_urls) >= 2:
        paths = []
        for index, url in enumerate(face_urls, start=1):
            try:
                paths.append(download_card_image(card_id, url, suffix=index))
            except Exception as e:
                logging.warning("Card face image download failed for %s face %s: %s", card_id, index, e)
                return []
        return paths

    image_url = _card_image_url(card)
    if not image_url:
        return []

    try:
        return [download_card_image(card_id, image_url)]
    except Exception as e:
        logging.warning("Card image download failed for %s: %s", card_id, e)
        return []


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
