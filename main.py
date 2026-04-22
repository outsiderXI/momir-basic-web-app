import time

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from downloader import ensure_card_image, initialize_database
from input_utils import esc_input
from printer import print_image
from search import cache_stats, get_card_details, human_size, random_creature_by_cmc, search_card_candidates
from splash import show_boot_sequence, show_quote, show_splash, type_text
from tokens import token_mode_from_name

console = Console()


def render_header():
    title = Text("MOMIR VIG PRINTER", style="bold bright_green")
    subtitle = Text("Random Creatures • Tokens • Any Card Print", style="italic cyan")
    console.print(
        Panel(
            Align.center(Group(title, subtitle)),
            border_style="green",
            padding=(1, 2),
        )
    )


def render_help():
    help_text = Text()
    help_text.append("Enter one of the following:\n", style="bold white")
    help_text.append("  • 1-16", style="bold yellow")
    help_text.append(" for a random creature by mana value\n")
    help_text.append("  • token name", style="bold magenta")
    help_text.append(" for token printing\n")
    help_text.append("  • any card name", style="bold cyan")
    help_text.append(" for normal card printing\n\n")
    help_text.append("ESC", style="bold red")
    help_text.append(" = Exit")

    console.print(
        Panel(
            help_text,
            title="[bold green]Ready[/bold green]",
            border_style="bright_green",
            padding=(1, 2),
        )
    )


def render_cache_stats():
    stats = cache_stats()
    text = Text()
    text.append("Cached images: ", style="bold white")
    text.append(str(stats["image_count"]), style="bold green")
    text.append("\nCache size: ", style="bold white")
    text.append(human_size(stats["image_size_bytes"]), style="bold cyan")

    console.print(
        Panel(
            text,
            title="[bold blue]Cache Stats[/bold blue]",
            border_style="blue",
            padding=(1, 2),
        )
    )


def startup():
    console.clear()
    show_splash()
    console.print()
    type_text("[ Booting Momir Vig Printer... ]", 0.02)
    time.sleep(0.3)
    show_quote()
    show_boot_sequence()
    type_text("[ Checking local card database... ]", 0.02)
    initialize_database()
    time.sleep(0.3)
    console.clear()
    render_header()
    render_help()
    render_cache_stats()


def show_prompt():
    console.print()
    return esc_input("⚡ Input > ")


def render_card_preview(name, cmc, type_line, cached):
    text = Text()
    text.append(f"{name}\n", style="bold white")
    text.append(f"Mana Value: {cmc}\n", style="yellow")
    text.append(f"{type_line}\n", style="cyan")
    text.append("Cached locally: ", style="bold white")
    text.append("✓" if cached else "No", style="bold green" if cached else "bold yellow")

    console.print(
        Panel(
            text,
            title="[bold green]Card Ready[/bold green]",
            border_style="green",
            padding=(1, 2),
        )
    )


def print_random_creature_by_cmc(cmc):
    card_id = random_creature_by_cmc(cmc)
    if not card_id:
        console.print("[bold red]No creature found with that mana value.[/bold red]")
        return

    details = get_card_details(card_id)
    if not details:
        console.print("[bold red]Card details not found.[/bold red]")
        return

    _, name, card_cmc, type_line = details
    path = ensure_card_image(card_id)
    if not path:
        console.print("[bold red]Creature image missing and could not be downloaded.[/bold red]")
        return

    render_card_preview(name, card_cmc, type_line, True)
    console.print(f"[bold green]Printing random creature with mana value {cmc}...[/bold green]")
    print_image(card_id)


def choose_card_candidate(candidates):
    if len(candidates) == 1:
        return candidates[0]

    table = Table(title="Multiple card matches found", border_style="yellow")
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold white")
    table.add_column("MV", style="yellow")
    table.add_column("Type", style="green")
    table.add_column("Cache", style="magenta")

    limited = candidates[:10]
    for i, card in enumerate(limited, start=1):
        table.add_row(
            str(i),
            card["name"],
            str(card["cmc"]),
            card["type_line"],
            "✓" if card["cached"] else "No",
        )

    console.print()
    console.print(table)

    while True:
        choice = esc_input("Select number (ESC to cancel): ")
        if choice is None:
            return None
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(limited):
                return limited[idx]
        console.print("[red]Invalid selection.[/red]")


def print_named_card(name):
    from search import exact_card_row_by_name

    exact = exact_card_row_by_name(name)
    if exact:
        card_id, card_name, card_cmc, type_line = exact

        path = ensure_card_image(card_id)
        if not path:
            console.print("[bold red]Card image missing and could not be downloaded.[/bold red]")
            return False

        render_card_preview(card_name, card_cmc, type_line, True)
        console.print(f"[bold green]Printing card:[/bold green] [bold white]{card_name}[/bold white]")
        return print_image(card_id)

    candidates = search_card_candidates(name, limit=20)
    if not candidates:
        console.print("[bold red]No matching non-token card found.[/bold red]")
        return False

    selected = choose_card_candidate(candidates)
    if not selected:
        return False

    card_id = selected["id"]
    card_name = selected["name"]
    card_cmc = selected["cmc"]
    type_line = selected["type_line"]

    path = ensure_card_image(card_id)
    if not path:
        console.print("[bold red]Card image missing and could not be downloaded.[/bold red]")
        return False

    render_card_preview(card_name, card_cmc, type_line, True)
    console.print(f"[bold green]Printing card:[/bold green] [bold white]{card_name}[/bold white]")
    return print_image(card_id)


def handle_input(text):
    raw = text.strip()
    if not raw:
        return

    if raw.lower() == "stats":
        render_cache_stats()
        return

    if raw.isdigit():
        cmc = int(raw)
        if 1 <= cmc <= 16:
            print_random_creature_by_cmc(cmc)
            return

    if token_mode_from_name(raw):
        return

    if print_named_card(raw):
        return

    console.print("[bold red]No token or card match found.[/bold red]")


def main():
    startup()
    while True:
        value = show_prompt()
        if value is None:
            console.print("\n[bold red]Exiting Momir Vig Printer.[/bold red]")
            break
        handle_input(value)


if __name__ == "__main__":
    main()
