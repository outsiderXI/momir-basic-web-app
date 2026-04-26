import requests

SCRYFALL = "https://api.scryfall.com"


def _scryfall_get(path, **params):
    response = requests.get(f"{SCRYFALL}{path}", params=params, timeout=20)
    response.raise_for_status()
    return response.json()


def _card_image_url(card):
    if "image_uris" in card:
        return card["image_uris"].get("large") or card["image_uris"].get("normal")
    for face in card.get("card_faces", []):
        if "image_uris" in face:
            return face["image_uris"].get("large") or face["image_uris"].get("normal")
    return None


def _card_row(card):
    return (
        card["id"],
        card.get("name", ""),
        int(card.get("cmc") or 0),
        card.get("type_line", ""),
    )


def _candidate(card):
    card_id, name, cmc, type_line = _card_row(card)
    return {
        "id": card_id,
        "name": name,
        "cmc": cmc,
        "type_line": type_line,
    }


def random_creature_by_cmc(cmc):
    try:
        card = _scryfall_get(
            "/cards/random",
            q=f"game:paper -is:digital type:creature mv={int(cmc)}",
        )
        return card.get("id")
    except Exception:
        return None


def get_card_details(card_id):
    try:
        return _card_row(_scryfall_get(f"/cards/{card_id}"))
    except Exception:
        return None


def exact_card_row_by_name(name):
    try:
        data = _scryfall_get(
            "/cards/search",
            q=f'!"{name}" -type:token game:paper -is:digital',
            unique="cards",
            order="released",
        )
        cards = data.get("data", [])
        if cards:
            return _card_row(cards[0])
    except Exception:
        return None
    return None


def search_card_candidates(name, limit=20):
    try:
        data = _scryfall_get(
            "/cards/search",
            q=f"{name} -type:token game:paper -is:digital",
            unique="cards",
            order="name",
        )
    except Exception:
        return []

    return [_candidate(card) for card in data.get("data", [])[:limit] if _card_image_url(card)]
