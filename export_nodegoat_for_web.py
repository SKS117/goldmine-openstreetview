#!/usr/bin/env python3
r"""
Exportiert die normalisierten Forschungsdaten aus nodegoat in eine einzige,
browserfreundliche Datei:

    data/site-data.json

Die Website greift NICHT direkt auf die nodegoat API zu.
Der Bearer-Token bleibt ausschliesslich in der lokalen Shell.

Aufruf:
    $env:NODEGOAT_TOKEN = "..."
    py .\export_nodegoat_for_web.py

Optional:
    py .\export_nodegoat_for_web.py --self-test
    py .\export_nodegoat_for_web.py --output data\site-data.json
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# ============================================================
# NODEGOAT / PROJEKT
# ============================================================

API_HOST = "https://api.nodegoat.dasch.swiss"
PROJECT_ID = 3045

TYPE_PERSON = 11870
TYPE_GV = 11877

# Orts-/City-Objekte, auf die nodegoat-Locations als Referenz zeigen.
# Dieser Type wird bereits vom Feld "Ort" der Generalversammlung verwendet.
TYPE_LOCATION = 11337

# Person2: Object Descriptions
OD_LAST_NAME = 35119
OD_FIRST_NAME = 35120

# Person2: Sub-Object Details / Descriptions
SD_WOHNORT = 12436
SOD_WOHNORT = 9849

SD_AKTIEN_TOTAL = 12437
SOD_AKTIEN_TOTAL = 9850

SD_AKTIEN_P = 12438
SOD_AKTIEN_P = 9851

SD_AKTIEN_O = 12439
SOD_AKTIEN_O = 9852

SD_ANWESENHEIT = 12455
SOD_ANWESEND = 9863
SOD_VERTRETEN_DURCH = 9864

# Generalversammlung 2: Object Descriptions
OD_GV_DATUM = 35145
OD_GV_ORT = 35146
OD_GV_TOTAL = 35147
OD_GV_TOTAL_O = 35148
OD_GV_TOTAL_P = 35149
OD_GV_QUELLE = 35150

PAGE_SIZE = 1000


# ============================================================
# ALLGEMEINE HILFSFUNKTIONEN
# ============================================================

def iter_values(value: Any):
    """Erlaubt sowohl nodegoat-Dictionaries als auch Listen."""
    if value is None:
        return []

    if isinstance(value, dict):
        return value.values()

    if isinstance(value, list):
        return value

    return []


def first_present(mapping: dict[str, Any] | None, *keys: str):
    if not isinstance(mapping, dict):
        return None

    for key in keys:
        value = mapping.get(key)

        if value not in (None, ""):
            return value

    return None


def text_value(value: Any) -> str:
    """
    Macht typische nodegoat-Textwerte browserfreundlich.
    text_tags kann je nach Konfiguration als String, Liste oder Dictionary
    zurückkommen.
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, (int, float, bool)):
        return str(value)

    if isinstance(value, list):
        parts = [
            text_value(item)
            for item in value
        ]

        return "; ".join(
            part
            for part in parts
            if part
        )

    if isinstance(value, dict):
        for key in (
            "value",
            "text",
            "label",
            "name"
        ):
            if key in value:
                resolved = text_value(
                    value[key]
                )

                if resolved:
                    return resolved

        parts = [
            text_value(item)
            for item in value.values()
        ]

        return "; ".join(
            part
            for part in parts
            if part
        )

    return str(value).strip()


def number_value(value: Any) -> int | float | None:
    if value in (None, ""):
        return None

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, (int, float)):
        return value

    match = re.search(
        r"-?\d+(?:[.,]\d+)?",
        str(value)
    )

    if not match:
        return None

    number = match.group(0).replace(
        ",",
        "."
    )

    parsed = float(number)

    return (
        int(parsed)
        if parsed.is_integer()
        else parsed
    )


def bool_value(value: Any) -> bool | None:
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    lowered = str(value).strip().lower()

    if lowered in {
        "1",
        "true",
        "yes",
        "ja"
    }:
        return True

    if lowered in {
        "0",
        "false",
        "no",
        "nein",
        ""
    }:
        return False

    return None


def normalise_raw_date(value: Any) -> str:
    """
    Kanonischer Schlüssel für den Abgleich von GV- und Sub-Object-Daten.

    Beispiele:
        19681130     -> 19681130
        "1968-11-30" -> 19681130
        1951         -> 19510000
        "1951"       -> 19510000
        "1968-11"    -> 19681100
    """
    if value in (None, ""):
        return ""

    raw = str(value).strip()

    negative = raw.startswith("-")

    digits = re.sub(
        r"\D",
        "",
        raw
    )

    if not digits:
        return ""

    if len(digits) == 4:
        digits += "0000"

    elif len(digits) == 6:
        digits += "00"

    elif len(digits) < 8:
        digits = digits.ljust(
            8,
            "0"
        )

    elif len(digits) > 8:
        digits = digits[:8]

    return (
        f"-{digits}"
        if negative
        else digits
    )


def nodegoat_date(value: Any) -> dict[str, Any]:
    """
    nodegoat liefert historische Datumswerte üblicherweise als YYYYMMDD.
    Bei unbekanntem Monat/Tag können Nullen vorkommen, z.B. 19510000.
    """
    raw = normalise_raw_date(value)

    if not raw:
        return {
            "raw": "",
            "iso": "",
            "year": None,
        }

    negative = raw.startswith("-")

    if negative:
        raw_digits = raw[1:]
    else:
        raw_digits = raw

    if not raw_digits.isdigit():
        return {
            "raw": raw,
            "iso": str(value),
            "year": None,
        }

    raw_digits = raw_digits.zfill(8)

    year = int(raw_digits[:4])
    month = int(raw_digits[4:6])
    day = int(raw_digits[6:8])

    if negative:
        year = -year

    if month == 0:
        iso = str(year)

    elif day == 0:
        iso = (
            f"{year:04d}-"
            f"{month:02d}"
        )

    else:
        iso = (
            f"{year:04d}-"
            f"{month:02d}-"
            f"{day:02d}"
        )

    return {
        "raw": raw,
        "iso": iso,
        "year": year,
    }


def object_definitions(pack: dict[str, Any]):
    return iter_values(
        pack.get(
            "object_definitions"
        )
    )


def definition(
    pack: dict[str, Any],
    description_id: int
) -> dict[str, Any] | None:
    for item in object_definitions(
        pack
    ):
        if not isinstance(item, dict):
            continue

        if int(
            item.get(
                "object_description_id",
                -1
            )
        ) == description_id:
            return item

    return None


def definition_value(
    pack: dict[str, Any],
    description_id: int
) -> Any:
    item = definition(
        pack,
        description_id
    )

    if not item:
        return None

    return first_present(
        item,
        "object_definition_value",
        "object_definition_ref_object_name",
        "object_definition_ref_object_id",
    )


def sub_definitions(
    sub_pack: dict[str, Any]
):
    return iter_values(
        sub_pack.get(
            "object_sub_definitions"
        )
    )


def sub_definition(
    sub_pack: dict[str, Any],
    description_id: int
) -> dict[str, Any] | None:
    for item in sub_definitions(
        sub_pack
    ):
        if not isinstance(item, dict):
            continue

        if int(
            item.get(
                "object_sub_description_id",
                -1
            )
        ) == description_id:
            return item

    return None


def sub_definition_value(
    sub_pack: dict[str, Any],
    description_id: int
) -> Any:
    item = sub_definition(
        sub_pack,
        description_id
    )

    if not item:
        return None

    return first_present(
        item,
        "object_sub_definition_value",
        "object_sub_definition_ref_object_name",
        "object_sub_definition_ref_object_id",
    )


def object_name(
    object_id: str,
    pack: dict[str, Any]
) -> str:
    obj = pack.get(
        "object",
        {}
    )

    name = first_present(
        obj,
        "object_name",
        "object_name_plain",
        "name"
    )

    if name:
        return text_value(name)

    first = text_value(
        definition_value(
            pack,
            OD_FIRST_NAME
        )
    )

    last = text_value(
        definition_value(
            pack,
            OD_LAST_NAME
        )
    )

    combined = " ".join(
        part
        for part in (
            first,
            last
        )
        if part
    ).strip()

    return (
        combined
        or f"nodegoat object {object_id}"
    )


def sub_object(
    sub_pack: dict[str, Any]
) -> dict[str, Any]:
    value = sub_pack.get(
        "object_sub"
    )

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def sub_detail_id(
    sub_pack: dict[str, Any]
) -> int | None:
    value = sub_object(
        sub_pack
    ).get(
        "object_sub_details_id"
    )

    try:
        return int(value)

    except (
        TypeError,
        ValueError
    ):
        return None


def sub_date_raw(
    sub_pack: dict[str, Any]
) -> str:
    sub = sub_object(
        sub_pack
    )

    return normalise_raw_date(
        first_present(
            sub,
            "object_sub_date_start",
            "object_sub_date_end",
        )
    )


def sub_ref_object_id(
    sub_pack: dict[str, Any]
) -> str | None:
    sub = sub_object(
        sub_pack
    )

    value = first_present(
        sub,
        "object_sub_location_ref_object_id",
        "object_sub_location_latlong_ref_object_id",
    )

    if value in (None, ""):
        return None

    return str(value)


def sub_coordinates(
    sub_pack: dict[str, Any]
) -> tuple[float | None, float | None]:
    """
    Unterstützt sowohl ältere lat/long-Ausgaben als auch Geometrien.
    Rückgabe: (lat, lon)
    """
    sub = sub_object(
        sub_pack
    )

    lat = number_value(
        first_present(
            sub,
            "object_sub_location_lat",
            "lat"
        )
    )

    lon = number_value(
        first_present(
            sub,
            "object_sub_location_long",
            "object_sub_location_lon",
            "long",
            "lon"
        )
    )

    if (
        lat is not None and
        lon is not None
    ):
        return (
            float(lat),
            float(lon)
        )

    geometry = first_present(
        sub,
        "object_sub_location_geometry",
        "geometry"
    )

    if geometry is None:
        return (
            None,
            None
        )

    if isinstance(
        geometry,
        str
    ):
        stripped = geometry.strip()

        if stripped.startswith(
            ("[", "{")
        ):
            try:
                geometry = json.loads(
                    stripped
                )

            except json.JSONDecodeError:
                geometry = stripped

        else:
            match = re.search(
                r"POINT\s*\(\s*"
                r"(-?\d+(?:\.\d+)?)"
                r"\s+"
                r"(-?\d+(?:\.\d+)?)"
                r"\s*\)",
                stripped,
                re.I
            )

            if match:
                return (
                    float(
                        match.group(2)
                    ),
                    float(
                        match.group(1)
                    )
                )

    coordinates = None

    if (
        isinstance(
            geometry,
            dict
        ) and
        isinstance(
            geometry.get(
                "coordinates"
            ),
            (list, tuple)
        )
    ):
        coordinates = geometry[
            "coordinates"
        ]

    elif isinstance(
        geometry,
        (list, tuple)
    ):
        coordinates = geometry

    if (
        coordinates and
        len(coordinates) >= 2
    ):
        lon = number_value(
            coordinates[0]
        )

        lat = number_value(
            coordinates[1]
        )

        if (
            lat is not None and
            lon is not None
        ):
            return (
                float(lat),
                float(lon)
            )

    return (
        None,
        None
    )


def ref_name(
    sub_pack: dict[str, Any]
) -> str:
    sub = sub_object(
        sub_pack
    )

    return text_value(
        first_present(
            sub,
            "object_sub_location_ref_object_name",
            "object_sub_location_latlong_ref_object_name",
        )
    )


def geometry_coordinates(
    geometry: Any
) -> tuple[float | None, float | None]:
    """
    Liest GeoJSON, [lon, lat] oder WKT POINT.
    Rückgabe: (lat, lon)
    """
    if geometry in (None, ""):
        return (
            None,
            None
        )

    if isinstance(
        geometry,
        str
    ):
        stripped = geometry.strip()

        if stripped.startswith(
            ("[", "{")
        ):
            try:
                geometry = json.loads(
                    stripped
                )

            except json.JSONDecodeError:
                pass

        if isinstance(
            geometry,
            str
        ):
            match = re.search(
                r"POINT\s*\(\s*"
                r"(-?\d+(?:\.\d+)?)"
                r"\s+"
                r"(-?\d+(?:\.\d+)?)"
                r"\s*\)",
                geometry,
                re.I
            )

            if match:
                return (
                    float(
                        match.group(2)
                    ),
                    float(
                        match.group(1)
                    )
                )

    coordinates = None

    if (
        isinstance(
            geometry,
            dict
        ) and
        isinstance(
            geometry.get(
                "coordinates"
            ),
            (list, tuple)
        )
    ):
        coordinates = geometry[
            "coordinates"
        ]

    elif isinstance(
        geometry,
        (list, tuple)
    ):
        coordinates = geometry

    if (
        coordinates and
        len(coordinates) >= 2 and
        not isinstance(
            coordinates[0],
            (list, tuple, dict)
        )
    ):
        lon = number_value(
            coordinates[0]
        )
        lat = number_value(
            coordinates[1]
        )

        if (
            lat is not None and
            lon is not None and
            -90 <= float(lat) <= 90 and
            -180 <= float(lon) <= 180
        ):
            return (
                float(lat),
                float(lon)
            )

    return (
        None,
        None
    )


def find_coordinates_deep(
    value: Any
) -> tuple[float | None, float | None]:
    """
    Referenzierte City-/Location-Objekte können ihre Geometrie an
    verschiedenen Stellen der nodegoat-Antwort tragen. Deshalb wird
    das Objekt rekursiv nach expliziten Location-/Geometry-Feldern
    durchsucht.

    Es werden nur eindeutig als Koordinaten benannte Felder verwendet;
    normale numerische Forschungsdaten werden ignoriert.
    """
    if isinstance(
        value,
        dict
    ):
        # Typische direkte lat/lon-Paare.
        lat = number_value(
            first_present(
                value,
                "object_sub_location_lat",
                "object_location_lat",
                "location_lat",
                "latitude",
                "lat",
            )
        )

        lon = number_value(
            first_present(
                value,
                "object_sub_location_long",
                "object_sub_location_lon",
                "object_location_long",
                "object_location_lon",
                "location_long",
                "location_lon",
                "longitude",
                "long",
                "lon",
            )
        )

        if (
            lat is not None and
            lon is not None and
            -90 <= float(lat) <= 90 and
            -180 <= float(lon) <= 180
        ):
            return (
                float(lat),
                float(lon)
            )

        # Explizite Geometriefelder.
        for key in (
            "object_sub_location_geometry",
            "object_location_geometry",
            "location_geometry",
            "geometry",
        ):
            if key in value:
                lat, lon = geometry_coordinates(
                    value[key]
                )

                if (
                    lat is not None and
                    lon is not None
                ):
                    return (
                        lat,
                        lon
                    )

        # Rekursiv nur dann weitersuchen, wenn oben nichts gefunden wurde.
        for child in value.values():
            lat, lon = find_coordinates_deep(
                child
            )

            if (
                lat is not None and
                lon is not None
            ):
                return (
                    lat,
                    lon
                )

    elif isinstance(
        value,
        list
    ):
        for child in value:
            lat, lon = find_coordinates_deep(
                child
            )

            if (
                lat is not None and
                lon is not None
            ):
                return (
                    lat,
                    lon
                )

    return (
        None,
        None
    )


def build_location_lookup(
    location_objects: dict[
        str,
        dict[str, Any]
    ]
) -> dict[
    str,
    dict[str, Any]
]:
    """
    nodegoat-City/Location-Objekte werden einmal geladen und danach
    über ihre Objekt-ID nachgeschlagen. Das verhindert einen API-Aufruf
    pro Adresse.
    """
    lookup: dict[
        str,
        dict[str, Any]
    ] = {}

    for object_id, pack in location_objects.items():
        lat, lon = find_coordinates_deep(
            pack
        )

        lookup[
            str(object_id)
        ] = {
            "id":
                str(object_id),
            "name":
                object_name(
                    str(object_id),
                    pack
                ),
            "lat":
                lat,
            "lon":
                lon,
        }

    return lookup


def collect_location_ref_ids(
    person_objects: dict[
        str,
        dict[str, Any]
    ]
) -> list[str]:
    """
    Sammelt ausschliesslich die Ortsobjekt-IDs, die in den
    Wohnort-Sub-Objects der geladenen Personen/Firmen referenziert sind.

    Wichtig:
    Anwesenheits-Sub-Objects referenzieren Generalversammlungen und
    dürfen hier nicht als Ortsreferenzen interpretiert werden.
    """
    result: set[str] = set()

    for pack in person_objects.values():
        for sub_pack in iter_values(
            pack.get(
                "object_subs"
            )
        ):
            if not isinstance(
                sub_pack,
                dict
            ):
                continue

            if sub_detail_id(
                sub_pack
            ) != SD_WOHNORT:
                continue

            ref_id = sub_ref_object_id(
                sub_pack
            )

            if ref_id:
                result.add(
                    str(ref_id)
                )

    return sorted(
        result,
        key=lambda value: (
            int(value)
            if value.isdigit()
            else value
        )
    )


# ============================================================
# API
# ============================================================

class NodegoatAPI:
    def __init__(
        self,
        token: str,
        host: str = API_HOST,
        project_id: int = PROJECT_ID,
    ):
        self.token = token
        self.host = host.rstrip("/")
        self.project_id = int(
            project_id
        )

    def get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        retries: int = 3,
    ) -> dict[str, Any]:
        url = (
            f"{self.host}/project/"
            f"{self.project_id}/"
            f"{path.lstrip('/')}"
        )

        if params:
            url += "?" + urlencode(
                params
            )

        request = Request(
            url,
            method="GET",
            headers={
                "Authorization":
                    f"Bearer {self.token}",
                "Accept":
                    "application/json",
                "User-Agent":
                    "goldmine-nodegoat-export/1.0",
            },
        )

        for attempt in range(
            retries
        ):
            try:
                with urlopen(
                    request,
                    timeout=60
                ) as response:
                    payload = json.load(
                        response
                    )

                if payload.get(
                    "authenticated"
                ) is False:
                    raise RuntimeError(
                        "nodegoat meldet authenticated=false."
                    )

                return payload

            except HTTPError as exc:
                body = ""

                try:
                    body = exc.read().decode(
                        "utf-8",
                        errors="replace"
                    )

                except Exception:
                    pass

                is_rate_limit = (
                    exc.code == 429 or
                    (
                        exc.code == 300 and
                        "request_limit" in body
                    )
                )

                if is_rate_limit:
                    raise RuntimeError(
                        "Das nodegoat API-Limit "
                        "(30 Requests pro IP / 15 Minuten) "
                        "ist momentan ausgeschöpft. "
                        "Warte etwa 15 Minuten und starte "
                        "den Export danach erneut.\n\n"
                        f"Letzter Request: {url}"
                    ) from exc

                raise RuntimeError(
                    f"HTTP {exc.code} bei {url}\n{body}"
                ) from exc

            except URLError as exc:
                if attempt < retries - 1:
                    time.sleep(
                        2 ** attempt
                    )
                    continue

                raise RuntimeError(
                    f"Netzwerkfehler bei {url}: {exc}"
                ) from exc

        raise RuntimeError(
            f"API-Aufruf fehlgeschlagen: {url}"
        )

    def get_objects_by_ids(
        self,
        type_id: int,
        object_ids: list[str],
        batch_size: int = 50,
    ) -> dict[str, dict[str, Any]]:
        """
        Lädt nur konkrete nodegoat-Objekte.

        nodegoat unterstützt mehrere IDs im Pfad:
            /data/type/11337/object/5,6,7

        Dadurch müssen wir beim Orts-Type nicht mehr zehntausende
        unbeteiligte Objekte paginieren.
        """
        if not object_ids:
            return {}

        unique_ids = list(
            dict.fromkeys(
                str(object_id)
                for object_id in object_ids
                if str(object_id).strip()
            )
        )

        result: dict[
            str,
            dict[str, Any]
        ] = {}

        for start in range(
            0,
            len(unique_ids),
            batch_size
        ):
            batch = unique_ids[
                start:start + batch_size
            ]

            path_ids = ",".join(
                batch
            )

            payload = self.get_json(
                f"data/type/{type_id}/object/{path_ids}"
            )

            objects = (
                payload
                .get("data", {})
                .get("objects", {})
            )

            if not isinstance(
                objects,
                dict
            ):
                raise RuntimeError(
                    "Unerwartete API-Struktur beim "
                    "gezielten Ortsabruf: data.objects "
                    "ist kein Dictionary."
                )

            for object_id, pack in objects.items():
                result[
                    str(object_id)
                ] = pack

        return result


    def get_type_objects(
        self,
        type_id: int,
        page_size: int = PAGE_SIZE,
    ) -> dict[str, dict[str, Any]]:
        """
        Effiziente Pagination. Da dein Datenbestand klein ist,
        braucht dies normalerweise nur 1-2 Requests pro Type.
        """
        result: dict[
            str,
            dict[str, Any]
        ] = {}

        offset = 0

        while True:
            payload = self.get_json(
                f"data/type/{type_id}/object",
                {
                    "limit": page_size,
                    "offset": offset,
                }
            )

            objects = (
                payload
                .get("data", {})
                .get("objects", {})
            )

            if not isinstance(
                objects,
                dict
            ):
                raise RuntimeError(
                    "Unerwartete API-Struktur: "
                    "data.objects ist kein Dictionary."
                )

            new_count = 0

            for object_id, pack in objects.items():
                object_id = str(
                    object_id
                )

                if object_id not in result:
                    new_count += 1

                result[
                    object_id
                ] = pack

            if not objects:
                break

            if new_count == 0:
                break

            offset += len(
                objects
            )

            # Bei weniger als der gewünschten Seitengrösse ist sehr
            # wahrscheinlich alles geladen. Ein zusätzlicher Request
            # ist für kleine Bestände unnötig.
            if len(objects) < page_size:
                break

        return result


# ============================================================
# LOKALE QUELLENDATEIEN / IIIF
# ============================================================

SOURCE_IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
)

SOURCE_JSON_DIRS = (
    Path("data/RAW"),
    Path("data/sources"),
)

SOURCE_IMAGE_DIRS = (
    Path("assets/sources"),
    Path("assets/workflow"),
    Path("data/RAW"),
    Path("data/sources"),
    Path("assets"),
)


def load_json_file(
    path: Path
) -> dict[str, Any] | list[Any] | None:
    try:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return None


def split_source_values(
    values: Any
) -> list[str]:
    """
    Wandelt nodegoat-/Legacy-Quellenfelder in einzelne
    Dateinamen bzw. Quellenbezeichner um.

    Wichtig:
    Dateinamen wie

        ...1961.pdf_page_3.json

    dürfen NICHT beim eingebetteten ".pdf" abgeschnitten werden.
    Eine Dateiendung zählt daher nur dann als Ende, wenn danach
    das Ende des Quellenwerts oder ein Trennzeichen folgt.
    """
    if values is None:
        return []

    if isinstance(
        values,
        list
    ):
        result: list[str] = []

        for value in values:
            result.extend(
                split_source_values(
                    value
                )
            )

        return result

    text = str(values).strip()

    if not text:
        return []

    # Quellenwerte werden in den Metadaten durch ; oder Zeilenumbrüche
    # getrennt. Erst danach wird pro Token geprüft, ob es sich um
    # einen expliziten Dateinamen handelt.
    tokens = [
        item.strip()
        for item in re.split(
            r"[;\n\r]+",
            text
        )
        if item.strip()
    ]

    if not tokens:
        return []

    result = []

    for token in tokens:
        match = re.search(
            r"\.(?:json|jpg|jpeg|png|webp|pdf)$",
            token,
            flags=re.I,
        )

        if match:
            result.append(
                token
            )
        else:
            # Auch freie Quellenbezeichner beibehalten.
            result.append(
                token
            )

    return result


def normalise_source_stem(
    value: str
) -> str:
    name = Path(
        str(value).strip()
    ).name

    lower = name.lower()

    for suffix in (
        ".json",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
    ):
        if lower.endswith(
            suffix
        ):
            return name[
                :-len(suffix)
            ]

    return name


def relative_web_path(
    path: Path,
    project_root: Path
) -> str:
    try:
        return path.resolve().relative_to(
            project_root.resolve()
        ).as_posix()

    except ValueError:
        return ""


def find_file_by_name(
    project_root: Path,
    directories: tuple[Path, ...],
    filenames: list[str],
) -> Path | None:
    for directory in directories:
        root = (
            project_root /
            directory
        )

        if not root.exists():
            continue

        for filename in filenames:
            candidate = (
                root /
                filename
            )

            if candidate.is_file():
                return candidate

    return None


def find_source_json(
    project_root: Path,
    source_value: str,
) -> Path | None:
    name = Path(
        str(source_value)
    ).name

    stem = normalise_source_stem(
        name
    )

    filenames = []

    if name.lower().endswith(
        ".json"
    ):
        filenames.append(
            name
        )

    filenames.append(
        f"{stem}.json"
    )

    return find_file_by_name(
        project_root,
        SOURCE_JSON_DIRS,
        list(
            dict.fromkeys(
                filenames
            )
        ),
    )


def source_document_stem(
    json_path: Path | None,
    fallback_stem: str,
) -> str:
    if not json_path:
        return fallback_stem

    data = load_json_file(
        json_path
    )

    if isinstance(
        data,
        dict
    ):
        document = data.get(
            "document"
        )

        if document:
            return normalise_source_stem(
                str(document)
            )

    return fallback_stem


def find_source_image(
    project_root: Path,
    stems: list[str],
) -> Path | None:
    filenames = []

    for stem in stems:
        if not stem:
            continue

        for extension in (
            ".jpg",
            ".jpeg",
            ".png",
            ".webp",
        ):
            filenames.append(
                f"{stem}{extension}"
            )

    return find_file_by_name(
        project_root,
        SOURCE_IMAGE_DIRS,
        list(
            dict.fromkeys(
                filenames
            )
        ),
    )


def load_iiif_overrides(
    project_root: Path
) -> dict[str, Any]:
    path = (
        project_root /
        "data" /
        "iiif-overrides.json"
    )

    if not path.exists():
        return {}

    data = load_json_file(
        path
    )

    return (
        data
        if isinstance(
            data,
            dict
        )
        else {}
    )


def iiif_url_for_source(
    overrides: dict[str, Any],
    stems: list[str],
    json_path: Path | None = None,
) -> str:
    keys = []

    for stem in stems:
        if stem:
            keys.append(
                stem
            )

    if json_path:
        keys.extend([
            json_path.name,
            json_path.stem,
        ])

    for key in keys:
        value = overrides.get(
            key
        )

        if isinstance(
            value,
            str
        ):
            return value.strip()

        if isinstance(
            value,
            dict
        ):
            for field in (
                "info_json",
                "iiif_info_url",
                "iiif"
            ):
                url = value.get(
                    field
                )

                if url:
                    return str(
                        url
                    ).strip()

    return ""


def load_legacy_gv_metadata(
    project_root: Path
) -> dict[str, Any]:
    path = (
        project_root /
        "data" /
        "gv-metadata.json"
    )

    if not path.exists():
        return {}

    data = load_json_file(
        path
    )

    return (
        data
        if isinstance(
            data,
            dict
        )
        else {}
    )


def legacy_sources_for_gv(
    current_info: dict[str, Any],
    legacy_metadata: dict[str, Any],
) -> list[str]:
    """
    Nutzt die alte gv-metadata.json nur zur Provenienz-/Dateizuordnung.
    Die historischen Forschungsdaten selbst bleiben aus nodegoat.
    """
    current_date = str(
        current_info.get(
            "date",
            ""
        )
    )

    current_year = current_info.get(
        "year"
    )

    exact_matches = []
    year_matches = []

    for legacy_info in legacy_metadata.values():
        if not isinstance(
            legacy_info,
            dict
        ):
            continue

        legacy_date = str(
            legacy_info.get(
                "date",
                ""
            )
        )

        legacy_year = legacy_info.get(
            "year"
        )

        if (
            current_date and
            legacy_date and
            current_date == legacy_date
        ):
            exact_matches.append(
                legacy_info
            )

        elif (
            current_year is not None and
            (
                legacy_year == current_year or
                (
                    legacy_date and
                    legacy_date.startswith(
                        str(current_year)
                    )
                )
            )
        ):
            year_matches.append(
                legacy_info
            )

    matches = (
        exact_matches
        if exact_matches
        else year_matches
    )

    result = []

    for info in matches:
        for field in (
            "source_files",
            "sources",
            "source",
            "files",
        ):
            result.extend(
                split_source_values(
                    info.get(field)
                )
            )

    return list(
        dict.fromkeys(
            result
        )
    )


def build_source_pages(
    gv_metadata: dict[
        str,
        dict[str, Any]
    ],
    project_root: Path,
) -> None:
    """
    Ergänzt jede GV um source_pages.

    Datei-Konvention:
        data/RAW/FILENAME.json
        assets/sources/FILENAME.jpg

    Zusätzlich werden assets/workflow, data/RAW und data/sources
    nach einem Bild mit identischem Stem durchsucht.

    Für echtes IIIF:
        data/iiif-overrides.json
    """
    legacy_metadata = load_legacy_gv_metadata(
        project_root
    )

    iiif_overrides = load_iiif_overrides(
        project_root
    )

    total_pages = 0
    image_pages = 0
    json_pages = 0
    iiif_pages = 0

    for gv_id, info in gv_metadata.items():
        source_values = []

        source_values.extend(
            split_source_values(
                info.get(
                    "source_files"
                )
            )
        )

        source_values.extend(
            legacy_sources_for_gv(
                info,
                legacy_metadata
            )
        )

        source_values = list(
            dict.fromkeys(
                source_values
            )
        )

        pages = []
        seen = set()

        for source_value in source_values:
            raw_stem = normalise_source_stem(
                source_value
            )

            json_path = find_source_json(
                project_root,
                source_value
            )

            document_stem = source_document_stem(
                json_path,
                raw_stem
            )

            stems = list(
                dict.fromkeys(
                    [
                        raw_stem,
                        document_stem,
                        (
                            json_path.stem
                            if json_path
                            else ""
                        ),
                    ]
                )
            )

            image_path = find_source_image(
                project_root,
                stems
            )

            iiif_url = iiif_url_for_source(
                iiif_overrides,
                stems,
                json_path,
            )

            page_key = (
                document_stem or
                raw_stem or
                source_value
            )

            if page_key in seen:
                continue

            # Nur tatsächlich nutzbare Quellenansichten aufnehmen.
            if (
                not json_path and
                not image_path and
                not iiif_url
            ):
                continue

            seen.add(
                page_key
            )

            page = {
                "id":
                    page_key,
                "label":
                    page_key,
                "document":
                    document_stem,
                "json_name":
                    (
                        json_path.name
                        if json_path
                        else ""
                    ),
                "json_url":
                    (
                        relative_web_path(
                            json_path,
                            project_root
                        )
                        if json_path
                        else ""
                    ),
                "image_url":
                    (
                        relative_web_path(
                            image_path,
                            project_root
                        )
                        if image_path
                        else ""
                    ),
                "iiif_info_url":
                    iiif_url,
            }

            pages.append(
                page
            )

            total_pages += 1

            if page[
                "json_url"
            ]:
                json_pages += 1

            if page[
                "image_url"
            ]:
                image_pages += 1

            if page[
                "iiif_info_url"
            ]:
                iiif_pages += 1

        pages.sort(
            key=lambda page:
                page.get(
                    "label",
                    ""
                ).casefold()
        )

        info[
            "source_pages"
        ] = pages

    print(
        "Verknüpfe historische Originalquellen mit JSON …"
    )
    print(
        f"  {total_pages} Quellenseiten verknüpft."
    )
    print(
        f"  {image_pages} mit lokalem Bild."
    )
    print(
        f"  {json_pages} mit JSON."
    )
    print(
        f"  {iiif_pages} mit echtem IIIF info.json."
    )


# ============================================================
# GENERALVERSAMMLUNGEN
# ============================================================

def build_gv_data(
    gv_objects: dict[
        str,
        dict[str, Any]
    ]
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
    dict[int, str]
]:
    gv_metadata: dict[
        str,
        dict[str, Any]
    ] = {}

    date_to_gv: dict[
        str,
        str
    ] = {}

    year_candidates: dict[
        int,
        list[str]
    ] = defaultdict(list)

    for nodegoat_id, pack in gv_objects.items():
        key = f"ng:{nodegoat_id}"

        date_info = nodegoat_date(
            definition_value(
                pack,
                OD_GV_DATUM
            )
        )

        title = object_name(
            nodegoat_id,
            pack
        )

        source = text_value(
            definition_value(
                pack,
                OD_GV_QUELLE
            )
        )

        total = number_value(
            definition_value(
                pack,
                OD_GV_TOTAL
            )
        )

        total_o = number_value(
            definition_value(
                pack,
                OD_GV_TOTAL_O
            )
        )

        total_p = number_value(
            definition_value(
                pack,
                OD_GV_TOTAL_P
            )
        )

        gv_metadata[key] = {
            "nodegoat_id":
                int(nodegoat_id),
            "title":
                title,
            "date":
                date_info["iso"],
            "year":
                date_info["year"],
            "date_raw":
                date_info["raw"],
            "source_files":
                [source] if source else [],
            "total_actions":
                total,
            "total_actions_o":
                total_o,
            "total_actions_p":
                total_p,
        }

        if date_info["raw"]:
            existing = date_to_gv.get(
                date_info["raw"]
            )

            if existing:
                print(
                    "WARNUNG: Mehrere GVs mit identischem Datum:",
                    date_info["raw"],
                    existing,
                    key
                )

            else:
                date_to_gv[
                    date_info["raw"]
                ] = key

        if date_info["year"] is not None:
            year_candidates[
                int(date_info["year"])
            ].append(key)

    # Ein Jahresfallback ist nur dann sicher, wenn in diesem Jahr
    # genau eine Generalversammlung vorhanden ist.
    year_to_gv = {
        year: keys[0]
        for year, keys in year_candidates.items()
        if len(keys) == 1
    }

    return (
        gv_metadata,
        date_to_gv,
        year_to_gv
    )


# ============================================================
# PERSONEN / SNAPSHOTS
# ============================================================

def build_person_records(
    person_objects: dict[
        str,
        dict[str, Any]
    ],
    gv_metadata: dict[
        str,
        dict[str, Any]
    ],
    date_to_gv: dict[
        str,
        str
    ],
    year_to_gv: dict[
        int,
        str
    ],
    location_lookup: dict[
        str,
        dict[str, Any]
    ] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str]
]:
    records: list[
        dict[str, Any]
    ] = []

    persons: list[
        dict[str, Any]
    ] = []

    warnings: list[str] = []

    if location_lookup is None:
        location_lookup = {}

    nodegoat_gv_to_key = {
        str(
            info["nodegoat_id"]
        ): key
        for key, info
        in gv_metadata.items()
    }

    for person_id, pack in person_objects.items():
        name = object_name(
            person_id,
            pack
        )

        first_name = text_value(
            definition_value(
                pack,
                OD_FIRST_NAME
            )
        )

        last_name = text_value(
            definition_value(
                pack,
                OD_LAST_NAME
            )
        )

        snapshots: dict[
            str,
            dict[str, Any]
        ] = {}

        def ensure_snapshot(
            date_raw: str,
            gv_key: str | None = None
        ) -> dict[str, Any]:
            # Sobald eine GV bekannt ist, ist ihre ID der stabile
            # Snapshot-Schlüssel. Dadurch werden z.B. 19511231 und
            # eine nur als Jahr 1951 modellierte GV zusammengeführt.
            key = (
                f"gv:{gv_key}"
                if gv_key
                else (
                    date_raw
                    or "undated"
                )
            )

            snapshot = snapshots.get(
                key
            )

            if snapshot is None:
                snapshot = {
                    "_key": key,
                    "date_raw": date_raw,
                    "gv_id": gv_key,
                    "address": "",
                    "lat": None,
                    "lon": None,
                    "location_ref_id": None,
                    "location_mode": "",
                    "actions_o": None,
                    "actions_p": None,
                    "actions_total": None,
                    "present": None,
                    "represented_by_id": None,
                }

                snapshots[
                    key
                ] = snapshot

            if (
                gv_key and
                not snapshot.get("gv_id")
            ):
                snapshot[
                    "gv_id"
                ] = gv_key

            return snapshot

        def gv_for_date(
            date_raw: str
        ) -> str | None:
            if not date_raw:
                return None

            exact = date_to_gv.get(date_raw)
            if exact:
                return exact

            info = nodegoat_date(date_raw)
            year = info.get("year")
            if year is None:
                return None

            return year_to_gv.get(int(year))


        for sub_pack in iter_values(
            pack.get(
                "object_subs"
            )
        ):
            if not isinstance(
                sub_pack,
                dict
            ):
                continue

            detail_id = sub_detail_id(
                sub_pack
            )

            date_raw = sub_date_raw(
                sub_pack
            )

            gv_ref_id = (
                sub_ref_object_id(
                    sub_pack
                )
                if detail_id ==
                SD_ANWESENHEIT
                else None
            )

            gv_key = (
                nodegoat_gv_to_key.get(
                    str(gv_ref_id)
                )
                if gv_ref_id
                else None
            )

            # Anwesenheit GV (Sub-Object Details 12455) hat im Modell
            # kein eigenes Datum. Das historische Datum kommt über die
            # referenzierte Generalversammlung. Für den Snapshot-Abgleich
            # übernehmen wir deshalb deren date_raw.
            if (
                gv_key and
                not date_raw
            ):
                date_raw = str(
                    gv_metadata
                    .get(gv_key, {})
                    .get("date_raw", "")
                )

            if (
                not gv_key and
                date_raw
            ):
                gv_key = gv_for_date(
                    date_raw
                )

            snapshot = ensure_snapshot(
                date_raw,
                gv_key
            )

            if detail_id == SD_WOHNORT:
                # 1) Historischer Text aus dem Wohnort-Feld.
                address = text_value(
                    sub_definition_value(
                        sub_pack,
                        SOD_WOHNORT
                    )
                )

                # 2) Direkt von nodegoat mitgelieferter Name der
                #    referenzierten City/Location.
                direct_ref_name = ref_name(
                    sub_pack
                )

                # 3) Referenz-ID auf das Ortsobjekt.
                location_ref_id = sub_ref_object_id(
                    sub_pack
                )

                location_ref = (
                    location_lookup.get(
                        str(location_ref_id)
                    )
                    if location_ref_id
                    else None
                )

                # Wenn der historische Text leer ist, zuerst den Namen
                # der Location-Referenz und danach das separat geladene
                # Ortsobjekt verwenden.
                if not address:
                    address = (
                        direct_ref_name or
                        text_value(
                            (
                                location_ref or {}
                            ).get(
                                "name"
                            )
                        )
                    )

                # Direkter Point/Geometry am Wohnort-Sub-Object.
                lat, lon = sub_coordinates(
                    sub_pack
                )

                location_mode = (
                    "city_reference"
                    if location_ref_id
                    else (
                        "point"
                        if (
                            lat is not None and
                            lon is not None
                        )
                        else ""
                    )
                )

                # Ist der Wohnort als City/Location-Referenz modelliert,
                # übernehmen wir – sofern vorhanden – die Koordinaten
                # des referenzierten Ortsobjekts.
                if (
                    (
                        lat is None or
                        lon is None
                    ) and
                    location_ref
                ):
                    ref_lat = location_ref.get(
                        "lat"
                    )
                    ref_lon = location_ref.get(
                        "lon"
                    )

                    if (
                        ref_lat is not None and
                        ref_lon is not None
                    ):
                        lat = float(
                            ref_lat
                        )
                        lon = float(
                            ref_lon
                        )

                        location_mode = (
                            "city_reference"
                        )

                # Auch ohne Koordinaten bleibt der City-Name erhalten.
                if (
                    not location_mode and
                    location_ref_id
                ):
                    location_mode = (
                        "city_reference"
                    )

                elif (
                    not location_mode and
                    address
                ):
                    location_mode = (
                        "text_only"
                    )

                if address:
                    snapshot[
                        "address"
                    ] = address

                if lat is not None:
                    snapshot[
                        "lat"
                    ] = lat

                if lon is not None:
                    snapshot[
                        "lon"
                    ] = lon

                if location_ref_id:
                    snapshot[
                        "location_ref_id"
                    ] = str(
                        location_ref_id
                    )

                if location_mode:
                    snapshot[
                        "location_mode"
                    ] = location_mode

            elif detail_id == SD_AKTIEN_O:
                snapshot[
                    "actions_o"
                ] = number_value(
                    sub_definition_value(
                        sub_pack,
                        SOD_AKTIEN_O
                    )
                )

            elif detail_id == SD_AKTIEN_P:
                snapshot[
                    "actions_p"
                ] = number_value(
                    sub_definition_value(
                        sub_pack,
                        SOD_AKTIEN_P
                    )
                )

            elif detail_id == SD_AKTIEN_TOTAL:
                snapshot[
                    "actions_total"
                ] = number_value(
                    sub_definition_value(
                        sub_pack,
                        SOD_AKTIEN_TOTAL
                    )
                )

            elif detail_id == SD_ANWESENHEIT:
                present = bool_value(
                    sub_definition_value(
                        sub_pack,
                        SOD_ANWESEND
                    )
                )

                snapshot[
                    "present"
                ] = (
                    True
                    if present is None
                    else present
                )

                represented = sub_definition(
                    sub_pack,
                    SOD_VERTRETEN_DURCH
                )

                if represented:
                    represented_id = first_present(
                        represented,
                        "object_sub_definition_ref_object_id",
                        "object_sub_definition_value",
                    )

                    if represented_id not in (
                        None,
                        ""
                    ):
                        snapshot[
                            "represented_by_id"
                        ] = str(
                            represented_id
                        )

        # Fehlende GV-Referenz nach Datum auflösen
        for snapshot in snapshots.values():
            if (
                not snapshot["gv_id"] and
                snapshot["date_raw"]
            ):
                snapshot[
                    "gv_id"
                ] = gv_for_date(
                    snapshot[
                        "date_raw"
                    ]
                )

        # Snapshot-Liste
        person_appearances = []

        for snapshot in snapshots.values():
            gv_key = snapshot.get(
                "gv_id"
            )

            if not gv_key:
                warnings.append(
                    f"{name} ({person_id}): "
                    f"Snapshot {snapshot['_key']} "
                    "konnte keiner Generalversammlung "
                    "zugeordnet werden."
                )

                continue

            gv_info = gv_metadata.get(
                gv_key,
                {}
            )

            # Nur tatsächlich relevante historische Snapshots ausgeben.
            has_content = any(
                (
                    snapshot.get("address"),
                    snapshot.get("lat") is not None,
                    snapshot.get("actions_o") is not None,
                    snapshot.get("actions_p") is not None,
                    snapshot.get("actions_total") is not None,
                    snapshot.get("present") is not None,
                )
            )

            if not has_content:
                continue

            # Total nur ergänzen, wenn beide Teilwerte wirklich vorhanden sind.
            if (
                snapshot["actions_total"] is None and
                snapshot["actions_o"] is not None and
                snapshot["actions_p"] is not None
            ):
                snapshot[
                    "actions_total"
                ] = (
                    snapshot[
                        "actions_o"
                    ] +
                    snapshot[
                        "actions_p"
                    ]
                )

            source_files = gv_info.get(
                "source_files",
                []
            )

            source_text = (
                source_files[0]
                if source_files
                else ""
            )

            record = {
                "person_id":
                    int(person_id),
                "nodegoat_object_id":
                    int(person_id),
                "normalized_name":
                    name,
                "name":
                    name,
                "first_name":
                    first_name,
                "last_name":
                    last_name,
                "gv_id":
                    gv_key,
                "gv_nodegoat_id":
                    gv_info.get(
                        "nodegoat_id"
                    ),
                "gv_date":
                    gv_info.get("date", ""),
                "gv_year":
                    gv_info.get("year"),
                "number":
                    "",
                "address":
                    snapshot["address"],
                "geocode_query":
                    snapshot["address"],
                "lat":
                    snapshot["lat"],
                "lon":
                    snapshot["lon"],
                "location_ref_id":
                    snapshot[
                        "location_ref_id"
                    ],
                "location_mode":
                    snapshot[
                        "location_mode"
                    ],
                "actions_o":
                    snapshot["actions_o"],
                "actions_p":
                    snapshot["actions_p"],
                "actions_total":
                    snapshot["actions_total"],
                "present":
                    snapshot["present"],
                "represented_by_id":
                    snapshot[
                        "represented_by_id"
                    ],
                "geocode_quality":
                    (
                        "nodegoat_city"
                        if snapshot[
                            "location_mode"
                        ] == "city_reference"
                        else (
                            "nodegoat"
                            if (
                                snapshot["lat"]
                                is not None and
                                snapshot["lon"]
                                is not None
                            )
                            else (
                                "nodegoat_text"
                                if snapshot["address"]
                                else "missing"
                            )
                        )
                    ),
                "geocode_note":
                    (
                        "Wohnort als City-/Location-Referenz aus nodegoat."
                        if snapshot[
                            "location_mode"
                        ] == "city_reference"
                        else "Georeferenz aus nodegoat."
                    ),
                "document":
                    source_text,
                "source_file":
                    source_text,
                "page_number":
                    None,
                "data_source":
                    "nodegoat",
            }

            records.append(
                record
            )

            person_appearances.append({
                "gv_id":
                    gv_key,
                "gv_nodegoat_id":
                    gv_info.get(
                        "nodegoat_id"
                    ),
                "date":
                    gv_info.get("date", ""),
                "year":
                    gv_info.get("year"),
                "address":
                    snapshot["address"],
                "lat":
                    snapshot["lat"],
                "lon":
                    snapshot["lon"],
                "location_ref_id":
                    snapshot[
                        "location_ref_id"
                    ],
                "location_mode":
                    snapshot[
                        "location_mode"
                    ],
                "actions_o":
                    snapshot["actions_o"],
                "actions_p":
                    snapshot["actions_p"],
                "actions_total":
                    snapshot["actions_total"],
                "present":
                    snapshot["present"],
                "represented_by_id":
                    snapshot[
                        "represented_by_id"
                    ],
            })

        person_appearances.sort(
            key=lambda item: (
                item.get("date") or
                str(
                    item.get("year") or
                    9999
                )
            )
        )

        persons.append({
            "person_id":
                int(person_id),
            "name":
                name,
            "first_name":
                first_name,
            "last_name":
                last_name,
            "appearances":
                person_appearances,
        })

    records.sort(
        key=lambda record: (
            record.get("gv_date") or
            str(
                record.get("gv_year") or
                9999
            ),
            record.get(
                "normalized_name",
                ""
            ).casefold(),
            record.get(
                "person_id",
                0
            ),
        )
    )

    persons.sort(
        key=lambda person: (
            person.get(
                "name",
                ""
            ).casefold(),
            person.get(
                "person_id",
                0
            ),
        )
    )

    return (
        records,
        persons,
        warnings
    )


# ============================================================
# EXPORT
# ============================================================

def export(
    token: str,
    output: Path,
    api_host: str = API_HOST,
    project_id: int = PROJECT_ID,
) -> dict[str, Any]:
    project_root = Path.cwd().resolve()

    api = NodegoatAPI(
        token=token,
        host=api_host,
        project_id=project_id,
    )

    print(
        "Lade Generalversammlungen aus nodegoat …"
    )

    gv_objects = api.get_type_objects(
        TYPE_GV
    )

    print(
        f"  {len(gv_objects)} GV-Objekte geladen."
    )

    print(
        "Lade Personen/Firmen aus nodegoat …"
    )

    person_objects = api.get_type_objects(
        TYPE_PERSON
    )

    print(
        f"  {len(person_objects)} Personen-/Firmenobjekte geladen."
    )

    # Reference-Locations werden direkt aus den Personenobjekten gelesen.
    # nodegoat liefert bei Location References den aufgelösten Ortsnamen
    # und – sofern im referenzierten Ort vorhanden – lat/long bereits mit.
    # Dadurch ist kein Download eines riesigen Orts-Types notwendig.
    referenced_locations = 0
    resolved_names = 0
    resolved_coordinates = 0

    for person_pack in person_objects.values():
        for sub_pack in iter_values(
            person_pack.get("object_subs")
        ):
            if (
                isinstance(sub_pack, dict) and
                sub_detail_id(sub_pack) == SD_WOHNORT and
                sub_ref_object_id(sub_pack)
            ):
                referenced_locations += 1

                if ref_name(sub_pack):
                    resolved_names += 1

                lat, lon = sub_coordinates(sub_pack)
                if lat is not None and lon is not None:
                    resolved_coordinates += 1

    print(
        "Verwende die von nodegoat direkt aufgelösten "
        "City-/Location-Referenzen …"
    )
    print(
        f"  {referenced_locations} referenzierte Wohnort-Snapshots gefunden."
    )
    print(
        f"  {resolved_names} davon enthalten einen aufgelösten Ortsnamen."
    )
    print(
        f"  {resolved_coordinates} davon enthalten aufgelöste Koordinaten."
    )

    location_lookup = {}

    gv_metadata, date_to_gv, year_to_gv = build_gv_data(
        gv_objects
    )

    build_source_pages(
        gv_metadata,
        project_root
    )

    records, persons, warnings = build_person_records(
        person_objects,
        gv_metadata,
        date_to_gv,
        year_to_gv,
        location_lookup,
    )

    payload = {
        "meta": {
            "generated_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
            "source":
                "nodegoat",
            "api_host":
                api_host,
            "project_id":
                project_id,
            "person_type_id":
                TYPE_PERSON,
            "gv_type_id":
                TYPE_GV,
            "location_reference_snapshots":
                referenced_locations,
            "location_names_resolved":
                resolved_names,
            "location_coordinates_resolved":
                resolved_coordinates,
            "person_count":
                len(persons),
            "gv_count":
                len(gv_metadata),
            "record_count":
                len(records),
            "warning_count":
                len(warnings),
        },
        "gv_metadata":
            gv_metadata,
        "records":
            records,
        "persons":
            persons,
        "warnings":
            warnings,
    }

    output.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temp = output.with_suffix(
        output.suffix + ".tmp"
    )

    temp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8"
    )

    temp.replace(
        output
    )

    return payload


# ============================================================
# SELF TEST
# ============================================================

def self_test():
    gv_pack = {
        "100": {
            "object": {
                "object_name_plain":
                    "Assemblée 1968"
            },
            "object_definitions": {
                "date": {
                    "object_description_id":
                        OD_GV_DATUM,
                    "object_definition_value":
                        19681130,
                },
                "src": {
                    "object_description_id":
                        OD_GV_QUELLE,
                    "object_definition_value":
                        "Se_18_Bilanz1967_page_4",
                },
            },
            "object_subs": {},
        }
    }

    person_pack = {
        "200": {
            "object": {
                "object_name_plain":
                    "Alain BREHAM"
            },
            "object_definitions": {},
            "object_subs": {
                "1": {
                    "object_sub": {
                        "object_sub_id": 1,
                        "object_sub_details_id":
                            SD_WOHNORT,
                        "object_sub_date_start":
                            19681130,
                        "object_sub_location_type":
                            "reference",
                        "object_sub_location_ref_object_id":
                            300,
                        "object_sub_location_ref_type_id":
                            11337,
                        "object_sub_location_ref_object_name":
                            "Paris",
                        "object_sub_location_lat":
                            48.87,
                        "object_sub_location_long":
                            2.31,
                    },
                    "object_sub_definitions": {},
                },
                "2": {
                    "object_sub": {
                        "object_sub_id": 2,
                        "object_sub_details_id":
                            SD_AKTIEN_O,
                        "object_sub_date_start":
                            19681130,
                    },
                    "object_sub_definitions": {
                        "a": {
                            "object_sub_description_id":
                                SOD_AKTIEN_O,
                            "object_sub_definition_value":
                                179,
                        }
                    },
                },
                "3": {
                    "object_sub": {
                        "object_sub_id": 3,
                        "object_sub_details_id":
                            SD_AKTIEN_P,
                        "object_sub_date_start":
                            19681130,
                    },
                    "object_sub_definitions": {
                        "a": {
                            "object_sub_description_id":
                                SOD_AKTIEN_P,
                            "object_sub_definition_value":
                                520,
                        }
                    },
                },
                "4": {
                    "object_sub": {
                        "object_sub_id": 4,
                        "object_sub_details_id":
                            SD_AKTIEN_TOTAL,
                        "object_sub_date_start":
                            19681130,
                    },
                    "object_sub_definitions": {
                        "a": {
                            "object_sub_description_id":
                                SOD_AKTIEN_TOTAL,
                            "object_sub_definition_value":
                                699,
                        }
                    },
                },
                "5": {
                    "object_sub": {
                        "object_sub_id": 5,
                        "object_sub_details_id":
                            SD_ANWESENHEIT,
                        "object_sub_location_ref_object_id":
                            100,
                    },
                    "object_sub_definitions": {
                        "a": {
                            "object_sub_description_id":
                                SOD_ANWESEND,
                            "object_sub_definition_value":
                                True,
                        }
                    },
                },
            },
        }
    }

    gv_metadata, date_to_gv, year_to_gv = build_gv_data(
        gv_pack
    )

    records, persons, warnings = build_person_records(
        person_pack,
        gv_metadata,
        date_to_gv,
        year_to_gv,
        {},
    )

    assert len(
        gv_metadata
    ) == 1

    assert len(
        records
    ) == 1

    assert len(
        persons
    ) == 1

    record = records[0]

    assert record[
        "person_id"
    ] == 200

    assert record[
        "normalized_name"
    ] == "Alain BREHAM"

    assert record[
        "actions_total"
    ] == 699

    assert record[
        "gv_nodegoat_id"
    ] == 100

    assert record[
        "address"
    ] == "Paris"

    assert record[
        "lat"
    ] == 48.87

    assert record[
        "lon"
    ] == 2.31

    assert record[
        "location_mode"
    ] == "city_reference"

    assert record[
        "geocode_quality"
    ] == "nodegoat_city"

    assert not warnings

    gv_1951_pack = {
        "101": {
            "object": {
                "object_name_plain": "Assemblée 1951"
            },
            "object_definitions": {
                "date": {
                    "object_description_id": OD_GV_DATUM,
                    "object_definition_value": 1951,
                }
            },
            "object_subs": {},
        }
    }

    _, _, year_map_1951 = build_gv_data(gv_1951_pack)
    assert year_map_1951[1951] == "ng:101"

    assert normalise_raw_date(
        "1968-11-30"
    ) == "19681130"

    assert normalise_raw_date(
        1951
    ) == "19510000"

    assert nodegoat_date(
        1951
    )["iso"] == "1951"

    print(
        "Self-Test erfolgreich."
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Exportiert nodegoat-Forschungsdaten "
            "für die Mines-de-Costano-Webseite."
        )
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/site-data.json"
        ),
    )

    parser.add_argument(
        "--api-host",
        default=API_HOST,
    )

    parser.add_argument(
        "--project-id",
        type=int,
        default=PROJECT_ID,
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
    )

    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    token = os.environ.get(
        "NODEGOAT_TOKEN",
        ""
    ).strip()

    if not token:
        print(
            "FEHLER: NODEGOAT_TOKEN ist nicht gesetzt.\n\n"
            'PowerShell:\n'
            '$env:NODEGOAT_TOKEN = "DEIN_BEARER_TOKEN"\n'
        )

        sys.exit(2)

    try:
        payload = export(
            token=token,
            output=args.output,
            api_host=args.api_host,
            project_id=args.project_id,
        )

    except Exception as exc:
        print(
            "\nEXPORT FEHLGESCHLAGEN:"
        )
        print(exc)
        sys.exit(1)

    meta = payload[
        "meta"
    ]

    print()
    print("=" * 72)
    print("NODEGOAT → WEB EXPORT ERFOLGREICH")
    print("=" * 72)
    print(
        f"Personen/Firmen: "
        f"{meta['person_count']}"
    )
    print(
        f"Generalversammlungen: "
        f"{meta['gv_count']}"
    )
    print(
        f"Historische Snapshots: "
        f"{meta['record_count']}"
    )
    print(
        f"Warnungen: "
        f"{meta['warning_count']}"
    )
    print(
        f"Datei: "
        f"{args.output.resolve()}"
    )

    if payload[
        "warnings"
    ]:
        print()
        print(
            "Erste Warnungen:"
        )

        for warning in payload[
            "warnings"
        ][:10]:
            print(
                f"  - {warning}"
            )


if __name__ == "__main__":
    main()
