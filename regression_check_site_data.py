#!/usr/bin/env python3
"""
Regressionstest für data/site-data.json.

Prüft nach jedem Hybrid-Export:
- 85 RAW-/Web-Records
- 44 Entitäten
- keine Warnungen
- keine unmatched / ambiguous Records
- erwartete GV-Gesamtsummen
- Summe der Record-Aktien je GV = GV-Gesamtsumme
- Jacques BREHAM 1951 = O 118 / P 537 / Total 655

Aufruf im Projektordner:
    py .\regression_check_site_data.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
import sys


SITE_DATA = Path("data/site-data.json")

EXPECTED_TOTALS = {
    1951: {"o": 1060, "p": 3200, "total": 4260},
    1961: {"o": 672, "p": 2297, "total": 2969},
    1962: {"o": 659, "p": 2310, "total": 2969},
    1965: {"o": 601, "p": 2217, "total": 2818},
    1967: {"o": 601, "p": 2217, "total": 2818},
    1968: {"o": 601, "p": 2217, "total": 2818},
    1969: {"o": 601, "p": 2217, "total": 2818},
}

EXPECTED_RECORD_COUNT = 85
EXPECTED_PERSON_COUNT = 44


def as_int(value):
    if value in (None, ""):
        return 0
    return int(value)


def fail(errors, message):
    errors.append(message)


def main():
    if not SITE_DATA.exists():
        print(f"FEHLER: {SITE_DATA} nicht gefunden.")
        sys.exit(1)

    payload = json.loads(
        SITE_DATA.read_text(encoding="utf-8")
    )

    meta = payload.get("meta", {})
    audit = payload.get("audit", {})
    records = payload.get("records", [])
    gv_metadata = payload.get("gv_metadata", {})

    errors = []

    if len(records) != EXPECTED_RECORD_COUNT:
        fail(
            errors,
            f"Recordzahl: erwartet {EXPECTED_RECORD_COUNT}, erhalten {len(records)}"
        )

    person_count = meta.get("person_count")
    if person_count != EXPECTED_PERSON_COUNT:
        fail(
            errors,
            f"Entitäten: erwartet {EXPECTED_PERSON_COUNT}, erhalten {person_count}"
        )

    warning_count = meta.get("warning_count", 0)
    if warning_count != 0:
        fail(
            errors,
            f"Warnungen: erwartet 0, erhalten {warning_count}"
        )

    match_counts = audit.get("match_counts", {})
    if match_counts.get("unmatched", 0) != 0:
        fail(
            errors,
            f"Unmatched Records: {match_counts.get('unmatched')}"
        )

    share_status = audit.get("share_status_counts", {})
    if share_status.get("ambiguous", 0) != 0:
        fail(
            errors,
            f"Ambiguous Aktienwerte: {share_status.get('ambiguous')}"
        )

    if share_status.get("invalid", 0) != 0:
        fail(
            errors,
            f"Invalid Aktienwerte: {share_status.get('invalid')}"
        )

    if share_status.get("ok", 0) != EXPECTED_RECORD_COUNT:
        fail(
            errors,
            f"Status ok: erwartet {EXPECTED_RECORD_COUNT}, "
            f"erhalten {share_status.get('ok', 0)}"
        )

    gv_by_year = {}
    for gv_id, info in gv_metadata.items():
        year = info.get("year")
        if year is not None:
            gv_by_year[int(year)] = (gv_id, info)

    records_by_gv = defaultdict(list)
    for record in records:
        records_by_gv[record.get("gv_id")].append(record)

    print("=" * 76)
    print("REGRESSIONSTEST SITE-DATA")
    print("=" * 76)

    for year, expected in EXPECTED_TOTALS.items():
        if year not in gv_by_year:
            fail(errors, f"{year}: GV fehlt")
            continue

        gv_id, info = gv_by_year[year]

        meta_o = as_int(info.get("total_actions_o"))
        meta_p = as_int(info.get("total_actions_p"))
        meta_total = as_int(info.get("total_actions"))

        rec_o = sum(
            as_int(record.get("actions_o"))
            for record in records_by_gv[gv_id]
        )
        rec_p = sum(
            as_int(record.get("actions_p"))
            for record in records_by_gv[gv_id]
        )
        rec_total = sum(
            as_int(record.get("actions_total"))
            for record in records_by_gv[gv_id]
        )

        print(
            f"{year}: "
            f"O={rec_o:,} · P={rec_p:,} · Total={rec_total:,}"
            .replace(",", "'")
        )

        actual_meta = {
            "o": meta_o,
            "p": meta_p,
            "total": meta_total,
        }

        actual_records = {
            "o": rec_o,
            "p": rec_p,
            "total": rec_total,
        }

        if actual_meta != expected:
            fail(
                errors,
                f"{year}: GV-Metadaten {actual_meta} != erwartet {expected}"
            )

        if actual_records != expected:
            fail(
                errors,
                f"{year}: Record-Summen {actual_records} != erwartet {expected}"
            )

    jacques = [
        record
        for record in records
        if (
            record.get("gv_year") == 1951
            and str(record.get("normalized_name", "")).strip().casefold()
            == "jacques breham"
        )
    ]

    if len(jacques) != 1:
        fail(
            errors,
            f"Jacques BREHAM 1951: erwartet 1 Record, erhalten {len(jacques)}"
        )
    else:
        record = jacques[0]
        values = (
            as_int(record.get("actions_o")),
            as_int(record.get("actions_p")),
            as_int(record.get("actions_total")),
        )

        if values != (118, 537, 655):
            fail(
                errors,
                "Jacques BREHAM 1951: "
                f"erwartet O=118/P=537/Total=655, erhalten {values}"
            )

    print()
    if errors:
        print("❌ REGRESSIONSTEST FEHLGESCHLAGEN")
        for error in errors:
            print(f" - {error}")
        sys.exit(1)

    print("✅ REGRESSIONSTEST ERFOLGREICH")
    print(
        "85 Records · 44 Entitäten · 0 Warnungen · "
        "0 unmatched · 0 ambiguous"
    )


if __name__ == "__main__":
    main()
