#!/usr/bin/env python3
r"""
Statischer IIIF Image API 3 / Level-0-Generator
================================================

Dieses Skript erzeugt aus den historischen Originalbildern mit libvips:

    iiif/<identifier>/info.json
    iiif/<identifier>/<region>/<size>/0/default.jpg

Die Ausgabe ist statisch und kann mit einem normalen HTTP-Server ausgeliefert
werden. Es ist kein dauerhaft laufender IIIF-Server nötig.

Standard-Workflow unter Windows / PowerShell:

    py .\generate_iiif.py --check
    py .\generate_iiif.py --dry-run
    py .\generate_iiif.py
    py .\export_nodegoat_for_web.py
    py -m http.server 8000

Standardmässige lokale IIIF-Basis-URL:

    http://localhost:8000/iiif

Für eine spätere öffentliche Website einfach neu erzeugen:

    py .\generate_iiif.py --base-url https://DEINE-DOMAIN/iiif --force

Voraussetzung:
    libvips mit dem Kommando vips / vips.exe

Das Skript kann alternativ einen expliziten Pfad erhalten:

    py .\generate_iiif.py --vips "C:\Tools\vips\bin\vips.exe"
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from typing import Any


# ============================================================
# KONFIGURATION
# ============================================================

DEFAULT_BASE_URL = "http://localhost:8000/iiif"

JSON_DIRS = (
    Path("data/RAW"),
    Path("data/sources"),
)

IMAGE_DIRS = (
    Path("assets/sources"),
    Path("assets/workflow"),
    Path("data/RAW"),
    Path("data/sources"),
)

IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
)

OUTPUT_DIR = Path("iiif")
OVERRIDES_PATH = Path("data/iiif-overrides.json")
MANIFEST_PATH = Path("data/iiif-build-manifest.json")


# ============================================================
# DATENMODELL
# ============================================================

@dataclass(frozen=True)
class SourcePair:
    document: str
    json_path: Path
    image_path: Path
    identifier: str


@dataclass
class BuildResult:
    document: str
    identifier: str
    source_json: str
    source_image: str
    info_json: str
    service_id: str
    status: str
    width: int | None = None
    height: int | None = None


# ============================================================
# ALLGEMEINE HILFSFUNKTIONEN
# ============================================================

def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return None


def write_json_atomic(
    path: Path,
    payload: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp = path.with_suffix(
        path.suffix + ".tmp"
    )

    temp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temp.replace(path)


def normalise_stem(value: str) -> str:
    name = Path(
        str(value).strip()
    ).name

    lowered = name.lower()

    for suffix in (
        ".json",
        *IMAGE_EXTENSIONS,
    ):
        if lowered.endswith(suffix):
            return name[
                :-len(suffix)
            ]

    return name


def safe_identifier(value: str) -> str:
    """
    Erzeugt URL- und Windows-freundliche IIIF-Identifier.

    Beispiel:
        Se_23_Assemblée_1951_page_2
        -> Se_23_Assemblee_1951_page_2
    """
    value = unicodedata.normalize(
        "NFKD",
        value,
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(
            char
        )
    )

    value = value.encode(
        "ascii",
        errors="ignore",
    ).decode(
        "ascii"
    )

    value = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        value,
    )

    value = re.sub(
        r"_+",
        "_",
        value,
    )

    value = value.strip(
        "._-"
    )

    return (
        value
        or "source"
    )


def relative_web_path(
    path: Path,
    project_root: Path,
) -> str:
    return path.resolve().relative_to(
        project_root.resolve()
    ).as_posix()


# ============================================================
# DATEIEN FINDEN
# ============================================================

def iter_json_files(
    project_root: Path,
):
    seen: set[Path] = set()

    for relative_dir in JSON_DIRS:
        directory = (
            project_root /
            relative_dir
        )

        if not directory.exists():
            continue

        for path in directory.glob(
            "*.json"
        ):
            resolved = path.resolve()

            if resolved in seen:
                continue

            seen.add(resolved)

            # Nur Quelldaten, keine Projekt-Metadaten.
            if path.name in {
                "gv-metadata.json",
                "geocoded.json",
                "site-data.json",
                "iiif-overrides.json",
                "iiif-build-manifest.json",
                "nominatim-cache.json",
                "geocoding-overrides.json",
            }:
                continue

            yield path


def image_index(
    project_root: Path,
) -> dict[str, Path]:
    """
    Index wird einmal aufgebaut, damit wir nicht pro JSON-Datei
    sämtliche Bildordner erneut durchsuchen.
    """
    index: dict[
        str,
        Path
    ] = {}

    for relative_dir in IMAGE_DIRS:
        directory = (
            project_root /
            relative_dir
        )

        if not directory.exists():
            continue

        for path in directory.iterdir():
            if (
                not path.is_file() or
                path.suffix.lower()
                not in IMAGE_EXTENSIONS
            ):
                continue

            key = path.stem.casefold()

            # Der zuerst gefundene explizitere Ordner gewinnt.
            index.setdefault(
                key,
                path
            )

    return index


def discover_sources(
    project_root: Path,
) -> tuple[
    list[SourcePair],
    list[dict[str, str]],
]:
    images = image_index(
        project_root
    )

    pairs: list[
        SourcePair
    ] = []

    missing: list[
        dict[str, str]
    ] = []

    identifiers: dict[
        str,
        str
    ] = {}

    seen_documents: set[
        str
    ] = set()

    for json_path in iter_json_files(
        project_root
    ):
        data = load_json(
            json_path
        )

        if not isinstance(
            data,
            dict
        ):
            continue

        document = str(
            data.get(
                "document"
            ) or
            json_path.stem
        ).strip()

        json_stem = json_path.stem
        document_stem = normalise_stem(
            document
        )

        candidates = [
            document_stem,
            json_stem,
        ]

        image_path = None

        for candidate in candidates:
            image_path = images.get(
                candidate.casefold()
            )

            if image_path:
                break

        if not image_path:
            missing.append({
                "document":
                    document_stem,
                "json":
                    relative_web_path(
                        json_path,
                        project_root,
                    ),
            })
            continue

        document_key = (
            document_stem.casefold()
        )

        if document_key in seen_documents:
            continue

        seen_documents.add(
            document_key
        )

        identifier = safe_identifier(
            document_stem
        )

        owner = identifiers.get(
            identifier.casefold()
        )

        if (
            owner and
            owner.casefold() !=
            document_stem.casefold()
        ):
            # Sehr unwahrscheinliche Slug-Kollision
            # deterministisch vermeiden.
            short = abs(
                hash(document_stem)
            ) % 1_000_000

            identifier = (
                f"{identifier}_{short:06d}"
            )

        identifiers[
            identifier.casefold()
        ] = document_stem

        pairs.append(
            SourcePair(
                document=document_stem,
                json_path=json_path,
                image_path=image_path,
                identifier=identifier,
            )
        )

    pairs.sort(
        key=lambda item:
            item.document.casefold()
    )

    return (
        pairs,
        missing
    )


# ============================================================
# LIBVIPS
# ============================================================

def resolve_vips(
    explicit: str | None,
    project_root: Path,
) -> Path | None:
    candidates = []

    if explicit:
        candidates.append(
            Path(explicit)
        )

    env_path = os.environ.get(
        "VIPS_BIN",
        ""
    ).strip()

    if env_path:
        candidates.append(
            Path(env_path)
        )

    for relative in (
        Path("tools/libvips/bin/vips.exe"),
        Path("libvips/bin/vips.exe"),
        Path("tools/vips/bin/vips.exe"),
    ):
        candidates.append(
            project_root /
            relative
        )

    which = shutil.which(
        "vips"
    )

    if which:
        candidates.append(
            Path(which)
        )

    which_exe = shutil.which(
        "vips.exe"
    )

    if which_exe:
        candidates.append(
            Path(which_exe)
        )

    for path in candidates:
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue

    return None


def vips_version(
    executable: Path
) -> str:
    result = subprocess.run(
        [
            str(executable),
            "--version",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )

    if result.returncode != 0:
        return ""

    return (
        result.stdout.strip()
        or result.stderr.strip()
    )


def build_command(
    vips: Path,
    pair: SourcePair,
    output_path: Path,
    base_url: str,
    tile_size: int,
    quality: int,
) -> list[str]:
    base_url = base_url.rstrip("/")

    return [
        str(vips),
        "dzsave",
        str(pair.image_path),
        str(output_path),
        "--layout",
        "iiif3",
        "--basename",
        pair.identifier,
        "--id",
        base_url,
        "--tile-size",
        str(tile_size),
        "--overlap",
        "0",
        "--suffix",
        f".jpg[Q={quality}]",
    ]


# ============================================================
# IIIF BUILD
# ============================================================

def validate_info_json(
    path: Path,
    expected_id: str,
) -> tuple[
    bool,
    str,
    int | None,
    int | None,
]:
    data = load_json(
        path
    )

    if not isinstance(
        data,
        dict
    ):
        return (
            False,
            "info.json ist kein JSON-Objekt.",
            None,
            None,
        )

    if data.get(
        "type"
    ) != "ImageService3":
        return (
            False,
            "type ist nicht ImageService3.",
            None,
            None,
        )

    if data.get(
        "profile"
    ) != "level0":
        return (
            False,
            "profile ist nicht level0.",
            None,
            None,
        )

    actual_id = str(
        data.get(
            "id",
            ""
        )
    ).rstrip("/")

    if (
        actual_id !=
        expected_id.rstrip("/")
    ):
        return (
            False,
            (
                "IIIF service id stimmt nicht: "
                f"{actual_id!r} != "
                f"{expected_id!r}"
            ),
            None,
            None,
        )

    width = data.get(
        "width"
    )

    height = data.get(
        "height"
    )

    if not isinstance(
        width,
        int
    ) or not isinstance(
        height,
        int
    ):
        return (
            False,
            "width/height fehlen in info.json.",
            None,
            None,
        )

    tiles = data.get(
        "tiles"
    )

    if not isinstance(
        tiles,
        list
    ) or not tiles:
        return (
            False,
            "tiles fehlen in info.json.",
            width,
            height,
        )

    return (
        True,
        "",
        width,
        height,
    )


def build_one(
    project_root: Path,
    vips: Path,
    pair: SourcePair,
    base_url: str,
    tile_size: int,
    quality: int,
    force: bool,
) -> BuildResult:
    output_root = (
        project_root /
        OUTPUT_DIR
    )

    final_dir = (
        output_root /
        pair.identifier
    )

    service_id = (
        f"{base_url.rstrip('/')}/"
        f"{pair.identifier}"
    )

    info_path = (
        final_dir /
        "info.json"
    )

    if (
        final_dir.exists() and
        not force
    ):
        valid, error, width, height = (
            validate_info_json(
                info_path,
                service_id,
            )
        )

        if valid:
            return BuildResult(
                document=
                    pair.document,
                identifier=
                    pair.identifier,
                source_json=
                    relative_web_path(
                        pair.json_path,
                        project_root,
                    ),
                source_image=
                    relative_web_path(
                        pair.image_path,
                        project_root,
                    ),
                info_json=
                    relative_web_path(
                        info_path,
                        project_root,
                    ),
                service_id=
                    service_id,
                status=
                    "existing",
                width=
                    width,
                height=
                    height,
            )

        raise RuntimeError(
            f"{final_dir} existiert bereits, "
            f"ist aber kein gültiger Build:\n{error}\n"
            "Nutze --force zum Neuerzeugen."
        )

    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    if final_dir.exists():
        shutil.rmtree(
            final_dir
        )

    command = build_command(
        vips=vips,
        pair=pair,
        output_path=final_dir,
        base_url=base_url,
        tile_size=tile_size,
        quality=quality,
    )

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        if final_dir.exists():
            shutil.rmtree(
                final_dir,
                ignore_errors=True,
            )

        raise RuntimeError(
            "libvips dzsave ist fehlgeschlagen:\n\n"
            + " ".join(command)
            + "\n\nSTDOUT:\n"
            + result.stdout
            + "\nSTDERR:\n"
            + result.stderr
        )

    valid, error, width, height = (
        validate_info_json(
            info_path,
            service_id,
        )
    )

    if not valid:
        raise RuntimeError(
            f"Ungültiges IIIF-Ergebnis für "
            f"{pair.document}:\n{error}"
        )

    return BuildResult(
        document=
            pair.document,
        identifier=
            pair.identifier,
        source_json=
            relative_web_path(
                pair.json_path,
                project_root,
            ),
        source_image=
            relative_web_path(
                pair.image_path,
                project_root,
            ),
        info_json=
            relative_web_path(
                info_path,
                project_root,
            ),
        service_id=
            service_id,
        status=
            "generated",
        width=
            width,
        height=
            height,
    )


def build_overrides(
    results: list[BuildResult]
) -> dict[str, Any]:
    """
    Der bestehende nodegoat-Webexport liest diese Datei automatisch.
    Deshalb ist keine manuelle Pflege der IIIF-URLs nötig.
    """
    overrides: dict[
        str,
        Any
    ] = {}

    for result in results:
        info_url = (
            result.info_json
        )

        payload = {
            "info_json":
                info_url,
            "service_id":
                result.service_id,
            "generated":
                True,
        }

        for key in (
            result.document,
            result.identifier,
            Path(
                result.source_json
            ).name,
            Path(
                result.source_json
            ).stem,
        ):
            if key:
                overrides[
                    key
                ] = payload

    return overrides


# ============================================================
# AUSGABE / CLI
# ============================================================

def print_discovery(
    pairs: list[SourcePair],
    missing: list[dict[str, str]],
    project_root: Path,
) -> None:
    print()
    print(
        "Gefundene Quellenpaare:"
    )

    if not pairs:
        print(
            "  Keine Bild/JSON-Paare gefunden."
        )

    for pair in pairs:
        print(
            "  OK "
            f"{pair.document}"
        )
        print(
            "     JSON: "
            + relative_web_path(
                pair.json_path,
                project_root,
            )
        )
        print(
            "     Bild: "
            + relative_web_path(
                pair.image_path,
                project_root,
            )
        )
        print(
            "     IIIF: "
            f"iiif/{pair.identifier}/info.json"
        )

    if missing:
        print()
        print(
            "JSON-Dateien ohne passendes Originalbild:"
        )

        for item in missing:
            print(
                "  - "
                f"{item['document']} "
                f"({item['json']})"
            )


def self_test() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(
            temp_dir
        )

        (
            root /
            "data/RAW"
        ).mkdir(
            parents=True
        )

        (
            root /
            "assets/sources"
        ).mkdir(
            parents=True
        )

        json_path = (
            root /
            "data/RAW/"
            "Se_23_Assemblee_page_2.json"
        )

        json_path.write_text(
            json.dumps(
                {
                    "document":
                        "Se_23_Assemblée_page_2",
                    "entries": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        image_path = (
            root /
            "assets/sources/"
            "Se_23_Assemblée_page_2.jpg"
        )

        image_path.write_bytes(
            b"test-image-placeholder"
        )

        pairs, missing = discover_sources(
            root
        )

        assert len(
            pairs
        ) == 1

        assert not missing

        pair = pairs[0]

        assert pair.document == (
            "Se_23_Assemblée_page_2"
        )

        assert pair.identifier == (
            "Se_23_Assemblee_page_2"
        )

        assert pair.image_path == (
            image_path
        )

        fake_result = BuildResult(
            document=
                pair.document,
            identifier=
                pair.identifier,
            source_json=
                "data/RAW/x.json",
            source_image=
                "assets/sources/x.jpg",
            info_json=
                "iiif/x/info.json",
            service_id=
                "http://localhost:8000/iiif/x",
            status=
                "generated",
        )

        overrides = build_overrides(
            [fake_result]
        )

        assert (
            overrides[
                pair.document
            ][
                "info_json"
            ]
            == "iiif/x/info.json"
        )

    print(
        "Self-Test erfolgreich."
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Erzeugt statische IIIF Image API 3 "
            "Level-0-Bildpyramiden mit libvips."
        )
    )

    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=(
            "Öffentliche Basis-URL des IIIF-Verzeichnisses. "
            f"Standard: {DEFAULT_BASE_URL}"
        ),
    )

    parser.add_argument(
        "--vips",
        help=(
            "Expliziter Pfad zu vips oder vips.exe."
        ),
    )

    parser.add_argument(
        "--tile-size",
        type=int,
        default=512,
    )

    parser.add_argument(
        "--quality",
        type=int,
        default=90,
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Bestehende IIIF-Builds neu erzeugen."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Nur Quelldateien finden; nichts erzeugen."
        ),
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Prüft Quellendateien und libvips-Installation."
        ),
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
    )

    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    if not (
        128 <=
        args.tile_size <=
        2048
    ):
        parser.error(
            "--tile-size muss zwischen 128 und 2048 liegen."
        )

    if not (
        1 <=
        args.quality <=
        100
    ):
        parser.error(
            "--quality muss zwischen 1 und 100 liegen."
        )

    project_root = (
        Path.cwd().resolve()
    )

    pairs, missing = discover_sources(
        project_root
    )

    print_discovery(
        pairs,
        missing,
        project_root,
    )

    vips = resolve_vips(
        args.vips,
        project_root,
    )

    print()
    print(
        "libvips:"
    )

    if vips:
        print(
            f"  {vips}"
        )

        version = vips_version(
            vips
        )

        if version:
            print(
                f"  {version}"
            )
    else:
        print(
            "  NICHT GEFUNDEN"
        )

    if args.check:
        print()

        if pairs and vips:
            print(
                "IIIF-Setup ist bereit."
            )
            return

        if not pairs:
            print(
                "Es wurden noch keine passenden "
                "Bild/JSON-Paare gefunden."
            )

        if not vips:
            print(
                "libvips fehlt bzw. vips.exe ist nicht im PATH."
            )

        sys.exit(1)

    if args.dry_run:
        print()
        print(
            "Dry Run abgeschlossen. "
            "Es wurden keine Dateien verändert."
        )
        return

    if not pairs:
        print()
        print(
            "FEHLER: Keine Bild/JSON-Paare gefunden."
        )
        sys.exit(2)

    if not vips:
        print()
        print(
            "FEHLER: libvips wurde nicht gefunden."
        )
        print()
        print(
            "Installiere die Windows-Binaries von libvips "
            "und füge deren bin-Ordner zum PATH hinzu."
        )
        print(
            "Alternativ:"
        )
        print(
            r'  py .\generate_iiif.py --vips '
            r'"C:\PFAD\ZU\vips\bin\vips.exe"'
        )
        sys.exit(3)

    results: list[
        BuildResult
    ] = []

    print()
    print("=" * 72)
    print(
        "STATISCHES IIIF WIRD ERZEUGT"
    )
    print("=" * 72)

    for index, pair in enumerate(
        pairs,
        start=1,
    ):
        print(
            f"[{index}/{len(pairs)}] "
            f"{pair.document}"
        )

        result = build_one(
            project_root=
                project_root,
            vips=
                vips,
            pair=
                pair,
            base_url=
                args.base_url,
            tile_size=
                args.tile_size,
            quality=
                args.quality,
            force=
                args.force,
        )

        results.append(
            result
        )

        print(
            f"    {result.status}: "
            f"{result.info_json}"
        )

    overrides = build_overrides(
        results
    )

    write_json_atomic(
        project_root /
        OVERRIDES_PATH,
        overrides,
    )

    manifest = {
        "iiif_version":
            "Image API 3",
        "profile":
            "level0",
        "base_url":
            args.base_url.rstrip(
                "/"
            ),
        "tile_size":
            args.tile_size,
        "jpeg_quality":
            args.quality,
        "source_count":
            len(results),
        "sources":
            [
                asdict(
                    result
                )
                for result in results
            ],
        "unmatched_json":
            missing,
    }

    write_json_atomic(
        project_root /
        MANIFEST_PATH,
        manifest,
    )

    generated = sum(
        1
        for result in results
        if result.status ==
        "generated"
    )

    existing = sum(
        1
        for result in results
        if result.status ==
        "existing"
    )

    print()
    print("=" * 72)
    print(
        "IIIF BUILD ERFOLGREICH"
    )
    print("=" * 72)
    print(
        f"Quellen insgesamt: {len(results)}"
    )
    print(
        f"Neu erzeugt:       {generated}"
    )
    print(
        f"Bereits vorhanden: {existing}"
    )
    print(
        f"Overrides:          {OVERRIDES_PATH}"
    )
    print(
        f"Manifest:           {MANIFEST_PATH}"
    )
    print()
    print(
        "Nächster Schritt:"
    )
    print(
        r"  py .\export_nodegoat_for_web.py"
    )
    print()
    print(
        "Danach:"
    )
    print(
        r"  py -m http.server 8000"
    )


if __name__ == "__main__":
    main()
