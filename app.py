import json
import logging
import socket
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory

from config import DATA_DIR, IMAGE_DIR
from downloader import download_card_image, ensure_card_image, initialize_database
from printer import print_image, print_text_receipt
from search import (
    exact_card_row_by_name,
    get_card_details,
    random_creature_by_cmc,
    search_card_candidates,
)
from tokens import (
    dedupe_token_variants,
    search_token_candidates_online,
)

APP_PORT = 5000
APP_HOST = "0.0.0.0"
MAX_HISTORY = 20
STATUS_FILE = DATA_DIR / "web_status.json"

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

state_lock = threading.Lock()
print_lock = threading.Lock()
startup_thread = None

state: dict[str, Any] = {
    "ready": False,
    "phase": "booting",
    "started_at": time.time(),
    "last_ip_printed": None,
    "logs": deque(maxlen=250),
    "history": deque(maxlen=MAX_HISTORY),
    "last_preview": None,
    "last_print": None,
    "token_options": {},
}


class WebLogHandler(logging.Handler):
    def emit(self, record):
        if record.name.startswith("werkzeug"):
            return
        append_log(self.format(record))


root_logger = logging.getLogger()
if not any(isinstance(h, WebLogHandler) for h in root_logger.handlers):
    handler = WebLogHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def append_log(message: str):
    with state_lock:
        state["logs"].append({"ts": time.strftime("%H:%M:%S"), "message": str(message)})
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(
            json.dumps(
                {
                    "ready": state["ready"],
                    "phase": state["phase"],
                    "last_log": message,
                    "updated_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass


def set_phase(phase: str, message: str | None = None):
    with state_lock:
        state["phase"] = phase
    if message:
        append_log(message)


def get_local_ip() -> str | None:
    for target in ("8.8.8.8", "1.1.1.1"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((target, 80))
            return sock.getsockname()[0]
        except Exception:
            pass
        finally:
            sock.close()

    try:
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return None


ASCII_BANNER = r"""
███╗   ███╗ ██████╗ ███╗   ███╗██╗██████╗
████╗ ████║██╔═══██╗████╗ ████║██║██╔══██╗
██╔████╔██║██║   ██║██╔████╔██║██║██████╔╝
██║╚██╔╝██║██║   ██║██║╚██╔╝██║██║██╔══██╗
██║ ╚═╝ ██║╚██████╔╝██║ ╚═╝ ██║██║██║  ██║
╚═╝     ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚═╝╚═╝  ╚═╝

██╗   ██╗██╗ ██████╗     ██████╗ ██████╗ ██╗███╗   ██╗████████╗███████╗██████╗
██║   ██║██║██╔════╝     ██╔══██╗██╔══██╗██║████╗  ██║╚══██╔══╝██╔════╝██╔══██╗
██║   ██║██║██║  ███╗    ██████╔╝██████╔╝██║██╔██╗ ██║   ██║   █████╗  ██████╔╝
╚██╗ ██╔╝██║██║   ██║    ██╔═══╝ ██╔══██╗██║██║╚██╗██║   ██║   ██╔══╝  ██╔══██╗
 ╚████╔╝ ██║╚██████╔╝    ██║     ██║  ██║██║██║ ╚████║   ██║   ███████╗██║  ██║
  ╚═══╝  ╚═╝ ╚═════╝     ╚═╝     ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚═╝  ╚═╝
""".strip("\n")


def _card_image_url(card_id: str) -> str | None:
    path = IMAGE_DIR / f"{card_id}.jpg"
    if path.exists():
        return f"/images/{path.name}"
    return None


def build_card_preview(card_id: str):
    path = ensure_card_image(card_id)
    if not path:
        return None

    details = get_card_details(card_id)
    if not details:
        return None

    cid, name, cmc, type_line = details
    return {
        "kind": "card",
        "id": cid,
        "name": name,
        "cmc": cmc,
        "type_line": type_line,
        "image_url": f"/images/{Path(path).name}",
        "copies": 1,
    }


def color_text(colors: list[str] | tuple[str, ...] | None) -> str:
    ordered = "WUBRG"
    return "".join(color for color in ordered if color in set(colors or [])) or "Colorless"


def token_option_payload(token: dict[str, Any]):
    image_name = Path(token.get("local_image") or f"{token['id']}.jpg").name
    return {
        "kind": "token",
        "id": token["id"],
        "name": token["name"],
        "type_line": "Token",
        "pt": f"{token.get('power') or '?'}/{token.get('toughness') or '?'}",
        "colors": token.get("colors", []),
        "color_text": color_text(token.get("colors", [])),
        "oracle_text": token.get("oracle_text") or "",
        "image_url": f"/images/{image_name}",
        "source_image": token.get("image"),
        "set_codes": token.get("_set_codes", []),
        "variant_count": token.get("_variant_count", 1),
        "copies": 1,
    }


def build_token_matches(name: str, pt: str = "", colors: str = ""):
    matches = search_token_candidates_online(name)
    matches = dedupe_token_variants(matches)

    output = []
    for token in matches[:18]:
        output.append(token_option_payload(token))
    with state_lock:
        state["token_options"] = {item["id"]: item for item in output}
    return output


def add_history(item: dict[str, Any]):
    history_item = dict(item)
    history_item["printed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with state_lock:
        state["history"].appendleft(history_item)
        state["last_print"] = history_item


def print_preview_item(preview: dict[str, Any], copies: int):
    successes = 0
    with print_lock:
        for _ in range(copies):
            if print_image(preview["id"]):
                successes += 1
            else:
                break

    if successes == 0:
        return None

    history_payload = dict(preview)
    history_payload["copies"] = successes
    add_history(history_payload)
    append_log(f"Printed {preview['name']} x{successes}")
    return history_payload


def wait_for_network_and_print_url():
    last_printed = None
    while True:
        ip = get_local_ip()
        if ip and ip != last_printed:
            url = f"http://{ip}:{APP_PORT}"
            append_log(f"Network ready at {url}")
            print_text_receipt([
                "Momir Vig Web UI Ready",
                url,
                "Open on phone or laptop",
            ])
            with state_lock:
                state["last_ip_printed"] = url
            return
        append_log("Waiting for Wi-Fi / local network...")
        time.sleep(5)


@app.route("/")
def index():
    return render_template("index.html", ascii_banner=ASCII_BANNER)


@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json", mimetype="application/manifest+json")


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory("static", "service-worker.js", mimetype="application/javascript")


@app.route("/images/<path:filename>")
def images(filename: str):
    return send_from_directory(IMAGE_DIR, filename)


@app.get("/api/status")
def api_status():
    with state_lock:
        payload = {
            "ready": state["ready"],
            "phase": state["phase"],
            "logs": list(state["logs"]),
            "history": list(state["history"]),
            "last_preview": state["last_preview"],
            "last_print": state["last_print"],
            "last_ip_printed": state["last_ip_printed"],
        }
    return jsonify(payload)


@app.post("/api/preview")
def api_preview():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    copies = max(1, min(20, int(data.get("copies", 1) or 1)))

    if not query:
        return jsonify({"ok": False, "error": "Enter a mana value, token name, or card name."}), 400

    result = None
    token_options = []

    if query.isdigit() and 1 <= int(query) <= 16:
        card_id = random_creature_by_cmc(int(query))
        if not card_id:
            return jsonify({"ok": False, "error": f"No creature found for mana value {query}."}), 404
        result = build_card_preview(card_id)
        if result:
            result["source"] = f"Random creature with mana value {query}"
    else:
        token_options = build_token_matches(query)
        if len(token_options) == 1:
            result = token_options[0]
            token_options = []
        elif len(token_options) > 1:
            with state_lock:
                state["last_preview"] = None
            return jsonify({
                "ok": True,
                "mode": "token_options",
                "options": token_options,
                "message": f"Found {len(token_options)} token options for '{query}'.",
            })
        else:
            exact = exact_card_row_by_name(query)
            if exact:
                result = build_card_preview(exact[0])
            if not result:
                candidates = search_card_candidates(query, limit=8)
                if not candidates:
                    return jsonify({"ok": False, "error": f"No card or token found for '{query}'."}), 404
                result = build_card_preview(candidates[0]["id"])
                if result:
                    result["source"] = f"Closest match: {candidates[0]['name']}"

    if not result:
        return jsonify({"ok": False, "error": "Unable to build preview."}), 500

    result["copies"] = copies
    with state_lock:
        state["last_preview"] = result
    return jsonify({"ok": True, "mode": result["kind"], "preview": result})


@app.post("/api/token-options")
def api_token_options():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    pt = str(data.get("pt", "")).strip()
    colors = str(data.get("colors", "")).strip()
    options = build_token_matches(query, pt=pt, colors=colors)
    return jsonify({"ok": True, "options": options})


@app.post("/api/card-options")
def api_card_options():
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    if not query:
        return jsonify({"ok": False, "error": "Enter a card name."}), 400

    options = []
    exact = exact_card_row_by_name(query)
    if exact:
        card_id, name, cmc, type_line = exact
        options.append(
            {
                "id": card_id,
                "name": name,
                "cmc": cmc,
                "type_line": type_line,
                "exact": True,
            }
        )

    seen = {option["id"] for option in options}
    for candidate in search_card_candidates(query, limit=10):
        if candidate["id"] in seen:
            continue
        options.append(
            {
                "id": candidate["id"],
                "name": candidate["name"],
                "cmc": candidate["cmc"],
                "type_line": candidate["type_line"],
                "exact": False,
            }
        )
        seen.add(candidate["id"])

    if not options:
        return jsonify({"ok": False, "error": f"No cards found for '{query}'."}), 404

    return jsonify({"ok": True, "options": options})


@app.post("/api/momir-print")
def api_momir_print():
    data = request.get_json(silent=True) or {}
    cmc = int(data.get("cmc", 0) or 0)
    if not 1 <= cmc <= 16:
        return jsonify({"ok": False, "error": "Choose a mana value from 1 to 16."}), 400

    card_id = random_creature_by_cmc(cmc)
    if not card_id:
        return jsonify({"ok": False, "error": f"No creature found for mana value {cmc}."}), 404

    preview = build_card_preview(card_id)
    if not preview:
        return jsonify({"ok": False, "error": "Unable to download the creature image."}), 500
    preview["source"] = f"Random creature with mana value {cmc}"

    printed = print_preview_item(preview, 1)
    if not printed:
        return jsonify({"ok": False, "error": "Printer job failed."}), 500

    with state_lock:
        history = list(state["history"])
    return jsonify({"ok": True, "printed": 1, "item": printed, "history": history})


@app.post("/api/select-token")
def api_select_token():
    data = request.get_json(silent=True) or {}
    token_id = str(data.get("token_id", "")).strip()
    copies = max(1, min(20, int(data.get("copies", 1) or 1)))
    if not token_id:
        return jsonify({"ok": False, "error": "Missing token id."}), 400

    with state_lock:
        cached_option = state["token_options"].get(token_id)
    if not cached_option:
        return jsonify({"ok": False, "error": "Token not found."}), 404

    preview = dict(cached_option)
    local = ensure_card_image(token_id)
    if not local and preview.get("source_image"):
        try:
            local = download_card_image(token_id, preview["source_image"])
        except Exception:
            local = None
    if not local:
        return jsonify({"ok": False, "error": "Token image could not be downloaded."}), 404
    preview["image_url"] = f"/images/{Path(local).name}"
    preview["copies"] = copies
    with state_lock:
        state["last_preview"] = preview
    return jsonify({"ok": True, "preview": preview})


@app.post("/api/print-token")
def api_print_token():
    data = request.get_json(silent=True) or {}
    token_id = str(data.get("token_id", "")).strip()
    copies = max(1, min(20, int(data.get("copies", 1) or 1)))
    if not token_id:
        return jsonify({"ok": False, "error": "Missing token id."}), 400

    with state_lock:
        cached_option = state["token_options"].get(token_id)
    if cached_option:
        preview = dict(cached_option)
        local = ensure_card_image(token_id)
        if not local and preview.get("source_image"):
            try:
                local = download_card_image(token_id, preview["source_image"])
            except Exception:
                local = None
        if not local:
            return jsonify({"ok": False, "error": "Token image could not be downloaded."}), 404
        preview["image_url"] = f"/images/{Path(local).name}"
    else:
        return jsonify({"ok": False, "error": "Token not found. Search and choose a token first."}), 404

    preview["copies"] = copies
    printed = print_preview_item(preview, copies)
    if not printed:
        return jsonify({"ok": False, "error": "Printer job failed."}), 500

    with state_lock:
        history = list(state["history"])
    return jsonify({"ok": True, "printed": printed["copies"], "item": printed, "history": history})


@app.post("/api/print-card")
def api_print_card():
    data = request.get_json(silent=True) or {}
    card_id = str(data.get("card_id", "")).strip()
    copies = max(1, min(20, int(data.get("copies", 1) or 1)))
    if not card_id:
        return jsonify({"ok": False, "error": "Missing card id."}), 400

    preview = build_card_preview(card_id)
    if not preview:
        return jsonify({"ok": False, "error": "Card image could not be downloaded."}), 404
    preview["copies"] = copies

    printed = print_preview_item(preview, copies)
    if not printed:
        return jsonify({"ok": False, "error": "Printer job failed."}), 500

    with state_lock:
        history = list(state["history"])
    return jsonify({"ok": True, "printed": printed["copies"], "item": printed, "history": history})


@app.post("/api/print")
def api_print():
    data = request.get_json(silent=True) or {}
    preview = data.get("preview")
    if not preview:
        with state_lock:
            preview = state["last_preview"]
    if not preview:
        return jsonify({"ok": False, "error": "Nothing selected to print."}), 400

    copies = max(1, min(20, int(data.get("copies", preview.get("copies", 1)) or 1)))
    printed = print_preview_item(preview, copies)
    if not printed:
        return jsonify({"ok": False, "error": "Printer job failed."}), 500

    return jsonify({"ok": True, "printed": printed["copies"], "item": printed})


@app.post("/api/print-again")
def api_print_again():
    with state_lock:
        last_print = state["last_print"]
    if not last_print:
        return jsonify({"ok": False, "error": "Nothing has been printed yet."}), 400

    successes = 0
    with print_lock:
        if print_image(last_print["id"]):
            successes = 1

    if successes == 0:
        return jsonify({"ok": False, "error": "Printer job failed."}), 500

    history_payload = dict(last_print)
    history_payload["copies"] = 1
    add_history(history_payload)
    append_log(f"Printed again: {last_print['name']}")
    return jsonify({"ok": True, "printed": 1, "item": history_payload})


@app.post("/api/history-preview")
def api_history_preview():
    data = request.get_json(silent=True) or {}
    item_id = str(data.get("id", "")).strip()
    item_kind = str(data.get("kind", "card")).strip()
    if not item_id:
        return jsonify({"ok": False, "error": "Missing history item id."}), 400

    if item_kind == "token":
        with state_lock:
            token = state["token_options"].get(item_id)
        if not token:
            return jsonify({"ok": False, "error": "Token not found."}), 404
        preview = dict(token)
        with state_lock:
            state["last_preview"] = preview
        return jsonify({"ok": True, "preview": preview})

    preview = build_card_preview(item_id)
    if not preview:
        return jsonify({"ok": False, "error": "Card preview unavailable."}), 404
    with state_lock:
        state["last_preview"] = preview
    return jsonify({"ok": True, "preview": preview})


def startup_worker():
    set_phase("network", "Starting Momir Vig web appliance...")
    wait_for_network_and_print_url()
    set_phase("initializing", "Checking internet availability...")
    initialize_database(log_callback=append_log)
    set_phase("ready", "System ready. Awaiting print commands.")
    with state_lock:
        state["ready"] = True


@app.post("/api/restart-startup")
def api_restart_startup():
    global startup_thread
    if startup_thread and startup_thread.is_alive():
        return jsonify({"ok": False, "error": "Startup tasks are already running."}), 409
    startup_thread = threading.Thread(target=startup_worker, daemon=True)
    startup_thread.start()
    return jsonify({"ok": True})


def ensure_startup_thread():
    global startup_thread
    if startup_thread is None or not startup_thread.is_alive():
        startup_thread = threading.Thread(target=startup_worker, daemon=True)
        startup_thread.start()


if __name__ == "__main__":
    ensure_startup_thread()
    app.run(host=APP_HOST, port=APP_PORT, debug=False, threaded=True)
