#!/usr/bin/env python3
r"""
Hybrid-Exporter V3 für die Mines-de-Costano-Webseite.

Ziel
----
Quantitative Aktienwerte und Quellzeilen kommen aus data/RAW/*.json.
nodegoat bleibt die Autorität für Entity Resolution, stabile Objekt-IDs,
W/M/F/U-Klassifikation, Wohnorte/Georeferenzen sowie Anwesenheit/Vertretung.

Sicherer Test ohne API:
    py .\export_hybrid_for_web_v3_final.py --base-site-data data\site-data.json

Aktuellen nodegoat-Stand zuerst über den bestehenden V2-Exporter laden:
    $env:NODEGOAT_TOKEN = "..."
    py .\export_hybrid_for_web_v3_final.py --refresh-nodegoat

Standardausgabe:
    data/site-data-v3.json

Die produktive Datei wird nur mit --apply überschrieben:
    py .\export_hybrid_for_web_v3_final.py --refresh-nodegoat --apply
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unicodedata
from typing import Any, Iterable


DEFAULT_OUTPUT = Path("data/site-data-v3.json")
PRODUCTION_OUTPUT = Path("data/site-data.json")
DEFAULT_GV_METADATA = Path("data/gv-metadata.json")
DEFAULT_RAW_DIR = Path("data/RAW")

BASE_EXPORTER_CANDIDATES = (
    "export_nodegoat_for_web_V2.py",
    "export_nodegoat_for_web_v2.py",
    "export_nodegoat_for_web.py",
)

CLASSIFICATION_CODES = {"W", "M", "F", "U"}

# Nur historisch bereits geprüfte Varianten. Keine fuzzy Entity Resolution.
EXPLICIT_ENTITY_ALIASES = {
    # Rohquellenvarianten der Compagnie Centrale ...
    "centrale compagnie sicli":
        "COMPAGNIE CENTRALE DE MINES et de METALLURGIE",
    "centrale compagnie metallurgie mines sicli":
        "COMPAGNIE CENTRALE DE MINES et de METALLURGIE",
}

# Wörter, die für den deterministischen Namensschlüssel keine Identität tragen.
NAME_STOPWORDS = {
    "m", "mr", "mme", "mlle", "monsieur", "madame", "me",
    "le", "la", "de", "des", "du", "d", "et",
    "professeur", "avocat", "doti", "von", "erben",
}

NAME_REPLACEMENTS = {
    "ste": "societe",
    "cie": "compagnie",
    "terenzino": "terenzio",
}

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


# ============================================================
# IO / ALLGEMEINE HILFEN
# ============================================================

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


def as_text(value: Any) -> str:
    return str(value or "").strip()


def split_source_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(split_source_values(item))
        return list(dict.fromkeys(out))

    text = str(value).strip()
    if not text:
        return []

    # Nodegoat exportierte 1951 zeitweise drei Dateinamen in einem String.
    parts = re.split(r"[;\r\n]+", text)
    return [part.strip() for part in parts if part.strip()]


def safe_identifier(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.encode("ascii", errors="ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._-")
    return value or "source"


def relative_web_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# ============================================================
# QUANTITATIVE WERTE AUS RAW
# ============================================================

def parse_share_value(value: Any) -> dict[str, Any]:
    """
    Parser ohne stilles Raten.

    - leer / '-' / '/' -> 0, Status empty
    - einzelne Ganzzahl -> Zahl, Status ok
    - mehrere Zahlen in derselben Zelle -> None, Status ambiguous
    - sonstige nichtnumerische Angabe -> None, Status invalid
    """
    raw = value

    if value is None:
        return {"value": 0, "status": "empty", "raw": raw}

    text = str(value).strip()
    if not text or text in {"-", "/", "–", "—"}:
        return {"value": 0, "status": "empty", "raw": raw}

    if re.fullmatch(r"[+-]?\d+", text):
        return {"value": int(text), "status": "ok", "raw": raw}

    numbers = re.findall(r"[+-]?\d+", text)
    if len(numbers) > 1:
        return {"value": None, "status": "ambiguous", "raw": raw}

    return {"value": None, "status": "invalid", "raw": raw}


def parse_declared_total(value: Any) -> int | None:
    parsed = parse_share_value(value)
    if parsed["status"] == "ok":
        return parsed["value"]
    return None


def load_raw_pages(raw_dir: Path) -> dict[str, dict[str, Any]]:
    """Lädt jede JSON-Quelldatei genau einmal, Schlüssel = Dateiname."""
    if not raw_dir.exists():
        raise FileNotFoundError(f"RAW-Ordner nicht gefunden: {raw_dir}")

    pages: dict[str, dict[str, Any]] = {}

    for path in sorted(raw_dir.rglob("*.json")):
        data = read_json(path)
        if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
            continue

        pages[path.name] = {
            "path": path,
            "data": data,
            "document": as_text(data.get("document")) or path.stem,
            "page_number": data.get("page_number"),
        }

    if not pages:
        raise RuntimeError(f"Keine RAW-JSON-Dateien in {raw_dir} gefunden.")

    return pages


def raw_page_entry_sums(page: dict[str, Any]) -> dict[str, Any]:
    sum_o = 0
    sum_p = 0
    ambiguous = 0
    invalid = 0

    for entry in page["data"].get("entries", []):
        o = parse_share_value(entry.get("actions_o"))
        p = parse_share_value(entry.get("actions_p"))

        if o["value"] is not None:
            sum_o += o["value"]
        if p["value"] is not None:
            sum_p += p["value"]

        ambiguous += (o["status"] == "ambiguous") + (p["status"] == "ambiguous")
        invalid += (o["status"] == "invalid") + (p["status"] == "invalid")

    totals = page["data"].get("total_actions") or {}
    if not isinstance(totals, dict):
        totals = {}

    return {
        "entry_sum_o_known": sum_o,
        "entry_sum_p_known": sum_p,
        "entry_sum_known": sum_o + sum_p,
        "declared_o": parse_declared_total(totals.get("total_o")),
        "declared_p": parse_declared_total(totals.get("total_p")),
        "declared_total": parse_declared_total(totals.get("total_voix")),
        "ambiguous_cells": ambiguous,
        "invalid_cells": invalid,
    }


def totals_for_gv_source_files(
    source_files: list[str],
    raw_pages: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """
    Berechnet die Aktien-Gesamtsumme einer GV direkt aus den einzelnen
    RAW-Einträgen aller zugeordneten JSON-Seiten.

    Wichtig für mehrseitige Listen wie 1951:
    ``total_actions`` am Seitenende kann ein fortgeschriebener REPORT sein.
    Diese Seitenwerte werden deshalb NICHT addiert. Stattdessen werden alle
    ``entries`` genau einmal addiert. Die deklarierten Seitentotale dienen
    nur als Plausibilitätskontrolle gegen die laufende kumulative Summe.
    """
    pages = []
    for source in source_files:
        name = Path(source).name
        page = raw_pages.get(name)
        if page is None:
            raise FileNotFoundError(f"RAW-Quelldatei fehlt: {source}")
        pages.append(page)

    if not pages:
        return {
            "ordinaires": 0,
            "priorite": 0,
            "total": 0,
            "strategy": "sum_raw_entries",
            "page_audit": [],
            "validation_warnings": [],
        }

    total_o = 0
    total_p = 0
    audit = []
    validation_warnings = []

    for page in pages:
        page_info = raw_page_entry_sums(page)

        if page_info.get("ambiguous_cells") or page_info.get("invalid_cells"):
            raise RuntimeError(
                f"{page['path'].name}: mehrdeutige oder ungültige Aktienwerte "
                "in den RAW-Einträgen. Bitte zuerst die JSON-Quelle korrigieren."
            )

        page_o = int(page_info["entry_sum_o_known"])
        page_p = int(page_info["entry_sum_p_known"])
        total_o += page_o
        total_p += page_p

        declared_o = page_info.get("declared_o")
        declared_p = page_info.get("declared_p")

        declared_matches_running = None
        if declared_o is not None and declared_p is not None:
            declared_matches_running = (
                int(declared_o) == total_o and
                int(declared_p) == total_p
            )
            if not declared_matches_running:
                validation_warnings.append(
                    f"{page['path'].name}: laufende Summe aus entries "
                    f"O={total_o}, P={total_p} weicht vom angegebenen REPORT "
                    f"O={declared_o}, P={declared_p} ab."
                )

        audit.append({
            "source_file": page["path"].name,
            "document": page["document"],
            "page_number": page["page_number"],
            **page_info,
            "page_entry_o": page_o,
            "page_entry_p": page_p,
            "running_o": total_o,
            "running_p": total_p,
            "declared_matches_running": declared_matches_running,
        })

    return {
        "ordinaires": total_o,
        "priorite": total_p,
        "total": total_o + total_p,
        "strategy": "sum_raw_entries",
        "page_audit": audit,
        "validation_warnings": validation_warnings,
    }


# ============================================================
# ENTITY RESOLUTION: RAW -> NODEGOAT
# ============================================================

def ascii_tokens(value: Any) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.encode("ascii", errors="ignore").decode("ascii").lower()

    # Succession ist kein stabiler Bestandteil des Personennamens.
    text = re.sub(r"\bsuc(?:c|cession)?\.?\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)

    out = []
    for token in text.split():
        token = NAME_REPLACEMENTS.get(token, token)
        if token in NAME_STOPWORDS:
            continue
        out.append(token)
    return out


def canonical_name_key(value: Any) -> str:
    return " ".join(sorted(ascii_tokens(value)))


def build_entity_index(persons: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_id: dict[str, dict[str, Any]] = {}

    for person in persons:
        pid = person.get("person_id")
        if pid not in (None, ""):
            by_id[str(pid)] = person

        key = canonical_name_key(person.get("name"))
        if key:
            by_key[key].append(person)

    return by_key, by_id


def resolve_entity(
    raw_name: str,
    by_key: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str, str]:
    """Returns (person, match_mode, canonical_key). Keine fuzzy Matches."""
    key = canonical_name_key(raw_name)
    matches = by_key.get(key, [])

    if len(matches) == 1:
        return matches[0], "canonical_exact", key

    if len(matches) > 1:
        return None, "ambiguous_entity_key", key

    target_name = EXPLICIT_ENTITY_ALIASES.get(key)
    if target_name:
        target_key = canonical_name_key(target_name)
        target_matches = by_key.get(target_key, [])
        if len(target_matches) == 1:
            return target_matches[0], "explicit_alias", key
        if len(target_matches) > 1:
            return None, "ambiguous_alias_target", key

    return None, "unmatched", key


# ============================================================
# GV-ZUORDNUNG / NODEGOAT-ENRICHMENT
# ============================================================

def metadata_year(info: dict[str, Any]) -> int | None:
    try:
        year = int(info.get("year"))
        if year > 0:
            return year
    except (TypeError, ValueError):
        pass

    m = re.match(r"^(\d{4})", as_text(info.get("date")))
    return int(m.group(1)) if m else None


def gv_map_local_to_base(
    local_metadata: dict[str, Any],
    base_gv: dict[str, dict[str, Any]],
) -> dict[str, str]:
    mapping: dict[str, str] = {}

    for local_id, local_info in local_metadata.items():
        local_date = as_text(local_info.get("date"))
        local_year = metadata_year(local_info)

        exact = [
            gv_id for gv_id, info in base_gv.items()
            if local_date and as_text(info.get("date")) == local_date
        ]

        if len(exact) == 1:
            mapping[local_id] = exact[0]
            continue

        year_matches = [
            gv_id for gv_id, info in base_gv.items()
            if local_year is not None and metadata_year(info) == local_year
        ]

        if len(year_matches) == 1:
            mapping[local_id] = year_matches[0]
            continue

        raise RuntimeError(
            f"GV-Zuordnung nicht eindeutig für {local_id}: "
            f"Datum={local_date!r}, Jahr={local_year}, Treffer={year_matches}"
        )

    return mapping


def build_base_record_index(records: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        pid = record.get("person_id")
        gv_id = record.get("gv_id")
        if pid in (None, "") or not gv_id:
            continue
        out[(str(pid), str(gv_id))] = record
    return out


# ============================================================
# QUELLENVIEWER
# ============================================================

def find_image_for_json(json_path: Path) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        candidate = json_path.with_suffix(ext)
        if candidate.exists():
            return candidate
    return None


def source_page_for_raw(
    source_file: str,
    raw_pages: dict[str, dict[str, Any]],
    project_root: Path,
) -> dict[str, Any]:
    page = raw_pages[Path(source_file).name]
    json_path = page["path"]
    document = page["document"]
    image_path = find_image_for_json(json_path)

    identifier = safe_identifier(document)
    iiif_path = project_root / "iiif" / identifier / "info.json"

    return {
        "id": document,
        "label": document,
        "document": document,
        "json_name": json_path.name,
        "json_url": relative_web_path(json_path, project_root),
        "image_url": (
            relative_web_path(image_path, project_root)
            if image_path else ""
        ),
        "iiif_info_url": (
            relative_web_path(iiif_path, project_root)
            if iiif_path.exists() else ""
        ),
    }


# ============================================================
# HYBRID-MERGE
# ============================================================

def make_raw_record(
    *,
    entry: dict[str, Any],
    page: dict[str, Any],
    base_gv_id: str,
    base_gv_info: dict[str, Any],
    person: dict[str, Any] | None,
    base_record: dict[str, Any] | None,
    match_mode: str,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []

    o = parse_share_value(entry.get("actions_o"))
    p = parse_share_value(entry.get("actions_p"))

    statuses = {o["status"], p["status"]}
    if "invalid" in statuses:
        share_status = "invalid"
    elif "ambiguous" in statuses:
        share_status = "ambiguous"
    else:
        share_status = "ok"

    actions_total = (
        o["value"] + p["value"]
        if share_status == "ok" and o["value"] is not None and p["value"] is not None
        else None
    )

    raw_name = as_text(entry.get("name"))
    person_id = person.get("person_id") if person else None

    if share_status != "ok":
        warnings.append(
            f"{base_gv_info.get('year')}: {raw_name}: "
            f"Aktienwert {share_status}; O={entry.get('actions_o')!r}, "
            f"P={entry.get('actions_p')!r}."
        )

    if person is None:
        warnings.append(
            f"{base_gv_info.get('year')}: {raw_name}: "
            "keinem nodegoat-Objekt zugeordnet; RAW-Zeile bleibt erhalten."
        )

    # Nodegoat liefert die Normalisierung/Georeferenz; die RAW-Zeile liefert
    # Name in Quelle, Nummer und quantitative Werte.
    enriched = base_record or {}

    classification = as_text(person.get("classification_code") if person else "")
    if classification not in CLASSIFICATION_CODES:
        classification = ""

    normalized_name = as_text(person.get("name") if person else raw_name)

    record = {
        "person_id": int(person_id) if str(person_id).isdigit() else None,
        "nodegoat_object_id": int(person_id) if str(person_id).isdigit() else None,
        "normalized_name": normalized_name,
        "name": normalized_name,
        "source_name": raw_name,
        "first_name": as_text(person.get("first_name") if person else ""),
        "last_name": as_text(person.get("last_name") if person else ""),
        "classification_code": classification,
        "entity_match_mode": match_mode,
        "gv_id": base_gv_id,
        "gv_nodegoat_id": base_gv_info.get("nodegoat_id"),
        "gv_date": base_gv_info.get("date", ""),
        "gv_year": base_gv_info.get("year"),
        "number": as_text(entry.get("number")),
        "address": as_text(enriched.get("address")) or as_text(entry.get("address")),
        "source_address": as_text(entry.get("address")),
        "geocode_query": as_text(enriched.get("geocode_query")) or as_text(entry.get("address")),
        "lat": enriched.get("lat"),
        "lon": enriched.get("lon"),
        "location_ref_id": enriched.get("location_ref_id"),
        "location_mode": as_text(enriched.get("location_mode")),
        "actions_o": o["value"],
        "actions_p": p["value"],
        "actions_total": actions_total,
        "actions_o_raw": entry.get("actions_o"),
        "actions_p_raw": entry.get("actions_p"),
        "actions_o_status": o["status"],
        "actions_p_status": p["status"],
        "share_status": share_status,
        "no_de_voix_raw": entry.get("no_de_voix"),
        "signature_present": entry.get("signature_present"),
        "signature": entry.get("signature"),
        "present": enriched.get("present"),
        "represented_by_id": enriched.get("represented_by_id"),
        "geocode_quality": as_text(enriched.get("geocode_quality")) or (
            "raw_only" if person is None else "missing"
        ),
        "geocode_note": as_text(enriched.get("geocode_note")) or (
            "Adresse aus RAW; keine nodegoat-Georeferenz vorhanden."
            if person is None else ""
        ),
        "document": page["document"],
        "source_file": page["path"].name,
        "page_number": page["page_number"],
        "data_source": "raw+nodegoat" if person is not None else "raw_only",
    }

    return record, warnings


def rebuild_persons(
    base_persons: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_pid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    raw_only: list[dict[str, Any]] = []

    for record in records:
        pid = record.get("person_id")
        if pid in (None, ""):
            raw_only.append(record)
        else:
            by_pid[str(pid)].append(record)

    persons: list[dict[str, Any]] = []

    for base_person in base_persons:
        pid = base_person.get("person_id")
        appearances = []
        for record in by_pid.get(str(pid), []):
            appearances.append({
                "gv_id": record.get("gv_id"),
                "gv_nodegoat_id": record.get("gv_nodegoat_id"),
                "date": record.get("gv_date", ""),
                "year": record.get("gv_year"),
                "address": record.get("address", ""),
                "lat": record.get("lat"),
                "lon": record.get("lon"),
                "location_ref_id": record.get("location_ref_id"),
                "location_mode": record.get("location_mode", ""),
                "actions_o": record.get("actions_o"),
                "actions_p": record.get("actions_p"),
                "actions_total": record.get("actions_total"),
                "share_status": record.get("share_status"),
                "present": record.get("present"),
                "represented_by_id": record.get("represented_by_id"),
                "source_file": record.get("source_file"),
                "number": record.get("number"),
            })

        # Personen ohne RAW-Zeile (z.B. reine Vertreter*innen) bleiben als
        # Entität erhalten, bekommen aber keine Aktien-Appearance erfunden.
        person = deepcopy(base_person)
        person["appearances"] = sorted(
            appearances,
            key=lambda a: (str(a.get("date") or a.get("year") or "9999"), str(a.get("gv_id"))),
        )
        persons.append(person)

    # RAW-only Akteur*innen sichtbar halten, ohne eine nodegoat-ID zu erfinden.
    for record in raw_only:
        raw_key = (
            f"raw:{record.get('gv_year')}:{record.get('source_file')}:"
            f"{record.get('number') or canonical_name_key(record.get('source_name'))}"
        )
        persons.append({
            "person_id": raw_key,
            "name": record.get("source_name") or record.get("name"),
            "first_name": "",
            "last_name": "",
            "classification_code": "",
            "data_source": "raw_only",
            "appearances": [{
                "gv_id": record.get("gv_id"),
                "gv_nodegoat_id": record.get("gv_nodegoat_id"),
                "date": record.get("gv_date", ""),
                "year": record.get("gv_year"),
                "address": record.get("address", ""),
                "lat": record.get("lat"),
                "lon": record.get("lon"),
                "location_ref_id": record.get("location_ref_id"),
                "location_mode": record.get("location_mode", ""),
                "actions_o": record.get("actions_o"),
                "actions_p": record.get("actions_p"),
                "actions_total": record.get("actions_total"),
                "share_status": record.get("share_status"),
                "present": record.get("present"),
                "represented_by_id": record.get("represented_by_id"),
                "source_file": record.get("source_file"),
                "number": record.get("number"),
            }],
        })

    persons.sort(key=lambda p: (as_text(p.get("name")).casefold(), str(p.get("person_id"))))
    return persons


def build_hybrid_payload(
    base_payload: dict[str, Any],
    local_metadata: dict[str, Any],
    raw_pages: dict[str, dict[str, Any]],
    project_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_gv = base_payload.get("gv_metadata") or {}
    base_records = base_payload.get("records") or []
    base_persons = base_payload.get("persons") or []

    if not base_gv or not base_persons:
        raise RuntimeError("Base-Export enthält keine gv_metadata/persons.")

    local_to_base = gv_map_local_to_base(local_metadata, base_gv)
    entity_by_key, _ = build_entity_index(base_persons)
    base_record_index = build_base_record_index(base_records)

    # Quantitative GV-Metadaten aktualisieren.
    hybrid_gv = deepcopy(base_gv)
    gv_audit: dict[str, Any] = {}
    warnings: list[str] = []

    for local_id, base_gv_id in local_to_base.items():
        local_info = local_metadata[local_id]
        source_files = split_source_values(local_info.get("source_files"))
        raw_totals = totals_for_gv_source_files(source_files, raw_pages)
        info = hybrid_gv[base_gv_id]
        info["source_files"] = source_files
        info["source_pages"] = [
            source_page_for_raw(source, raw_pages, project_root)
            for source in source_files
        ]

        # Provenienz der früheren nodegoat-GV-Summen erhalten.
        info["nodegoat_total_actions"] = info.get("total_actions")
        info["nodegoat_total_actions_o"] = info.get("total_actions_o")
        info["nodegoat_total_actions_p"] = info.get("total_actions_p")

        info["total_actions_o"] = raw_totals["ordinaires"]
        info["total_actions_p"] = raw_totals["priorite"]
        info["total_actions"] = raw_totals["total"]
        info["total_source"] = "raw"
        info["total_strategy"] = raw_totals["strategy"]

        gv_audit[base_gv_id] = {
            "local_gv_id": local_id,
            "year": info.get("year"),
            "source_files": source_files,
            **raw_totals,
        }

        warnings.extend(raw_totals.get("validation_warnings", []))

    hybrid_records: list[dict[str, Any]] = []

    # Mehrseitige RAW-Quellen werden als eigenständige Seiten behandelt.
    match_counts: Counter[str] = Counter()

    # RAW-Dateien nur gemäss gv-metadata konsumieren, in dortiger Reihenfolge.
    for local_id, base_gv_id in local_to_base.items():
        base_gv_info = hybrid_gv[base_gv_id]
        source_files = split_source_values(local_metadata[local_id].get("source_files"))

        for source_file in source_files:
            page = raw_pages[Path(source_file).name]
            for entry in page["data"].get("entries", []):
                if not isinstance(entry, dict):
                    continue

                person, match_mode, _ = resolve_entity(
                    as_text(entry.get("name")),
                    entity_by_key,
                )
                match_counts[match_mode] += 1

                base_record = None
                if person is not None and person.get("person_id") not in (None, ""):
                    base_record = base_record_index.get(
                        (str(person.get("person_id")), str(base_gv_id))
                    )

                record, row_warnings = make_raw_record(
                    entry=entry,
                    page=page,
                    base_gv_id=base_gv_id,
                    base_gv_info=base_gv_info,
                    person=person,
                    base_record=base_record,
                    match_mode=match_mode,
                )
                hybrid_records.append(record)
                warnings.extend(row_warnings)

    # Deterministische Sortierung: GV, Quellseite, laufende Nummer.
    def numeric_number(value: Any) -> tuple[int, str]:
        text = as_text(value)
        m = re.match(r"^\d+$", text)
        return (int(text), text) if m else (10**9, text)

    hybrid_records.sort(
        key=lambda r: (
            str(r.get("gv_date") or r.get("gv_year") or "9999"),
            str(r.get("source_file") or ""),
            numeric_number(r.get("number")),
            str(r.get("source_name") or "").casefold(),
        )
    )

    hybrid_persons = rebuild_persons(base_persons, hybrid_records)

    classification_counts = Counter(
        as_text(p.get("classification_code")) or "missing"
        for p in base_persons
    )

    audit = {
        "raw_record_count": len(hybrid_records),
        "base_record_count": len(base_records),
        "nodegoat_person_count": len(base_persons),
        "output_person_count": len(hybrid_persons),
        "match_counts": dict(sorted(match_counts.items())),
        "share_status_counts": dict(sorted(Counter(
            r.get("share_status", "") for r in hybrid_records
        ).items())),
        "gv": gv_audit,
        "warnings": warnings,
    }

    payload = deepcopy(base_payload)
    payload["gv_metadata"] = hybrid_gv
    payload["records"] = hybrid_records
    payload["persons"] = hybrid_persons
    payload["audit"] = audit

    old_meta = payload.get("meta") or {}
    payload["meta"] = {
        **old_meta,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "raw+nodegoat",
        "quantitative_source": "data/RAW",
        "entity_source": "nodegoat",
        "record_count": len(hybrid_records),
        "person_count": len(hybrid_persons),
        "nodegoat_person_count": len(base_persons),
        "gv_count": len(hybrid_gv),
        "classification_counts": {
            "W": classification_counts.get("W", 0),
            "M": classification_counts.get("M", 0),
            "F": classification_counts.get("F", 0),
            "U": classification_counts.get("U", 0),
            "missing": classification_counts.get("missing", 0),
        },
        "warning_count": len(warnings),
        "raw_only_record_count": match_counts.get("unmatched", 0),
    }

    return payload, audit


# ============================================================
# BASE-EXPORT LADEN
# ============================================================

def find_base_exporter(project_root: Path, explicit: Path | None) -> Path:
    if explicit:
        path = explicit if explicit.is_absolute() else project_root / explicit
        if path.exists():
            return path
        raise FileNotFoundError(f"Base-Exporter nicht gefunden: {path}")

    current = Path(__file__).resolve()
    for name in BASE_EXPORTER_CANDIDATES:
        path = (project_root / name).resolve()
        if path.exists() and path != current:
            return path

    raise FileNotFoundError(
        "Kein V2-Exporter gefunden. Erwartet z.B. export_nodegoat_for_web_V2.py."
    )


def import_module_from_path(path: Path):
    spec = importlib.util.spec_from_file_location("goldmine_base_exporter_v2", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Exporter konnte nicht importiert werden: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refresh_base_payload(
    project_root: Path,
    exporter_path: Path,
    api_host: str | None,
    project_id: int | None,
) -> dict[str, Any]:
    token = os.environ.get("NODEGOAT_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "NODEGOAT_TOKEN ist nicht gesetzt. Für einen Offline-Test "
            "stattdessen --base-site-data verwenden."
        )

    module = import_module_from_path(exporter_path)
    if not hasattr(module, "export"):
        raise RuntimeError(f"{exporter_path.name} enthält keine export()-Funktion.")

    host = api_host or getattr(module, "API_HOST", None)
    pid = project_id or getattr(module, "PROJECT_ID", None)
    if not host or not pid:
        raise RuntimeError("API_HOST/PROJECT_ID konnten nicht aus V2 übernommen werden.")

    with tempfile.TemporaryDirectory(prefix="goldmine_v3_") as tmpdir:
        temp_output = Path(tmpdir) / "nodegoat-base.json"
        payload = module.export(
            token=token,
            output=temp_output,
            api_host=host,
            project_id=int(pid),
        )
        if not isinstance(payload, dict):
            payload = read_json(temp_output)

    return payload


# ============================================================
# AUDIT-AUSGABE
# ============================================================

def format_int(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", "'")
    except (TypeError, ValueError):
        return "–"


def print_audit(audit: dict[str, Any]) -> None:
    print("\n" + "=" * 72)
    print("HYBRID-V3-AUDIT")
    print("=" * 72)
    print(f"RAW-Zeilen:             {audit['raw_record_count']}")
    print(f"Nodegoat-Basiszeilen:   {audit['base_record_count']}")
    print(f"Nodegoat-Entitäten:     {audit['nodegoat_person_count']}")
    print(f"Ausgabe-Entitäten:      {audit['output_person_count']}")
    print("Entity-Matching:        " + " · ".join(
        f"{key}={value}" for key, value in audit["match_counts"].items()
    ))
    print("Aktienstatus:           " + " · ".join(
        f"{key}={value}" for key, value in audit["share_status_counts"].items()
    ))

    print("\nGV-Gesamtsummen aus RAW:")
    for _, info in sorted(
        audit["gv"].items(),
        key=lambda item: str(item[1].get("year") or "9999"),
    ):
        print(
            f"  {info.get('year')}: "
            f"O={format_int(info.get('ordinaires'))} · "
            f"P={format_int(info.get('priorite'))} · "
            f"Total={format_int(info.get('total'))} · "
            f"{info.get('strategy')}"
        )

    warnings = audit.get("warnings") or []
    if warnings:
        print(f"\nWarnungen: {len(warnings)}")
        for warning in warnings[:20]:
            print(f"  - {warning}")
        if len(warnings) > 20:
            print(f"  ... plus {len(warnings) - 20} weitere")
    else:
        print("\nWarnungen: 0")


# ============================================================
# SELF TEST
# ============================================================

def self_test() -> None:
    assert parse_share_value("")["value"] == 0
    assert parse_share_value("150")["value"] == 150
    assert parse_share_value("537")["status"] == "ok"
    assert parse_share_value("537")["value"] == 537
    assert canonical_name_key("M. BREHAM Alain") == canonical_name_key("Alain BREHAM")
    assert canonical_name_key("Pani doti. Terenzino") == canonical_name_key("Terenzio PANI")
    assert safe_identifier("Se_23_Assemblée_page_2") == "Se_23_Assemblee_page_2"
    print("Self-Test erfolgreich.")


# ============================================================
# CLI
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Hybrid-Export: Aktien/Quellzeilen aus RAW, Entitäten und "
            "Georeferenzen aus nodegoat."
        )
    )
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--gv-metadata", type=Path, default=DEFAULT_GV_METADATA)
    parser.add_argument("--base-site-data", type=Path, default=None)
    parser.add_argument("--base-exporter", type=Path, default=None)
    parser.add_argument("--refresh-nodegoat", action="store_true")
    parser.add_argument("--api-host", default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    root = args.project_root.resolve()

    raw_dir = args.raw_dir if args.raw_dir.is_absolute() else root / args.raw_dir
    metadata_path = args.gv_metadata if args.gv_metadata.is_absolute() else root / args.gv_metadata

    raw_pages = load_raw_pages(raw_dir)
    local_metadata = read_json(metadata_path)

    if args.refresh_nodegoat:
        exporter_path = find_base_exporter(root, args.base_exporter)
        print(f"Nodegoat-Basis via: {exporter_path.name}")
        base_payload = refresh_base_payload(
            project_root=root,
            exporter_path=exporter_path,
            api_host=args.api_host,
            project_id=args.project_id,
        )
    else:
        base_path = args.base_site_data or PRODUCTION_OUTPUT
        base_path = base_path if base_path.is_absolute() else root / base_path
        print(f"Offline-Basis: {base_path}")
        base_payload = read_json(base_path)

    payload, audit = build_hybrid_payload(
        base_payload=base_payload,
        local_metadata=local_metadata,
        raw_pages=raw_pages,
        project_root=root,
    )

    print_audit(audit)

    if args.audit_only:
        print("\nAudit-only: keine Datei geschrieben.")
        return

    output = PRODUCTION_OUTPUT if args.apply else args.output
    output = output if output.is_absolute() else root / output
    write_json_atomic(output, payload)

    print("\nHYBRID-V3-EXPORT ERFOLGREICH")
    print(f"Datei: {output}")
    if not args.apply:
        print("Produktive data/site-data.json wurde NICHT überschrieben.")
        print("Nach Prüfung: denselben Aufruf mit --apply wiederholen.")


if __name__ == "__main__":
    main()
