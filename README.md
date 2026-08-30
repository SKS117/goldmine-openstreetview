# Mines de Costano – digitale Forschungsumgebung

Dieses Repository enthält die digitale Webpräsentation des Forschungsprojekts zu den Generalversammlungen und Aktionär*innen der Mines de Costano.

Die Website verbindet:

- historische Originalquellen,
- strukturierte JSON-Daten,
- normalisierte Forschungsdaten aus nodegoat,
- historische Wohnorte,
- IIIF-Bildansichten,
- Karten,
- Personen- und Firmenprofile,
- sowie Visualisierungen zur Entwicklung der Aktienverhältnisse.

## Wichtig: So starten Sie die Website

**Bitte `index.html` nicht direkt per Doppelklick öffnen.**

Die Website lädt JSON- und IIIF-Dateien über HTTP. Deshalb muss der Ordner über einen kleinen lokalen Webserver geöffnet werden.

Zum reinen Betrachten der Website müssen **keine Daten neu erzeugt werden**. Sie benötigen insbesondere:

- keinen nodegoat-Zugang,
- keinen API-Token,
- kein libvips,
- keine zusätzlichen Python-Pakete.

Benötigt wird lediglich **Python 3**.

---

# Schnellstart unter Windows

## 1. Repository herunterladen

Auf GitHub:

**Code → Download ZIP**

Danach die ZIP-Datei vollständig entpacken.

Nicht direkt innerhalb der ZIP-Datei arbeiten.

## 2. Website starten

Im entpackten Ordner doppelklicken auf:

```text
START_WINDOWS.bat
```

Das Skript sucht automatisch nach Python 3 und startet anschliessend die Website.

Der Browser sollte sich nach kurzer Zeit automatisch öffnen unter:

```text
http://localhost:8000/
```

Das schwarze Terminal-/PowerShell-Fenster muss geöffnet bleiben, solange die Website benutzt wird.

## 3. Website beenden

Im Terminalfenster:

```text
Ctrl + C
```

drücken.

Danach kann das Fenster geschlossen werden.

---

# Schnellstart unter macOS

## 1. Repository herunterladen

Auf GitHub:

**Code → Download ZIP**

Danach die ZIP-Datei vollständig entpacken.

## 2. Terminal öffnen

Öffnen Sie die App **Terminal**.

Geben Sie ein:

```bash
cd 
```

Wichtig: Nach `cd` befindet sich ein Leerzeichen.

Ziehen Sie nun den entpackten Repository-Ordner aus dem Finder direkt in das Terminalfenster.

Der vollständige Pfad wird automatisch eingefügt.

Drücken Sie **Enter**.

## 3. Website starten

Geben Sie ein:

```bash
bash START_MAC.sh
```

Der Browser sollte sich nach kurzer Zeit automatisch öffnen unter:

```text
http://localhost:8000/
```

Das Terminalfenster muss geöffnet bleiben, solange die Website benutzt wird.

## 4. Website beenden

Im Terminal:

```text
Control + C
```

drücken.

---

# Falls Python 3 nicht installiert ist

Prüfen:

Windows:

```powershell
py --version
```

macOS:

```bash
python3 --version
```

Wenn keine Python-3-Version angezeigt wird, installieren Sie Python 3 von:

https://www.python.org/downloads/

Danach das Terminal beziehungsweise PowerShell vollständig schliessen und erneut öffnen.

Für die Website sind **keine zusätzlichen Python-Bibliotheken** notwendig.

---

# Alternative: manueller Start

Falls die Startdateien nicht verwendet werden sollen, kann die Website auch direkt über Python gestartet werden.

Windows:

```powershell
py start_server.py
```

macOS:

```bash
python3 start_server.py
```

Alternativ funktioniert auch der Standardserver von Python:

Windows:

```powershell
py -m http.server 8000
```

macOS:

```bash
python3 -m http.server 8000
```

Danach im Browser:

```text
http://localhost:8000/
```

---

# Warum Port 8000?

Die historischen Originalquellen wurden als statisches **IIIF Image API 3 Level 0** erzeugt.

Die entsprechenden `info.json`-Dateien enthalten Service-IDs nach dem Muster:

```text
http://localhost:8000/iiif/...
```

Deshalb verwendet die abgegebene lokale Forschungsumgebung bewusst immer:

```text
localhost:8000
```

Ein anderer Port würde die IIIF-Verknüpfungen verändern und ist für die Abgabe nicht vorgesehen.

---

# Was ist im Repository enthalten?

Die für die Webansicht relevanten Bestandteile sind ungefähr:

```text
goldmine_openstreetview/
│
├── README.md
├── index.html
├── style.css
├── app.js
│
├── start_server.py
├── START_WINDOWS.bat
├── START_MAC.sh
├── check_repository.py
│
├── data/
│   ├── site-data.json
│   ├── gv-metadata.json
│   ├── iiif-overrides.json
│   └── RAW/
│       ├── *.json
│       └── historische Quellenbilder
│
├── iiif/
│   └── ...
│       ├── info.json
│       └── Bild-Tiles
│
├── assets/
│   └── ...
│
├── export_nodegoat_for_web.py
└── generate_iiif.py
```

## `data/site-data.json`

Diese Datei enthält den für die Website exportierten Forschungsstand aus nodegoat.

Die Website greift für die zentrale Datenansicht **nicht direkt auf die geschützte nodegoat-API** zu.

Dadurch werden für die Betrachtung weder Benutzerkonto noch API-Token benötigt.

## `data/RAW/`

Enthält die strukturierten JSON-Extraktionen und – sofern für die Publikation freigegeben – die zugehörigen digitalen Quellenbilder.

## `iiif/`

Enthält die vorab erzeugte statische IIIF-Struktur mit `info.json` und Bild-Tiles.

Für die Betrachtung muss **kein IIIF-Server installiert werden**.

## `assets/`

Enthält Bilder und weitere statische Dateien der Weboberfläche.

---

# Externe Online-Komponenten

Die lokale Website enthält den exportierten Forschungsstand und die statischen IIIF-Dateien.

Einzelne Funktionen greifen jedoch bewusst auf externe Dienste zu:

- das öffentliche nodegoat-Interface,
- Panoramax,
- sowie derzeit einige JavaScript-/CSS-Bibliotheken über fest versionierte CDNs.

Für die vollständige Funktionalität der Weboberfläche wird deshalb eine Internetverbindung empfohlen.

Wenn ein externer Dienst vorübergehend nicht erreichbar ist, bleiben die lokal gespeicherten Forschungsdaten davon unberührt.

---

# Repository vor der Abgabe prüfen

Vor dem Hochladen auf GitHub kann eine automatische Strukturprüfung ausgeführt werden.

Windows:

```powershell
py check_repository.py
```

macOS:

```bash
python3 check_repository.py
```

Die Prüfung kontrolliert unter anderem:

- ob die wichtigsten Website-Dateien vorhanden sind,
- ob `data/site-data.json` gelesen werden kann,
- ob verknüpfte lokale JSON-/Bild-/IIIF-Dateien existieren,
- wie viele IIIF-`info.json`-Dateien vorhanden sind,
- und ob offensichtliche Secret-Dateien im Projektordner liegen.

Am Ende sollte erscheinen:

```text
REPOSITORY-CHECK ERFOLGREICH.
Die statische Webansicht ist strukturell abgabebereit.
```

---

# Wichtig vor dem Upload auf GitHub

## 1. Keine Zugangsdaten hochladen

Der nodegoat-Bearer-Token darf **nicht** im Repository gespeichert werden.

Im Projekt wird er für Entwicklungsarbeiten nur als lokale Umgebungsvariable verwendet.

Nicht hochladen:

```text
.env
token.txt
*.key
*.pem
```

Die beigefügte `.gitignore` schliesst typische Secret-Dateien bereits aus.

## 2. `tools/` nicht hochladen

Der lokale Windows-libvips-Ordner wird zur Betrachtung der Website nicht benötigt.

Er ist:

- betriebssystemspezifisch,
- relativ gross,
- und für macOS ungeeignet.

Deshalb wird `tools/` durch `.gitignore` ausgeschlossen.

Die fertigen IIIF-Dateien im Ordner `iiif/` werden dagegen **mit dem Repository abgegeben**.

## 3. Generierte Forschungsartefakte ausdrücklich mit hochladen

Folgende Ordner beziehungsweise Dateien müssen im Abgabe-Repository enthalten sein:

```text
data/site-data.json
data/RAW/
iiif/
assets/
```

Diese Dateien sind notwendig, damit die abgegebene Version ohne erneuten Build betrachtet werden kann.

---

# Website betrachten ≠ Forschungsdaten neu erzeugen

Für die Abgabe werden zwei Ebenen bewusst getrennt.

## A. Website betrachten

Benötigt nur:

```text
Python 3
```

und:

```text
start_server.py
```

Es werden keine Forschungsdaten verändert.

## B. Forschungsdaten neu erzeugen

Nur für die Weiterentwicklung des Projekts relevant.

Dafür existieren unter anderem:

```text
export_nodegoat_for_web.py
generate_iiif.py
```

Der nodegoat-Export benötigt einen eigenen API-Token.

Die Neuerzeugung der IIIF-Bildpyramiden benötigt **libvips**.

Diese Schritte sind **nicht notwendig**, um die eingereichte Website anzusehen.

---

# Datenfluss

Die veröffentlichte Webansicht folgt vereinfacht diesem Ablauf:

```text
nodegoat
    ↓
Python-Export
    ↓
data/site-data.json
    ↓
Website
    ├── Generalversammlungen
    ├── Personen & Firmen
    ├── Aktienvisualisierungen
    └── Karten

Historische Quellenbilder
    ↓
libvips
    ↓
statisches IIIF
    ↓
OpenSeadragon

JSON-Extraktionen
    ↓
Quellenansicht neben IIIF
```

---

# Hinweise zu den Visualisierungen

Die Aktienvisualisierungen werden beim Laden der Website aus den exportierten Forschungsdaten berechnet.

Dargestellt werden unter anderem:

- Aktien Ordinaires und Priorité pro Generalversammlung,
- Konzentration des Aktienbesitzes,
- grösster Aktienbestand,
- Top 3 und Top 5,
- sowie individuelle Aktienverläufe von Personen und Firmen.

Fehlende Erwähnungen einer Person in einer Generalversammlung werden **nicht automatisch als Aktienbestand von 0 interpretiert**.

Unplausible Einzelwerte werden in der quantitativen Analyse nicht automatisch korrigiert, sondern als Datenqualitätsproblem kenntlich gemacht.

---

# GitHub-Abgabe: empfohlener Ablauf

Wenn der lokale Stand fertig ist:

```text
1. Repository-Check ausführen
2. Geheimnisse und unnötige lokale Tools ausschliessen
3. vollständigen statischen Forschungsstand committen
4. auf GitHub pushen
5. Abgabe-Commit mit einem Tag markieren
6. Repository selbst einmal als ZIP herunterladen
7. ZIP in einen neuen Ordner entpacken
8. Website exakt nach dieser README starten
9. erst danach den GitHub-Link abgeben
```

Für die Abgabe empfiehlt sich beispielsweise ein Tag wie:

```text
seminar-submission-v1.0
```

Damit bleibt eindeutig nachvollziehbar, welche Version der Website zur Seminararbeit gehört.

---

# Fehlerbehebung

## Die Website wurde per Doppelklick geöffnet und funktioniert nicht richtig

Nicht:

```text
file:///.../index.html
```

verwenden.

Stattdessen den lokalen Server starten und öffnen:

```text
http://localhost:8000/
```

## Port 8000 wird bereits verwendet

Wahrscheinlich läuft noch ein früherer lokaler Server.

Das alte Terminal-/PowerShell-Fenster suchen und dort:

```text
Ctrl + C
```

drücken.

Danach erneut starten.

## Die Website zeigt eine alte Version

Windows:

```text
Ctrl + F5
```

macOS:

```text
Command + Shift + R
```

## nodegoat oder Panoramax wird nicht angezeigt

Diese Teile benötigen eine Internetverbindung und hängen von externen Diensten ab.

Die lokal gespeicherten Forschungsdaten und IIIF-Dateien sind davon getrennt.

---

# Technischer Hinweis

Der lokale Server basiert ausschliesslich auf der Python-Standardbibliothek.

Er ist nur für die **lokale Betrachtung der statischen Forschungswebsite** gedacht und nicht als produktiver öffentlicher Webserver.

---

# Rechte und Lizenzen

Die im Projekt eingesetzten Softwarebibliotheken und Standards werden im Forschungsworkflow transparent ausgewiesen.

Für die Veröffentlichung des Repositorys sollte zusätzlich geprüft werden, welche Nutzungs- und Reproduktionsrechte für die historischen Originalscans gelten.

Eine Open-Source-Lizenz für den selbst geschriebenen Code bedeutet nicht automatisch, dass historische Quellenbilder unter derselben Lizenz weitergegeben werden dürfen.
