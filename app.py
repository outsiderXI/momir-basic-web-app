import json
import socket
import threading
import time
from collections import deque
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from downloader import ensure_card_image, initialize_database
from printer import print_image, print_text
from search import (
    cache_stats,
    exact_card_row_by_name,
    get_card_details,
    human_size,
    random_creature_by_cmc,
    search_card_candidates,
)
from splash import BOOT_LINES, MOMIR_QUOTES, generate_ascii_art
from tokens import dedupe_token_variants, extract_keywords, filter_color, filter_pt, load_tokens, smart_match

PORT = 5000
MAX_LOG_LINES = 250

app = Flask(__name__)


class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.logs = deque(maxlen=MAX_LOG_LINES)
        self.ready = False
        self.startup_complete = False
        self.startup_error = None
        self.current_step = "Booting"
        self.action_status = "Starting up..."
        self.print_busy = False
        self.server_url = None
        self.last_action = None

    def log(self, message):
        with self.lock:
            self.logs.append({"ts": time.strftime("%H:%M:%S"), "message": message})
            self.current_step = message

    def snapshot(self):
        with self.lock:
            stats = cache_stats() if Path("data/cards.db").exists() else {"image_count": 0, "image_size_bytes": 0}
            return {
                "ready": self.ready,
                "startup_complete": self.startup_complete,
                "startup_error": self.startup_error,
                "current_step": self.current_step,
                "action_status": self.action_status,
                "print_busy": self.print_busy,
                "server_url": self.server_url,
                "last_action": self.last_action,
                "logs": list(self.logs),
                "cache": {
                    "image_count": stats["image_count"],
                    "image_size": human_size(stats["image_size_bytes"]),
                },
            }


state = AppState()


ASCII_ART = "\n".join(generate_ascii_art(max_width=72))


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for _, _, addresses in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = addresses[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass

    return None


def wait_for_network_and_print_address():
    state.log("Waiting for Wi-Fi / network...")
    while True:
        ip = get_local_ip()
        if ip:
            url = f"http://{ip}:{PORT}"
            with state.lock:
                state.server_url = url
            receipt = (
                "Momir Vig Printer Web App\n"
                f"Open on your phone or laptop:\n{url}\n"
            )
            print_text(receipt)
            state.log(f"Web server address printed: {url}")
            return
        time.sleep(3)


def startup_worker():
    try:
        state.log("Initializing biomantic matrix...")
        for line in BOOT_LINES:
            state.log(line)
            time.sleep(0.2)
        state.log(MOMIR_QUOTES[int(time.time()) % len(MOMIR_QUOTES)])
        initialize_database(log=state.log, progress_mode="plain")
        with state.lock:
            state.ready = True
            state.startup_complete = True
            state.action_status = "Ready to print."
            state.current_step = "Ready"
        state.log("Momir Vig web app is ready.")
    except Exception as exc:
        with state.lock:
            state.startup_complete = True
            state.startup_error = str(exc)
            state.action_status = f"Startup failed: {exc}"
            state.current_step = "Startup failed"
        state.log(f"Startup failed: {exc}")


def with_print_lock(action_name, func):
    with state.lock:
        if not state.ready:
            return False, {"ok": False, "message": "Printer is still starting up."}, 409
        if state.print_busy:
            return False, {"ok": False, "message": "Printer is busy with another job."}, 409
        state.print_busy = True
        state.action_status = action_name
        state.last_action = action_name

    try:
        result = func()
        return True, result, 200
    except Exception as exc:
        state.log(f"Action failed: {exc}")
        return False, {"ok": False, "message": str(exc)}, 500
    finally:
        with state.lock:
            state.print_busy = False
            if state.ready:
                state.action_status = "Ready to print."


def token_candidates(name, pt=None, colors=None):
    tokens = load_tokens()
    if not tokens:
        return []

    matches = smart_match(tokens, name)
    if not matches:
        return []

    if pt:
        filtered = filter_pt(matches, pt)
        if filtered:
            matches = filtered

    matches = dedupe_token_variants(matches)

    if colors:
        filtered = filter_color(matches, colors.strip().lower())
        if filtered:
            matches = filtered

    results = []
    for token in matches[:12]:
        results.append(
            {
                "id": token["id"],
                "name": token["name"],
                "pt": f"{token.get('power', '?')}/{token.get('toughness', '?')}",
                "colors": "".join(token.get("colors", [])) or "Colorless",
                "abilities": extract_keywords(token),
                "local_image": token.get("local_image"),
                "set_codes": token.get("_set_codes", []),
            }
        )
    return results


def resolve_query(query, pt=None, colors=None):
    raw = (query or "").strip()
    if not raw:
        return {"mode": "error", "message": "Enter a mana value, token name, or card name."}

    if raw.isdigit():
        cmc = int(raw)
        if 1 <= cmc <= 16:
            return {"mode": "cmc", "cmc": cmc}

    tokens = token_candidates(raw, pt=pt, colors=colors)
    if len(tokens) == 1:
        return {"mode": "token_exact", "token": tokens[0]}
    if len(tokens) > 1:
        return {"mode": "token_choose", "tokens": tokens}

    exact = exact_card_row_by_name(raw)
    if exact:
        card_id, card_name, cmc, type_line = exact
        return {
            "mode": "card_exact",
            "card": {"id": card_id, "name": card_name, "cmc": cmc, "type_line": type_line},
        }

    cards = search_card_candidates(raw, limit=10)
    if len(cards) == 1:
        return {"mode": "card_exact", "card": cards[0]}
    if cards:
        return {"mode": "card_choose", "cards": cards}

    return {"mode": "error", "message": "No token or card match found."}


@app.get("/")
def index():
    return render_template("index.html", ascii_art=ASCII_ART, port=PORT)


@app.get("/api/state")
def api_state():
    return jsonify(state.snapshot())


@app.post("/api/submit")
def api_submit():
    payload = request.get_json(silent=True) or {}
    query = payload.get("query", "")
    pt = payload.get("pt", "")
    colors = payload.get("colors", "")
    copies = max(1, min(int(payload.get("copies", 1) or 1), 20))

    resolved = resolve_query(query, pt=pt, colors=colors)

    if resolved["mode"] == "cmc":
        cmc = resolved["cmc"]

        def _print_random():
            card_id = random_creature_by_cmc(cmc)
            if not card_id:
                return {"ok": False, "message": f"No creature found with mana value {cmc}."}
            details = get_card_details(card_id)
            if not details:
                return {"ok": False, "message": "Card details not found."}
            _, name, card_cmc, type_line = details
            path = ensure_card_image(card_id)
            if not path:
                return {"ok": False, "message": "Creature image missing and could not be downloaded."}
            if not print_image(card_id):
                return {"ok": False, "message": "Printer error while printing the creature."}
            state.log(f"Printed random creature {name} (MV {card_cmc}).")
            return {
                "ok": True,
                "message": f"Printed random creature: {name}",
                "printed": {"id": card_id, "name": name, "cmc": card_cmc, "type_line": type_line},
            }

        _, response, status = with_print_lock(f"Printing random creature with mana value {cmc}...", _print_random)
        return jsonify(response), status

    if resolved["mode"] == "token_exact":
        token = resolved["token"]
        return jsonify({"ok": True, "needs_choice": False, "mode": "token", "token": token, "copies": copies})

    if resolved["mode"] == "token_choose":
        return jsonify({"ok": True, "needs_choice": True, "mode": "token", "tokens": resolved["tokens"], "copies": copies})

    if resolved["mode"] == "card_exact":
        return jsonify({"ok": True, "needs_choice": False, "mode": "card", "card": resolved["card"], "copies": copies})

    if resolved["mode"] == "card_choose":
        return jsonify({"ok": True, "needs_choice": True, "mode": "card", "cards": resolved["cards"], "copies": copies})

    return jsonify({"ok": False, "message": resolved["message"]}), 404


@app.post("/api/print-card")
def api_print_card():
    payload = request.get_json(silent=True) or {}
    card_id = payload.get("card_id")
    copies = max(1, min(int(payload.get("copies", 1) or 1), 20))

    if not card_id:
        return jsonify({"ok": False, "message": "card_id is required."}), 400

    def _do_print():
        details = get_card_details(card_id)
        if not details:
            return {"ok": False, "message": "Card details not found."}
        _, name, cmc, type_line = details
        path = ensure_card_image(card_id)
        if not path:
            return {"ok": False, "message": "Card image missing and could not be downloaded."}
        for _ in range(copies):
            if not print_image(card_id):
                return {"ok": False, "message": f"Printer error while printing {name}."}
        state.log(f"Printed {copies}x {name}.")
        return {
            "ok": True,
            "message": f"Printed {copies}x {name}.",
            "printed": {"id": card_id, "name": name, "cmc": cmc, "type_line": type_line},
        }

    _, response, status = with_print_lock(f"Printing card x{copies}...", _do_print)
    return jsonify(response), status


@app.post("/api/print-token")
def api_print_token():
    payload = request.get_json(silent=True) or {}
    token_id = payload.get("token_id")
    copies = max(1, min(int(payload.get("copies", 1) or 1), 20))

    if not token_id:
        return jsonify({"ok": False, "message": "token_id is required."}), 400

    tokens = load_tokens()
    token = next((t for t in tokens if t.get("id") == token_id), None)
    if not token:
        return jsonify({"ok": False, "message": "Token not found."}), 404

    def _do_print():
        local_image = token.get("local_image") or ensure_card_image(token_id)
        if not local_image:
            return {"ok": False, "message": "Token image missing and could not be downloaded."}
        for _ in range(copies):
            if not print_image(local_image):
                return {"ok": False, "message": f"Printer error while printing {token['name']}."}
        state.log(f"Printed {copies}x token {token['name']}.")
        return {"ok": True, "message": f"Printed {copies}x {token['name']}."}

    _, response, status = with_print_lock(f"Printing token x{copies}...", _do_print)
    return jsonify(response), status


@app.get("/api/search")
def api_search():
    query = request.args.get("q", "")
    pt = request.args.get("pt", "")
    colors = request.args.get("colors", "")
    return jsonify(resolve_query(query, pt=pt, colors=colors))


if __name__ == "__main__":
    state.log("Booting Momir Vig web app...")
    threading.Thread(target=wait_for_network_and_print_address, daemon=True).start()
    threading.Thread(target=startup_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
