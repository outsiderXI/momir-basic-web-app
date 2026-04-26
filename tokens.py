from difflib import SequenceMatcher

import requests

SCRYFALL = "https://api.scryfall.com"


def _card_image_url(card):
    if "image_uris" in card:
        return card["image_uris"].get("large") or card["image_uris"].get("normal")
    for face in card.get("card_faces", []):
        if "image_uris" in face:
            return face["image_uris"].get("large") or face["image_uris"].get("normal")
    return None


def search_token_candidates_online(name, limit=18):
    name = name.strip()
    if not name:
        return []

    exact_cards = _search_tokens(f'!"{name}" type:token game:paper', limit * 3)
    if exact_cards:
        return _token_payloads(exact_cards, limit)

    cards = _search_tokens(f"{name} type:token game:paper", limit * 3)
    cards = _close_token_name_matches(cards, name)
    return _token_payloads(cards, limit)


def _search_tokens(query, limit):
    try:
        response = requests.get(
            f"{SCRYFALL}/cards/search",
            params={
                "q": query,
                "include_extras": "true",
                "unique": "prints",
                "order": "name",
            },
            timeout=20,
        )
        response.raise_for_status()
    except Exception:
        return []

    return response.json().get("data", [])[:limit]


def _token_payloads(cards, limit):
    tokens = []
    for card in cards[:limit * 3]:
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
                "set_name": card.get("set_name", ""),
                "set_code": card.get("set", "").upper(),
            }
        )
        if len(tokens) >= limit:
            break
    return tokens


def _close_token_name_matches(cards, query):
    names = {}
    query_key = query.casefold()
    for card in cards:
        token_name = card.get("name", "")
        if not token_name:
            continue
        name_key = token_name.casefold()
        score = SequenceMatcher(None, query_key, name_key).ratio()
        word_match = query_key in {part.casefold() for part in token_name.replace("//", " ").split()}
        if score >= 0.72 or word_match:
            names[name_key] = max(names.get(name_key, 0), score + (0.15 if word_match else 0))

    if not names:
        return []

    best_names = {
        name
        for name, _ in sorted(names.items(), key=lambda item: item[1], reverse=True)[:6]
    }
    return [card for card in cards if card.get("name", "").casefold() in best_names]


def token_signature(token):
    return (
        token.get("name", "").strip().lower(),
        token.get("power"),
        token.get("toughness"),
        tuple(token.get("colors", [])),
        (token.get("oracle_text") or "").strip().lower(),
    )


def dedupe_token_variants(matches):
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
