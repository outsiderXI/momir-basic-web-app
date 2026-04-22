from pathlib import Path

DATA_DIR = Path("./data")
IMAGE_DIR = DATA_DIR / "images"
BULK_JSON = DATA_DIR / "scryfall_cards.json"
DB_FILE = DATA_DIR / "cards.db"

IMAGE_DIR.mkdir(parents=True, exist_ok=True)

PRINTER_VENDOR_ID = 0x04B8
PRINTER_PRODUCT_ID = 0x0202
PRINTER_MAX_WIDTH = 384

SCRYFALL_BULK_URL = "https://api.scryfall.com/bulk-data"
