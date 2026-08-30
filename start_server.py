#!/usr/bin/env python3
"""
Lokaler Server für die Seminararbeits-Webseite.

Keine externen Python-Pakete nötig.

Windows:
    py start_server.py

macOS:
    python3 start_server.py

Die IIIF-Dateien dieses Projekts verwenden localhost:8000 als Service-ID.
Deshalb läuft der Server bewusst immer auf Port 8000.
"""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import sys
import threading
import webbrowser


ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8000
URL = f"http://localhost:{PORT}/"

REQUIRED_PATHS = (
    "index.html",
    "app.js",
    "style.css",
    "data/site-data.json",
    "iiif",
)


class SubmissionHandler(SimpleHTTPRequestHandler):
    """
    Einfacher statischer HTTP-Handler.

    Cache-Control verhindert vor allem bei der Begutachtung, dass ältere
    JavaScript-/CSS-Versionen aus dem Browsercache angezeigt werden.
    """

    def end_headers(self) -> None:
        self.send_header(
            "Cache-Control",
            "no-store, no-cache, must-revalidate, max-age=0",
        )
        self.send_header(
            "Pragma",
            "no-cache",
        )
        super().end_headers()


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = True


def validate_repository() -> list[str]:
    missing = []

    for relative in REQUIRED_PATHS:
        if not (ROOT / relative).exists():
            missing.append(relative)

    return missing


def port_is_available() -> bool:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        try:
            sock.bind(
                (HOST, PORT)
            )
        except OSError:
            return False

    return True


def print_header() -> None:
    print()
    print("=" * 72)
    print("MINES DE COSTANO – LOKALE WEBANSICHT")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Startet die statische Forschungswebseite lokal auf "
            "http://localhost:8000/"
        )
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="Prüft nur, ob die wichtigsten Dateien vorhanden sind.",
    )

    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Öffnet den Browser nicht automatisch.",
    )

    args = parser.parse_args()

    print_header()

    missing = validate_repository()

    if missing:
        print("FEHLER: Das Repository scheint unvollständig zu sein.")
        print()
        print("Folgende Dateien/Ordner fehlen:")

        for item in missing:
            print(f"  - {item}")

        print()
        print(
            "Bitte das GitHub-ZIP vollständig entpacken und "
            "start_server.py aus dem Projekt-Hauptordner starten."
        )

        return 2

    print("Repository-Prüfung: OK")

    if args.check:
        print("Die wichtigsten Dateien sind vorhanden.")
        return 0

    if not port_is_available():
        print()
        print("FEHLER: Port 8000 wird bereits verwendet.")
        print()
        print(
            "Möglicherweise läuft bereits ein anderer lokaler Server. "
            "Schliesse das entsprechende Terminalfenster bzw. stoppe den "
            "anderen Server mit Ctrl+C und starte dieses Skript danach erneut."
        )
        print()
        print(
            "Warum Port 8000 fest ist: Die statischen IIIF-info.json-Dateien "
            "verwenden http://localhost:8000/iiif/... als Service-ID."
        )

        return 3

    os.chdir(ROOT)

    try:
        server = LocalServer(
            (HOST, PORT),
            SubmissionHandler,
        )
    except OSError as error:
        print(
            f"Server konnte nicht gestartet werden: {error}"
        )
        return 4

    print()
    print(f"Website: {URL}")
    print()
    print("Der Browser wird gleich automatisch geöffnet.")
    print("Dieses Fenster offen lassen, solange die Website benutzt wird.")
    print("Zum Beenden: Ctrl+C")
    print()

    if not args.no_browser:
        timer = threading.Timer(
            0.8,
            lambda: webbrowser.open(URL),
        )
        timer.daemon = True
        timer.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
        print("Server beendet.")
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
