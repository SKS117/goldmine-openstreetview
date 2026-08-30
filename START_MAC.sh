#!/usr/bin/env bash

cd "$(dirname "$0")" || exit 1

echo "================================================================"
echo "Mines de Costano - lokale Webansicht"
echo "================================================================"
echo

if command -v python3 >/dev/null 2>&1; then
    exec python3 start_server.py
fi

if command -v python >/dev/null 2>&1; then
    exec python start_server.py
fi

echo "FEHLER: Python 3 wurde auf diesem Mac nicht gefunden."
echo
echo "Bitte Python 3 von https://www.python.org/downloads/ installieren."
echo "Danach Terminal neu öffnen und erneut:"
echo
echo "    bash START_MAC.sh"
echo
exit 1
