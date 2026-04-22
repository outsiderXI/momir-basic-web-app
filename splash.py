import random
import shutil
import sys
import time
from pathlib import Path

from PIL import Image
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.text import Text

console = Console()

MOMIR_QUOTES = [
    "Consult the Simic Combine...",
    "Evolving the battlefield...",
    "Sequencing creature genomes...",
    "Mutating battlefield organisms...",
    "Stabilizing mana matrix...",
    "Summoning creature prototype...",
    "Calculating mana value distributions...",
    "Breeding new evolutionary forms...",
    "Initializing biomantic protocols...",
    "The experiment begins...",
]

BOOT_LINES = [
    "Initializing biomantic matrix...",
    "Sequencing creature DNA...",
    "Splicing token genomes...",
    "Loading Simic growth chambers...",
    "Warming printer interface...",
]


def type_text(text, speed=0.02, style=None):
    if style:
        console.print(Text(text, style=style))
        time.sleep(max(0.1, speed * 10))
        return

    for char in text:
        sys.stdout.write(char)
        sys.stdout.flush()
        time.sleep(speed)
    print()


def show_quote():
    quote = random.choice(MOMIR_QUOTES)
    console.print(Align.center(Text(quote, style="italic bright_black")))
    console.print()


def show_splash(delay=0.045):
    console.clear()

    image_path = Path("assets/momir_vig.png")
    if not image_path.exists():
        console.print(
            Panel(
                Align.center(Text("MOMIR VIG PRINTER", style="bold bright_green")),
                border_style="bright_green",
                padding=(1, 2),
            )
        )
        return

    term_width = shutil.get_terminal_size().columns
    img = Image.open(image_path)
    scale = min((term_width - 10) / img.width, 1)
    new_w = max(24, int(img.width * scale))
    new_h = max(8, int(img.height * scale * 0.5))
    img = img.resize((new_w, new_h))
    img = img.convert("L")

    pixels = img.load()
    chars = " .:-=+*#%@"

    lines = []
    for y in range(img.height):
        row = ""
        for x in range(img.width):
            brightness = pixels[x, y]
            idx = min(len(chars) - 1, int(brightness / 256 * len(chars)))
            row += chars[idx]
        lines.append(row)

    console.print(Panel("", border_style="bright_green", padding=(0, 1)))

    for line in lines:
        console.print(Align.center(Text(line, style="green")))
        time.sleep(delay)

def show_boot_sequence():
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold green]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task("Booting system", total=len(BOOT_LINES))
        for line in BOOT_LINES:
            progress.update(task, description=line)
            time.sleep(0.35)
            progress.advance(task)
