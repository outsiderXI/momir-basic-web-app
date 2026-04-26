from pathlib import Path
import logging
import time

from config import IMAGE_DIR, PRINTER_PRODUCT_ID, PRINTER_VENDOR_ID

PRINTER_PROFILE = "TM-T88V"
POST_PRINT_FEED_LINES = 2


def _resolve_image_path(card_id_or_path):
    """
    Accept either:
      - a direct filesystem path
      - a card ID that maps to IMAGE_DIR/<id>.jpg
    """
    path = Path(card_id_or_path)

    if path.exists():
        return path

    fallback = IMAGE_DIR / f"{card_id_or_path}.jpg"
    if fallback.exists():
        return fallback

    return None


def _open_printer():
    from escpos.printer import Usb

    return Usb(PRINTER_VENDOR_ID, PRINTER_PRODUCT_ID, profile=PRINTER_PROFILE)


def print_image(card_id_or_path, retries=3, retry_delay=1.0):
    path = _resolve_image_path(card_id_or_path)

    if not path:
        logging.error("Image not found: %s", card_id_or_path)
        return False

    last_error = None

    for attempt in range(1, retries + 1):
        printer = None
        try:
            if attempt > 1:
                logging.warning("Printer recovery attempt %s/%s...", attempt, retries)

            printer = _open_printer()

            # Use the same simple image behavior that worked in your old version.
            printer.image(str(path))

            # Small feed to make sure the card clears cleanly.
            try:
                printer.feed(POST_PRINT_FEED_LINES)
            except Exception:
                pass

            # Your previous version cut after every print, so keep that behavior.
            try:
                printer.cut()
            except Exception:
                pass

            try:
                printer.close()
            except Exception:
                pass

            if attempt > 1:
                logging.info("Printer recovered successfully.")

            return True

        except Exception as e:
            last_error = e
            logging.warning("Printer error on attempt %s/%s: %s", attempt, retries, e)

            if attempt < retries:
                time.sleep(retry_delay)

        finally:
            if printer is not None:
                try:
                    printer.close()
                except Exception:
                    pass

    logging.error("Printing failed after %s attempts: %s", retries, last_error)
    return False


def print_text_receipt(lines, retries=3, retry_delay=1.0):
    if isinstance(lines, str):
        lines = [lines]

    last_error = None
    for attempt in range(1, retries + 1):
        printer = None
        try:
            printer = _open_printer()
            printer.set(align="center", bold=True)
            for line in lines:
                printer.text(str(line) + "\n")
            printer.text("\n")
            try:
                printer.cut()
            except Exception:
                pass
            try:
                printer.close()
            except Exception:
                pass
            return True
        except Exception as e:
            last_error = e
            time.sleep(retry_delay)
        finally:
            if printer is not None:
                try:
                    printer.close()
                except Exception:
                    pass

    logging.error("Receipt text printing failed: %s", last_error)
    return False
