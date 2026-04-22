# Momir Vig Printer Web App

This version turns your Momir Vig thermal printer into a **headless Raspberry Pi web appliance**.

You can:

- plug in the Raspberry Pi and Epson receipt printer
- let the Pi join Wi‑Fi
- have the printer **print the local web address** automatically
- open that address on your **phone, tablet, or laptop**
- use the same Momir Vig workflow without needing a screen or keyboard on the Pi

---

## What this version does

On boot, the Raspberry Pi will:

1. start the local web server
2. wait for Wi‑Fi / network connectivity
3. detect its local IP address
4. print the web address through the Epson receipt printer
5. continue normal startup tasks like:
   - checking for Scryfall bulk updates
   - rebuilding the local SQLite database when needed
   - rebuilding token data when needed
   - downloading missing card images
   - downloading missing token images
6. expose a browser UI you can use from your phone or computer

Example printed receipt:

```text
Momir Vig Printer Web App
Open on your phone or laptop:
http://192.168.1.44:5000
```

---

## Web app features

The browser UI supports the same core flows as your current terminal version:

- **Momir mode:** enter `1` through `16` for a random creature by mana value
- **Token mode:** enter token names like `rat`, `treasure`, `soldier`
- **Card printing:** enter exact card names like `Sol Ring`
- **Smart matching:** if multiple matches exist, the web UI lets you choose the correct one
- **Multiple copies:** choose how many copies to print
- **Live startup log:** watch the Pi finish database and image cache work from your phone
- **ASCII Momir splash art:** shown in the web UI during startup and normal use

---

## Hardware requirements

- Raspberry Pi with Wi‑Fi
- Epson TM‑T88V or compatible ESC/POS USB receipt printer
- USB cable between Pi and printer
- internet access for initial syncs and updates
- roughly **60 GB free storage** for full image cache mode

---

## Python requirements

Install system packages first:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip libjpeg-dev zlib1g-dev libopenjp2-7 libtiff6 libusb-1.0-0-dev
```

Then create a virtual environment and install Python dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

## Project layout

Important files in this version:

- `app.py` — Flask web server and API
- `main.py` — original terminal version, still available
- `printer.py` — Epson USB printing helpers for images and text receipts
- `downloader.py` — Scryfall database/image startup work
- `templates/index.html` — mobile-friendly browser interface
- `deploy/momir-vig-web.service` — example systemd service file

---

## Running the web version manually

From the project folder:

```bash
source venv/bin/activate
python app.py
```

The app listens on:

```text
0.0.0.0:5000
```

As soon as the Pi has a non-loopback network address, it will print the URL on the Epson printer.

---

## Using it from your phone

1. power on the Pi and printer
2. wait for the printer to print the access URL
3. connect your phone or laptop to the same network
4. open the printed URL in a browser
5. wait for startup to finish if it is still rebuilding or caching
6. print cards from the web UI

---

## Setting it up as a boot service

Copy the included service file:

```bash
sudo cp deploy/momir-vig-web.service /etc/systemd/system/
```

Edit it if your username or install path is different:

```bash
sudo nano /etc/systemd/system/momir-vig-web.service
```

Make sure these paths match your system:

- `User=`
- `WorkingDirectory=`
- `ExecStart=`

Then enable it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable momir-vig-web.service
sudo systemctl start momir-vig-web.service
```

Check status:

```bash
sudo systemctl status momir-vig-web.service
```

View logs:

```bash
journalctl -u momir-vig-web.service -f
```

---

## Recommended Raspberry Pi network setup

For the smoothest experience, make sure your Pi can join Wi‑Fi automatically at boot.

If you want the address to stay predictable, reserve a DHCP lease for the Pi in your router.

That way the printed URL will usually stay the same.

---

## Printer behavior

The printer now does two different jobs:

1. **startup receipt printing** — prints the Pi’s local web address once networking is available
2. **card/token printing** — prints the selected Magic card or token image

A print lock is used so two browser taps do not collide with each other on the USB printer.

---

## Startup behavior notes

On first startup, the Pi may spend a long time doing these tasks:

- downloading the latest Scryfall bulk dataset
- rebuilding the local card database
- building the token database
- downloading missing card images
- downloading missing token images

The web UI shows a live log during this process.

Printing becomes available once startup finishes.

---

## Troubleshooting

### The receipt printer does not print the URL

Check:

- the printer is powered on
- USB is connected to the Pi
- vendor/product IDs in `config.py` match your printer
- the service is running
- the Pi actually joined Wi‑Fi

Check service logs:

```bash
journalctl -u momir-vig-web.service -f
```

### The web page loads but says it is still starting

That usually means the Pi is still:

- downloading the Scryfall dataset
- rebuilding the database
- caching card images

Wait for the startup log in the browser to reach **Ready**.

### The printer says resource busy

That usually means another print job or process still has the printer device open. Restart the app or service:

```bash
sudo systemctl restart momir-vig-web.service
```

### I want a different port

Change the `PORT` constant in `app.py`.

If you change the port, the printed receipt will automatically use the new port too.

---
