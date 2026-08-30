# Georeferenzierung prüfen

Die automatische Nominatim-Geokodierung ist **kein fertiges Forschungsergebnis**.

Für jeden Datensatz solltest du mindestens prüfen:

1. Passt Ort/Stadt/Land zur historischen Quellenangabe?
2. Wurde wirklich die richtige Strasse gefunden?
3. Ist die Hausnummer plausibel?
4. Handelt es sich nur um einen Ortsmittelpunkt?
5. Ist die historische Adresse heute noch identisch?
6. Soll der Treffer als `exact_address`, `locality` oder `unresolved` klassifiziert werden?

## Empfohlener Workflow

Nach `python tools/geocode.py` steht in `data/geocoded.json` ein automatisch
ermittelter Kandidat.

Wenn du einen Treffer geprüft hast, übernimm seine Koordinaten in
`data/geocoding-overrides.json`:

```json
{
  "DOKUMENT::NUMMER": {
    "query": "112 Boulevard Exelmans, 75016 Paris, France",
    "lat": 48.000000,
    "lon": 2.000000,
    "quality": "exact_address",
    "note": "Manuell anhand OpenStreetMap geprüft."
  }
}
```

Danach `python tools/geocode.py` erneut ausführen. Manuell eingetragene
Koordinaten werden nicht erneut bei Nominatim gesucht.

So bleibt nachvollziehbar:

**Quelle → Transkription → Normalisierung → Geokodierung → Prüfung → Visualisierung**
