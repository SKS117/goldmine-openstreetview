#!/usr/bin/env python3
"""
Prüft, ob die für die Abgabe benötigten statischen Website-Dateien vorhanden
und intern weitgehend konsistent sind.

Keine externen Python-Pakete nötig.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent

REQUIRED = (
    "index.html",
    "style.css",
    "app.js",
    "README.md",
    "start_server.py",
    "data/site-data.json",
    "iiif",
)


def existing_local_path(value: str) -> bool | None:
    if not value:
        return None

    parsed = urlparse(value)

    if parsed.scheme in {
        "http",
        "https",
    }:
        return None

    return (
        ROOT /
        value
    ).exists()


def main() -> int:
    print()
    print("=" * 72)
    print("REPOSITORY-CHECK")
    print("=" * 72)

    errors = []
    warnings = []

    for relative in REQUIRED:
        if not (
            ROOT /
            relative
        ).exists():
            errors.append(
                f"Fehlt: {relative}"
            )

    site_path = (
        ROOT /
        "data/site-data.json"
    )

    if site_path.exists():
        try:
            site = json.loads(
                site_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as error:
            errors.append(
                f"site-data.json ist ungültig: {error}"
            )
            site = {}
    else:
        site = {}

    gv_metadata = site.get(
        "gv_metadata",
        {}
    )

    source_pages = []

    if isinstance(
        gv_metadata,
        dict,
    ):
        for gv_id, info in gv_metadata.items():
            if not isinstance(
                info,
                dict,
            ):
                continue

            for page in info.get(
                "source_pages",
                [],
            ):
                if isinstance(
                    page,
                    dict,
                ):
                    source_pages.append(
                        (
                            gv_id,
                            page,
                        )
                    )

    for gv_id, page in source_pages:
        for field in (
            "json_url",
            "image_url",
            "iiif_info_url",
        ):
            value = str(
                page.get(
                    field,
                    ""
                )
            ).strip()

            if not value:
                continue

            exists = existing_local_path(
                value
            )

            if exists is False:
                errors.append(
                    f"{gv_id}: {field} fehlt lokal: {value}"
                )

    iiif_dir = (
        ROOT /
        "iiif"
    )

    info_files = (
        list(
            iiif_dir.rglob(
                "info.json"
            )
        )
        if iiif_dir.exists()
        else []
    )

    for info_path in info_files:
        try:
            info = json.loads(
                info_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as error:
            errors.append(
                f"Ungültiges IIIF info.json: "
                f"{info_path.relative_to(ROOT)} ({error})"
            )
            continue

        service_id = str(
            info.get(
                "id",
                ""
            )
        )

        if (
            service_id and
            not service_id.startswith(
                "http://localhost:8000/iiif/"
            )
        ):
            warnings.append(
                "IIIF-Service-ID verwendet nicht "
                f"localhost:8000: {service_id}"
            )

    secret_candidates = (
        ".env",
        ".env.local",
        "secrets.json",
        "secret.json",
        "token.txt",
    )

    for name in secret_candidates:
        if (
            ROOT /
            name
        ).exists():
            warnings.append(
                f"Mögliche Secret-Datei im Repository: {name}"
            )

    print(
        f"Generalversammlungen in site-data.json: "
        f"{len(gv_metadata) if isinstance(gv_metadata, dict) else 0}"
    )
    print(
        f"Verknüpfte digitale Quellenseiten: {len(source_pages)}"
    )
    print(
        f"IIIF info.json-Dateien: {len(info_files)}"
    )

    if warnings:
        print()
        print("WARNUNGEN:")

        for warning in warnings:
            print(
                f"  - {warning}"
            )

    if errors:
        print()
        print("FEHLER:")

        for error in errors:
            print(
                f"  - {error}"
            )

        print()
        print("REPOSITORY NOCH NICHT ABGABEBEREIT.")
        return 1

    print()
    print("REPOSITORY-CHECK ERFOLGREICH.")
    print(
        "Die statische Webansicht ist strukturell abgabebereit."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
