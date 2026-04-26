import difflib
import json
import time

import requests
from rich.console import Console
from rich.table import Table

from config import DATA_DIR

TOKEN_FILE = DATA_DIR / "tokens.json"
console = Console()
SCRYFALL = "https://api.scryfall.com"


def _card_image_url(card):
    if "image_uris" in card:
        return card["image_uris"].get("large") or card["image_uris"].get("normal")
    for face in card.get("card_faces", []):
        if "image_uris" in face:
            return face["image_uris"].get("large") or face["image_uris"].get("normal")
    return None


def search_token_candidates_online(name, limit=18):
    try:
        response = requests.get(
            f"{SCRYFALL}/cards/search",
            params={
                "q": f"{name} type:token game:paper",
                "include_extras": "true",
                "unique": "prints",
                "order": "name",
            },
            timeout=20,
        )
        response.raise_for_status()
    except Exception:
        return []

    tokens = []
    for card in response.json().get("data", [])[:limit * 3]:
        image = _card_image_url(card)
        if not image:
            continue
        tokens.append(
            {
                "id": card["id"],
                "name": card.get("name", ""),
                "power": card.get("power"),
                "toughness": card.get("toughness"),
                "colors": card.get("colors", []),
                "oracle_text": card.get("oracle_text", ""),
                "image": image,
                "local_image": None,
                "set_name": card.get("set_name", ""),
                "set_code": card.get("set", "").upper(),
            }
        )
        if len(tokens) >= limit:
            break
    return tokens


def load_tokens():
    if not TOKEN_FILE.exists():
        return []

    with TOKEN_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def smart_match(tokens, name):
    name = name.lower().strip()

    exact = [t for t in tokens if t["name"].lower() == name]
    if exact:
        return exact

    exact_token = [t for t in tokens if t["name"].lower() == f"{name} token"]
    if exact_token:
        return exact_token

    substring = [t for t in tokens if name in t["name"].lower()]
    if substring:
        return substring

    names = [t["name"] for t in tokens]
    close = difflib.get_close_matches(name, names, n=10, cutoff=0.7)
    return [t for t in tokens if t["name"] in close]


def filter_pt(tokens, pt):
    try:
        p, t = pt.split("/")
        return [c for c in tokens if c.get("power") == p and c.get("toughness") == t]
    except Exception:
        return tokens


def filter_color(tokens, text):
    color_map = {
        "white": "W",
        "blue": "U",
        "black": "B",
        "red": "R",
        "green": "G",
    }
    desired = {color_map.get(c) for c in text.split() if c in color_map}
    desired.discard(None)
    return [t for t in tokens if set(t.get("colors", [])) == desired]


def extract_keywords(card):
    text = card.get("oracle_text", "") or ""
    if not text:
        return "No abilities"

    keywords = [
        "flying",
        "trample",
        "vigilance",
        "haste",
        "deathtouch",
        "lifelink",
        "first strike",
        "double strike",
        "menace",
        "reach",
        "hexproof",
        "indestructible",
        "ward",
    ]
    found = [k for k in keywords if k in text.lower()]
    if found:
        return ", ".join(found)

    return text.split("\n")[0][:60]


def token_signature(token):
    return (
        token.get("name", "").strip().lower(),
        token.get("power"),
        token.get("toughness"),
        tuple(token.get("colors", [])),
        (token.get("oracle_text") or "").strip().lower(),
    )


def dedupe_token_variants(matches):
    """
    Collapse artwork/printing variants of the same functional token into one option.
    Keeps one representative token plus aggregated set info.
    """
    grouped = {}

    for token in matches:
        sig = token_signature(token)
        if sig not in grouped:
            grouped[sig] = {
                "token": token,
                "sets": [],
                "count": 0,
            }

        set_code = token.get("set_code", "") or "?"
        if set_code not in grouped[sig]["sets"]:
            grouped[sig]["sets"].append(set_code)

        grouped[sig]["count"] += 1

    deduped = []
    for group in grouped.values():
        token = dict(group["token"])
        token["_variant_count"] = group["count"]
        token["_set_codes"] = sorted(group["sets"])
        deduped.append(token)

    deduped.sort(
        key=lambda t: (
            t.get("name", ""),
            t.get("power") or "",
            t.get("toughness") or "",
            t.get("oracle_text") or "",
        )
    )

    return deduped


def choose_from_list(matches):
    from input_utils import esc_input

    unique_matches = dedupe_token_variants(matches)

    table = Table(title="Multiple token matches", border_style="magenta")
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold white")
    table.add_column("PT", style="yellow", no_wrap=True)
    table.add_column("Colors", style="green", no_wrap=True)
    table.add_column("Abilities", style="dim")
    table.add_column("Sets", style="blue")

    limited = unique_matches[:10]
    for i, m in enumerate(limited, start=1):
        pt = f"{m.get('power', '?')}/{m.get('toughness', '?')}"
        colors = "".join(m.get("colors", []))
        abilities = extract_keywords(m)
        sets = ", ".join(m.get("_set_codes", [])[:4])
        if len(m.get("_set_codes", [])) > 4:
            sets += "..."

        table.add_row(str(i), m["name"], pt, colors, abilities, sets)

    console.print()
    console.print(table)
    console.print()

    while True:
        choice = esc_input("Select number: ")
        if choice is None:
            return None

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(limited):
                return limited[idx]

        console.print("[red]Invalid selection.[/red]")

def print_multiple(path):
    from input_utils import esc_input
    from printer import print_image

    console.print()
    count_input = esc_input("How many copies? (default 1): ")
    if count_input is None:
        return

    count_input = count_input.strip()

    if count_input == "":
        count = 1
    elif count_input.isdigit() and int(count_input) > 0:
        count = int(count_input)
    else:
        console.print("[yellow]Invalid input, printing 1 copy.[/yellow]")
        count = 1

    for i in range(count):
        console.print()
        console.print(f"[green]Printing copy {i+1}/{count}[/green]")
        print_image(path)
        time.sleep(0.3)


def select_token_from_name(name):
    from input_utils import esc_input

    tokens = load_tokens()
    if not tokens:
        return None

    matches = smart_match(tokens, name)
    if not matches:
        return None

    if len(matches) == 1:
        return matches[0]

    console.print()
    pt_input = esc_input("Optional PT (e.g. 3/3): ")
    if pt_input is None:
        return None

    if pt_input:
        filtered = filter_pt(matches, pt_input)
        if filtered:
            matches = filtered

    # Deduplicate after PT filtering so repeated art variants disappear early.
    matches = dedupe_token_variants(matches)

    if len(matches) > 1:
        console.print()
        color_input = esc_input("Optional color(s): ")
        if color_input is None:
            return None

        color_input = color_input.strip().lower()
        if color_input:
            filtered = filter_color(matches, color_input)
            if filtered:
                matches = filtered

    if len(matches) > 1:
        return choose_from_list(matches)

    return matches[0]

def token_mode_from_name(name):
    card = select_token_from_name(name)
    if not card:
        return False

    console.print()
    console.print(
        f"[bold magenta]Printing token:[/bold magenta] "
        f"[bold white]{card['name']}[/bold white]"
    )

    path = card.get("local_image")
    if path:
        print_multiple(path)
        return True

    console.print("[red]Image missing.[/red]")
    return False
