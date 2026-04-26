# Momir Vig Printer Web App

A headless Raspberry Pi / Linux MTG thermal card printer that exposes a phone-friendly local web app.

## What it does

- Boot the Raspberry Pi and Epson receipt printer with no screen or keyboard required
- Wait for Wi-Fi / LAN connectivity
- Print the Pi's local web URL on the receipt printer
- Continue normal startup tasks such as checking internet availability
- Serve a local web UI you can open from your phone, tablet, or laptop
- Print random creatures by mana value, tokens, and normal cards from the browser

## Web features

- Recent print history
- Immediate Momir Basic printing from mana value buttons
- Token disambiguation cards with color, power/toughness, and rules text
- Similar-name options for normal card printing
- PWA support so you can install it to your phone's home screen

## Hardware requirements

- Raspberry Pi with Wi-Fi
- Epson TM-T88V or compatible ESC/POS USB receipt printer
- USB connection between Pi and printer
- Internet connection for card and token lookups

## Main Entry Point

- `app.py` runs the headless web app

## Install

```bash
git clone https://github.com/outsiderXI/Momir-Vig-Printer.git
cd Momir-Vig-Printer
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run the web app manually

```bash
source venv/bin/activate
python app.py
```

When the Pi gets on the network, the Epson printer will print something like:

```text
Momir Vig Web UI Ready
http://192.168.1.42:5000
Open on phone or laptop
```

Open that address from your phone or laptop while connected to the same network.

## Web app usage

You can:

- tap mana values `1` through `16` to immediately print a random creature
- search token names like `rat` or `treasure`
- choose the correct token when multiple variants exist, then choose copies
- search normal cards like `Sol Ring`, choose the closest match, then choose copies
- use the install prompt to add the app to your phone's home screen

## Startup behavior

Startup is intentionally lightweight so it can run comfortably as a headless Raspberry Pi appliance. The app:

1. Check internet availability
2. Print the local web URL when the Pi has a network address
3. Use live Scryfall lookups for Momir, token, and card searches
4. Cache only the individual images that are printed

The web UI stays focused on the three print workflows and recent print history.

## Set it to launch automatically on boot

Copy the included service file:

```bash
sudo cp deploy/momir-vig-web.service /etc/systemd/system/
```

Edit it if needed:

```bash
sudo nano /etc/systemd/system/momir-vig-web.service
```

Make sure these values match your system:

- `User=pi`
- `WorkingDirectory=/home/pi/Momir-Vig-Printer`
- `ExecStart=/home/pi/Momir-Vig-Printer/venv/bin/python /home/pi/Momir-Vig-Printer/app.py`

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable momir-vig-web.service
sudo systemctl start momir-vig-web.service
```

Check status:

```bash
systemctl status momir-vig-web.service
journalctl -u momir-vig-web.service -f
```

## Notes

- The web app listens on port `5000` by default
- Your phone or laptop must be on the same local network as the Pi
- The browser UI uses cached app assets and can be installed as a PWA, but card/token lookups and printing still depend on the Pi, internet, and printer being online
- `print_image()` is wrapped with a lock in the web app so overlapping browser actions do not collide with the USB printer

## Project structure

- `app.py` - Flask web server and API
- `config.py` - app, printer, and image sizing settings
- `templates/index.html` - web UI
- `static/manifest.json` - PWA manifest
- `static/service-worker.js` - offline shell caching
- `deploy/momir-vig-web.service` - systemd startup service
- `printer.py` - image printing and receipt text printing
- `downloader.py` - internet readiness and on-demand image caching
- `search.py` - live Scryfall card lookups
- `tokens.py` - live Scryfall token lookups and token deduping
