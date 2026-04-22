from pathlib import Path
import time

from escpos.printer import Usb
from rich.console import Console
from rich.panel import Panel

from config import IMAGE_DIR, PRINTER_PRODUCT_ID, PRINTER_VENDOR_ID

console = Console()

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
    return Usb(PRINTER_VENDOR_ID, PRINTER_PRODUCT_ID, profile=PRINTER_PROFILE)


def print_image(card_id_or_path, retries=3, retry_delay=1.0):
    path = _resolve_image_path(card_id_or_path)

    if not path:
        console.print(
            Panel(
                f"[bold red]Image not found:[/bold red] {card_id_or_path}",
                title="Print Error",
                border_style="red",
            )
        )
        return False

    last_error = None

    for attempt in range(1, retries + 1):
        printer = None
        try:
            if attempt > 1:
                console.print(
                    Panel(
                        f"[yellow]Printer recovery attempt {attempt}/{retries}...[/yellow]",
                        title="Printer Recovery",
                        border_style="yellow",
                    )
                )

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
                console.print("[bold green]Printer recovered successfully.[/bold green]")

            return True

        except Exception as e:
            last_error = e

            console.print(
                Panel(
                    f"[red]Printer error:[/red] {e}",
                    title=f"Print Attempt {attempt}/{retries}",
                    border_style="red",
                )
            )

            if attempt < retries:
                console.print("[yellow]Retrying printer connection...[/yellow]")
                time.sleep(retry_delay)

        finally:
            if printer is not None:
                try:
                    printer.close()
                except Exception:
                    pass

    console.print(
        Panel(
            f"[bold red]Printing failed after {retries} attempts.[/bold red]\n{last_error}",
            title="Printer Offline",
            border_style="bold red",
        )
    )
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

    console.print(
        Panel(
            f"[bold red]Receipt text printing failed.[/bold red]\n{last_error}",
            title="Printer Offline",
            border_style="bold red",
        )
    )
    return False
