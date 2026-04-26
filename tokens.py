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
                "set_name": card.get("set_name", ""),
                "set_code": card.get("set", "").upper(),
            }
        )
        if len(tokens) >= limit:
            break
    return tokens


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
