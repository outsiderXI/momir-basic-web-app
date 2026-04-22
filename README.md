# Momir Vig Printer Web App

A headless Raspberry Pi / Linux MTG thermal card printer that exposes a phone-friendly local web app.

## What it does

- Boot the Raspberry Pi and Epson receipt printer with no screen or keyboard required
- Wait for Wi-Fi / LAN connectivity
- Print the Pi's local web URL on the receipt printer
- Continue normal startup tasks such as refreshing the Scryfall database and caching images
- Serve a local web UI you can open from your phone, tablet, or laptop
- Print random creatures by mana value, tokens, and normal cards from the browser

## New web features

- Card image preview before printing
- Print again button
- Recent print history
- Token disambiguation cards instead of terminal prompts
- PWA support so you can install it to your phone's home screen
- Tap buttons for mana values 1-16
- Live startup and activity logs in the browser

## Hardware requirements

- Raspberry Pi with Wi-Fi
- Epson TM-T88V or compatible ESC/POS USB receipt printer
- USB connection between Pi and printer
- Internet connection for the first full cache build or future database refreshes
- Roughly 60 GB free storage if you want a large local image cache

## Main entry points

- `main.py` keeps the original terminal version intact
- `app.py` runs the new headless web app

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

- tap mana values `1` through `16` for Momir mode
- search token names like `rat` or `treasure`
- search normal cards like `Sol Ring`
- preview the image before printing
- choose the correct token when multiple variants exist
- reprint from recent history
- use the install prompt to add the app to your phone's home screen

## First startup behavior

The first startup may take a while. The app can:

1. Check internet availability
2. Check whether the Scryfall bulk data changed
3. Rebuild the SQLite search index if needed
4. Rebuild the token database if needed
5. Download missing card images
6. Download missing token images

The web UI shows the live startup log while this is happening.

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
- The browser UI uses cached assets and can be installed as a PWA, but printing still depends on the Pi and printer being online
- `print_image()` is wrapped with a lock in the web app so overlapping browser actions do not collide with the USB printer

## Project structure

- `app.py` - Flask web server and API
- `templates/index.html` - web UI
- `static/manifest.json` - PWA manifest
- `static/service-worker.js` - offline shell caching
- `deploy/momir-vig-web.service` - systemd startup service
- `printer.py` - image printing and receipt text printing
- `downloader.py` - database/image initialization and caching

## Original terminal mode still works

If you still want the original direct-on-Pi version:

```bash
python main.py
```
