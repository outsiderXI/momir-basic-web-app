import random
import sqlite3

from rapidfuzz import fuzz, process

from config import DB_FILE, IMAGE_DIR


def random_creature_by_cmc(cmc):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id
        FROM cards
        WHERE is_creature = 1 AND cmc = ?
        """,
        (cmc,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return None

    return random.choice(rows)[0]


def get_card_details(card_id):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, name, cmc, type_line
        FROM cards
        WHERE id = ?
        LIMIT 1
        """,
        (card_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def exact_card_row_by_name(name):
    """
    Return one preferred exact non-token printing automatically.

    Preference order:
    - exact English paper card
    - not promo
    - not full art
    - not textless
    - black border
    - normal modern frame
    - earliest release among normal printings
    """

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            id,
            name,
            cmc,
            type_line
        FROM cards
        WHERE name = ?
          AND is_token = 0
        ORDER BY
            CASE WHEN lang = 'en' THEN 0 ELSE 1 END,
            CASE WHEN promo = 0 THEN 0 ELSE 1 END,
            CASE WHEN full_art = 0 THEN 0 ELSE 1 END,
            CASE WHEN textless = 0 THEN 0 ELSE 1 END,
            CASE WHEN border_color = 'black' THEN 0 ELSE 1 END,
            CASE WHEN frame = '2015' THEN 0
                 WHEN frame = '2003' THEN 1
                 WHEN frame = '1997' THEN 2
                 ELSE 3
            END,
            CASE WHEN rarity = 'common' THEN 0
                 WHEN rarity = 'uncommon' THEN 1
                 WHEN rarity = 'rare' THEN 2
                 WHEN rarity = 'mythic' THEN 3
                 ELSE 4
            END,
            released_at ASC,
            set_code ASC,
            id ASC
        LIMIT 1
        """,
        (name,),
    )

    row = cur.fetchone()
    conn.close()
    return row


def exact_card_id_by_name(name):
    row = exact_card_row_by_name(name)
    return row[0] if row else None


def search_card_candidates(name, limit=20):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    prefix_query = " ".join(part + "*" for part in name.split() if part.strip())
    if prefix_query:
        cur.execute(
            """
            SELECT c.id, c.name, c.cmc, c.type_line
            FROM cards_fts f
            JOIN cards c ON c.id = f.id
            WHERE f.name MATCH ?
              AND c.is_token = 0
            LIMIT ?
            """,
            (prefix_query, limit),
        )
        fts_rows = cur.fetchall()
        if fts_rows:
            conn.close()
            return _decorate_candidates(fts_rows)

    cur.execute(
        """
        SELECT id, name, cmc, type_line
        FROM cards
        WHERE is_token = 0
        """
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        return []

    name_lookup = [r[1] for r in rows]
    fuzzy = process.extract(name, name_lookup, scorer=fuzz.WRatio, limit=limit)

    out = []
    used_names = set()

    for matched_name, score, _ in fuzzy:
        if score < 70 or matched_name in used_names:
            continue

        used_names.add(matched_name)
        preferred = exact_card_row_by_name(matched_name)
        if preferred:
            out.append(preferred)

    return _decorate_candidates(out)


def _decorate_candidates(rows):
    decorated = []
    for card_id, name, cmc, type_line in rows:
        cached = (IMAGE_DIR / f"{card_id}.jpg").exists()
        decorated.append(
            {
                "id": card_id,
                "name": name,
                "cmc": cmc,
                "type_line": type_line,
                "cached": cached,
            }
        )
    return decorated


def search_card(name):
    exact = exact_card_id_by_name(name)
    if exact:
        return exact

    candidates = search_card_candidates(name, limit=1)
    return candidates[0]["id"] if candidates else None


def cache_stats():
    image_count = len(list(IMAGE_DIR.glob("*.jpg")))
    image_size = sum(p.stat().st_size for p in IMAGE_DIR.glob("*.jpg") if p.is_file())
    return {
        "image_count": image_count,
        "image_size_bytes": image_size,
    }


def human_size(num_bytes):
    value = float(num_bytes)
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
        value /= 1024
