"""Reproduce the reviewed Ceske Budejovice selection from local GeoParquet only.

Creates a 30-footprint candidate manifest and README, not reconstructed models.
No network, point-cloud processing, render, or edits to the basic city preview.
"""
from __future__ import annotations

import os
for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "ARROW_NUM_THREADS"):
    os.environ.setdefault(_key, "2")
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from uuid import UUID

import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer
import shapely
from shapely.geometry import mapping
import resource_guard as guard

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".work/.preview/ceske-budejovice"
DEST = ROOT / "cities/ceske-budejovice/roof-pilot"
REVIEW_DATE = "2026-11-16"
MUNICIPAL_PLAN = "https://data.c-budejovice.cz/Oupa/VEREJNE_VYHLASKY/Z_96_az_99_vcetne_UZ/UZ_UPnM_CB_poZm99_UredniDeska_OUP__2023-06-15/TEXTY/Kryci%20listy/1_vnitrni%20mesto/1.1.1_Historicke_jadro_2023-06.pdf"


def ref(provider, url, supports, **extra):
    return dict(provider=provider, url=url, supports=supports, checked_on=REVIEW_DATE, **extra)


REFERENCES = {
    "arena_operator": ref("Kulturní a sportovní zařízení města České Budějovice", "https://www.kszcb.cz/kudy-a-jak-na-stadion", "Identita Budvar arény a adresa F. A. Gerstnera 7/8."),
    "arena_two_halls": ref("Kulturní a sportovní zařízení města České Budějovice", "https://www.kszcb.cz/o-stadionu-1767963403", "Areál má dvě kryté ledové haly; jejich označení I/II zde není přiřazeno k polygonům."),
    "pool_operator": ref("Kulturní a sportovní zařízení města České Budějovice", "https://www.kszcb.cz/kudy-a-jak-do-bazenu", "Plavecký stadion na Sokolském ostrově, orientační číslo 4."),
    "hall_operator": ref("Kulturní a sportovní zařízení města České Budějovice", "https://www.kszcb.cz/kudy-a-jak-do-haly", "Sportovní hala, Stromovka, orientační číslo 12."),
    "black_tower": ref("Oficiální turistický portál města", "https://www.budejce.cz/aktivity/2-cerna-vez", "Černá věž, U Černé věže 70/2."),
    "townhall": ref("Statutární město České Budějovice", "https://www.c-budejovice.cz/sportovni-zarizeni", "Kontaktní adresa magistrátu nám. Přemysla Otakara II. 1/1; přiřazení potvrzuje místní adresní bod a POI."),
    "cathedral": ref("Oficiální turistický portál města", "https://www.budejce.cz/aktivity/7-katedrala-svateho-mikulase", "Katedrála sv. Mikuláše v ulici U Černé věže."),
    "monastery_church": ref("Oficiální turistický portál města", "https://www.budejce.cz/aktivity/14-kostel-obetovani-panny-marie", "Kostel Obětování Panny Marie na Piaristickém náměstí a sousedící klášterní komplex."),
    "churches": ref("Statutární město České Budějovice", "https://www.c-budejovice.cz/prehled-kostelu-bohosluzeb", "Kostel sv. Václava v Kostelní ulici; doplňková lokalizace centrálních kostelů."),
    "wortner": ref("Alšova jihočeská galerie", "https://www.ajg.cz/pro-navstevniky.html", "Wortnerův dům na adrese U Černé věže 343/22."),
    "vcela": ref("Oficiální turistický portál města", "https://budejce.cz/aktivity/12-palac-vcela", "Palác Včela, Karla IV. 92/1, nároží náměstí."),
    "masne": ref("Provozovatel restaurace Masné krámy", "https://www.masne-kramy.cz/", "Masné krámy v Krajinské, orientační číslo 13; čp. 29 z místního adresního bodu."),
    "puklic_plan": ref("Statutární město České Budějovice", MUNICIPAL_PLAN, "Městský dům Puklicův čp. 36/2, Krajinská; identifikace, nikoli přebírání plánových regulativů.", document_date="2023-06", access_note="Text dostupný při prvním otevření; opakovaný find vrátil 404. Identita současně podporována indexovaným popisem NPÚ."),
    "puklic_npu": ref("Národní památkový ústav", "https://pamatkovykatalog.cz/mestsky-dum-19152358", "Indexovaný odborný popis objekt označuje jako Puklicův dům.", access_note="Vyhledávací index dostupný; přímé otevření vrátilo 503. Nejde o úplné přečtení památkové karty."),
    "rabenstejn": ref("Oficiální turistický portál města", "https://www.budejce.cz/aktivity/33-rabenstejnska-vez", "Rabenštejnská věž a navazující kulturní centrum; adresa Panská 207/4 se vztahuje ke komplexu, nikoli automaticky k samostatnému polygonu věže."),
    "zelezna": ref("Oficiální turistický portál města", "https://www.budejce.cz/aktivity/17-zelezna-panna", "Železná panna, Zátkovo nábřeží 461/15."),
    "krajinska43_photo": ref("Czeva / původní fotografie na Wikimedia Commons", "https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_8_(01).jpg", "Identita domu Krajinská 43/8 a historická fotografie průčelí; podrobné ověření v samostatné rešerši podloubí.", photo_date="2012-09-28", license="CC BY-SA 3.0", access_note="Zdroj prohlédl agent rešerše podloubí; zde opakované otevření selhalo. Fotografie je skládané panorama, nikoli metrický podklad."),
    "krajinska44_photo": ref("Czeva / původní fotografie na Wikimedia Commons", "https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_10.jpg", "Popis původní fotografie výslovně uvádí Krajinská 44/10; historické průčelí a podloubí řeší samostatná rešerše.", photo_date="2012-09-28", license="CC BY-SA 3.0", access_note="Skládané panorama; identita potvrzena metadaty fotografie, rozměry se z něj zde neměří."),
    "krajinska45_photo": ref("Czeva / původní fotografie na Wikimedia Commons", "https://commons.wikimedia.org/wiki/File:%C4%8CB,_Krajinsk%C3%A1_12_(01).jpg", "Identita domu Krajinská 45/12 a historická fotografie průčelí; podrobné ověření v samostatné rešerši podloubí.", photo_date="2012-09-28", license="CC BY-SA 3.0", access_note="Zdroj prohlédl agent rešerše podloubí; zde opakované otevření selhalo. Fotografie je skládané panorama, nikoli metrický podklad."),
}


def spec(bid, name, category, reason, *, group=None, refs=(), address=None,
         source_name=None, detailed=True, priority=1, tests=(), note=None):
    return dict(building_id=bid, name=name, category=category, reason=reason,
                group_id=group or "building:" + bid, reference_keys=list(refs),
                required_address=address, required_name=source_name,
                detailed_candidate=detailed, priority=priority, proposed_tests=list(tests), note=note)


SAMPLE = [
    spec("2ea0e62e-9a14-4d65-bfef-7036d91bffa0", "Budvar aréna – severní zdrojový půdorys", "arena_complex", "Velký rozpon a členění haly do střešních a nižších obvodových objemů.", group="budvar-arena", refs=("arena_operator", "arena_two_halls"), address=("F. A. Gerstnera", "7"), source_name="Budvar aréna", tests=("large_span_roof", "height_parts", "roof_ridge")),
    spec("d232deba-7d0b-4c01-a01f-d78024f24e8d", "Budvar aréna – jižní zdrojový půdorys", "arena_complex", "Druhá hala téhož areálu, hodnocení samostatně i společně se severní částí.", group="budvar-arena", refs=("arena_operator", "arena_two_halls"), source_name="Budvar aréna", tests=("large_span_roof", "height_parts"), note="Identita areálu a zdrojový název jsou doloženy; označení hala I/II nebylo přiřazeno."),
    spec("48f63de9-e9ea-4307-81c5-8c1553976441", "Plavecký stadion – Sokolský ostrov 402/4", "swimming_pool", "Velká střecha; otestovat zdrojové flat proti skutečnému bodovému průběhu, bez předjímání tvaru.", refs=("pool_operator",), address=("Sokolský ostrov", "402"), source_name="Plavecký bazén", tests=("large_span_roof", "source_type_conflict", "height_parts")),
    spec("283392cf-95ca-4063-8b85-989e92f083a6", "Sportovní hala – Stromovka 1216/12", "sports_hall", "Rozsáhlý členitý obrys, typ střechy chybí; oddělit hlavní hmotu od příslušenství.", refs=("hall_operator",), address=("Stromovka", "1216"), source_name="Sportovní hala", tests=("large_span_roof", "height_parts", "unknown_roof")),
    spec("8b11dd1d-1fd4-40f2-bae9-56da48a0a78a", "Černá věž", "landmark_tower", "Vysoká úzká dominanta; rozdělení dříku, ochozu a vrcholové části.", refs=("black_tower",), address=("U Černé věže", "70"), source_name="Černá věž", tests=("tower_mass", "nonplanar_roof", "silhouette")),
    spec("e45c2485-616a-4003-92e4-428ce930f490", "Radnice – náměstí Přemysla Otakara II. 1/1", "townhall", "Historická dominanta, více střešních objemů, fasáda a kontakt s podloubím.", group="townhall", refs=("townhall",), address=("nám. Přemysla Otakara II.", "1"), tests=("height_parts", "roof_ridge", "facade_sources", "arcade_review"), note="Vzorek obsahuje tento zdrojový půdorys, nikoli automaticky celý dnešní areál magistrátu."),
    spec("7291bb13-d369-4b44-b700-301debf6dfac", "Katedrála svatého Mikuláše", "cathedral", "Kostelní hmoty a složená střecha; zachovat siluetu významné stavby.", refs=("cathedral",), source_name="svatý Mikuláš", tests=("height_parts", "roof_ridge", "silhouette")),
    spec("ac588980-e044-46ce-aa17-efc306da42be", "Kostel Obětování Panny Marie", "monastery_church", "Složitá historická střecha a návaznost na klášter; oddělit hodnocení zdrojového polygonu od celého komplexu.", group="dominikansky-klaster", refs=("monastery_church",), source_name="Obětování Panny Marie", tests=("height_parts", "roof_ridge", "silhouette"), note="Tento výběr neprohlašuje všechny sousední klášterní budovy a Bílou věž za zahrnuté."),
    spec("53b0b641-97d6-4a61-9fe2-88e0d318285d", "Kostel svatého Václava", "church", "Menší kostel jako protějšek rozsáhlých centrálních chrámů.", refs=("churches",), source_name="Svatý Václav", priority=2, tests=("roof_ridge", "height_parts")),
    spec("98192926-2e4d-4667-b3e9-9998dd4ea22a", "Wortnerův dům – U Černé věže 343/22", "historic_house", "Charakteristické průčelí a střešní hmota; odlišit štít/atiku od skutečných střešních rovin.", refs=("wortner",), address=("U Černé věže", "343"), priority=2, tests=("attic_vs_roof", "silhouette", "facade_sources")),
    spec("5962baef-4d3a-4d16-80c1-fb9f46dd7e93", "Palác Včela – Karla IV. 92/1", "historic_corner", "Nárožní výrazná stavba pro střechu, vikýře a pozdější samostatný test fasády.", refs=("vcela",), address=("Karla IV.", "92"), tests=("height_parts", "dormer_review", "facade_sources")),
    spec("3afe9e11-0b96-481f-abcf-4c7fb28829eb", "Masné krámy – Krajinská 29/13", "historic_roof", "Zdroj uvádí gambrel; vhodný náročnější test rodiny střech a průčelí.", refs=("masne",), address=("Krajinská", "29"), tests=("roof_family", "attic_vs_roof", "facade_sources"), note="POI restaurace leží mimo polygon; identita je spojena přes adresu, nikoli posunem POI."),
    spec("427eb7c5-9db7-4919-9d98-7cf5bdef8e98", "Puklicův dům – Krajinská 36/2", "historic_corner", "Nároží náměstí a Krajinské, vhodné pro objem, fasádu a ověření podloubí.", refs=("puklic_plan", "puklic_npu"), address=("Krajinská", "36"), tests=("height_parts", "facade_sources", "arcade_review")),
    spec("726f7d38-a45f-4b37-b2c6-59c70cca59ca", "Rabenštejnská věž – samostatný půdorys", "fortification_tower", "Drobný vysoký objekt, test střechy věže a nevhodnosti odhadu výšky z průměru sousedů.", group="rabenstejnska-complex", refs=("rabenstejn",), source_name="Rabenštejnská věž", priority=2, tests=("tower_mass", "roof_family"), note="Adresa Panská 207/4 z primárního webu leží v sousedním polygonu komplexu. Samostatná věž je určena zdrojovým názvem a polohou; adresní shoda věže se netvrdí."),
    spec("bd271e8d-30b9-4806-98cd-93c625992ee3", "Železná panna – Zátkovo nábřeží 461/15", "fortification_tower", "Malá stopa vysokého objektu; zdrojové num_floors=1 nelze považovat za ověřený počet pater.", refs=("zelezna",), address=("Zátkovo nábř.", "461"), source_name="Železná Panna", priority=2, tests=("tower_mass", "attribute_conflict", "roof_family")),
    spec("766e2987-0af0-4165-b25a-216597858fa9", "Krajinská 43/8 – kandidát podloubí", "arcade_row", "První ze tří sousedních domů pro společný test průchodné uliční fronty.", group="krajinska-arcades-43-45", refs=("krajinska43_photo",), address=("Krajinská", "43"), tests=("arcade_review", "shared_wall", "roof_ridge")),
    spec("acf04bcb-18f5-41ec-b7e7-14232e12fc1f", "Krajinská 44/10 – kandidát podloubí", "arcade_row", "Prostřední dům řady, návaznost podloubí a výšek sousedních hmot.", group="krajinska-arcades-43-45", refs=("krajinska44_photo",), address=("Krajinská", "44"), tests=("arcade_review", "shared_wall", "roof_ridge")),
    spec("9659768d-7c0c-48f6-a646-2c1296afccd2", "Krajinská 45/12 – kandidát podloubí", "arcade_row", "Třetí dům řady, kontrola okraje souvislého podloubí.", group="krajinska-arcades-43-45", refs=("krajinska45_photo",), address=("Krajinská", "45"), tests=("arcade_review", "shared_wall", "roof_ridge")),
    spec("2f30ac8a-fa58-4068-b710-35d669adf1fb", "Husova třída čp. 1839", "ordinary_gabled_control", "Menší půdorys se zdrojovým gabled jako jednoduchý kontrolní případ.", group="husova-1838-1839", address=("Husova tř.", "1839"), detailed=False, priority=3, tests=("baseline_control", "roof_ridge")),
    spec("71bee53b-db89-4757-b287-081da88273e2", "Husova třída čp. 1838", "ordinary_gabled_control", "Sousední běžný dům, kontrola neslučování navazujících střech.", group="husova-1838-1839", address=("Husova tř.", "1838"), detailed=False, priority=3, tests=("baseline_control", "shared_wall")),
    spec("545391a8-c795-4908-9e05-0b107a8e7569", "Panská čp. 168", "small_row_control", "Malá řadová stopa kolem 81 m², test malého počtu bodů.", group="panska-168-169", address=("Panská", "168"), detailed=False, priority=3, tests=("baseline_control", "few_points")),
    spec("e0dde9f9-cdc6-43a4-a55e-d57b70c6a77a", "Panská čp. 169", "small_row_control", "Sousední větší řadový dům se zdrojovým gabled.", group="panska-168-169", address=("Panská", "169"), detailed=False, priority=3, tests=("baseline_control", "shared_wall")),
    spec("2eb8ba3a-e54c-43fc-9712-4beea77cdb3c", "Česká čp. 150", "small_hipped_control", "Malá stopa se zdrojovým hipped; kontrola proti jednoduché sedlové šabloně.", address=("Česká", "150"), detailed=False, priority=3, tests=("baseline_control", "roof_family")),
    spec("04dba65d-c28d-4fea-a70f-f4b66d8136aa", "Česká čp. 143", "small_skillion_control", "Drobná stopa se zdrojovým skillion v souvislé řadě.", group="ceska-143-144", address=("Česká", "143"), detailed=False, priority=3, tests=("baseline_control", "few_points")),
    spec("29cea80d-8250-493e-9dd4-aafcb3936d73", "Česká čp. 144", "small_skillion_control", "Sousední drobná stavba pro kontrolu konzistence a oddělení půdorysů.", group="ceska-143-144", address=("Česká", "144"), detailed=False, priority=3, tests=("baseline_control", "shared_wall")),
    spec("a13715df-cf9e-496f-a407-4dfc2de86005", "Na Mlýnské stoce čp. 385", "low_flat_control", "Nízký malý objekt se zdrojovým flat a jedním podlažím.", address=("Na Mlýnské stoce", "385"), detailed=False, priority=3, tests=("baseline_control", "flat_roof")),
    spec("099a5e53-02a4-4b93-a6a7-0123062e381f", "Žižkova třída čp. 1321", "high_flat_control", "Vyšší objekt se zdrojovým flat a 15 podlažími; atributy ověřit vůči bodům.", address=("Žižkova tř.", "1321"), detailed=False, priority=3, tests=("baseline_control", "flat_roof", "height_check"), note="Výšková kategorie vychází z atributu; konstrukční systém ani počet pater nejsou zaměřeny."),
    spec("ee0e4f64-a21b-454a-995f-a341add160a3", "Lidická třída čp. 178", "high_flat_control", "Druhý vyšší objekt se zdrojovým flat; jižní část skutečné preview dlaždice.", address=("Lidická tř.", "178"), detailed=False, priority=3, tests=("baseline_control", "flat_roof", "height_check")),
    spec("478f9384-0414-4c4d-99af-fa0c89f059fc", "Náměstí Přemysla Otakara II. čp. 67", "square_row_control", "Řadový dům přímo na náměstí bez zdrojového typu střechy.", group="square-67-68", address=("nám. Přemysla Otakara II.", "67"), detailed=False, priority=3, tests=("baseline_control", "unknown_roof", "shared_wall")),
    spec("5f42f760-3506-4432-9ecc-25313e40df60", "Náměstí Přemysla Otakara II. čp. 68", "square_row_control", "Sousední menší řadový dům bez roof_shape, vhodný pro kontrolu fallbacku.", group="square-67-68", address=("nám. Přemysla Otakara II.", "68"), detailed=False, priority=3, tests=("baseline_control", "unknown_roof", "shared_wall")),
]


def fingerprint(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def osm_urls(sources):
    links = []
    for source in sources or []:
        record = (source.get("record_id") or "").split("@")[0]
        if record[:1] in ("w", "n", "r") and record[1:].isdigit():
            links.append("https://www.openstreetmap.org/" + {"w": "way", "n": "node", "r": "relation"}[record[0]] + "/" + record[1:])
    return sorted(set(links))


def create_sample():
    started = time.perf_counter()
    pa.set_cpu_count(2); pa.set_io_thread_count(2)
    guard.check_budget(reserve_bytes=2_000_000, force=True)
    if len(SAMPLE) != 30 or len({s["building_id"] for s in SAMPLE}) != 30:
        raise ValueError("Exactly 30 unique reviewed footprints are required")
    if sum(s["detailed_candidate"] for s in SAMPLE) > 20:
        raise ValueError("At most 20 detailed candidates")
    config_path = ROOT / "cities/ceske-budejovice/mesto.preview.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config["ctverce"] != [[0, 0]] or config["polovina"] != 1150:
        raise ValueError("The reviewed selection is for the actual 2.3 km preview tile")
    lon, lat = config["stred"]; half = config["polovina"]
    kx = math.cos(math.radians(lat)) * 111320; ky = 110574
    extent = shapely.box(lon - half / kx, lat - half / ky, lon + half / kx, lat + half / ky)
    to_metric = Transformer.from_crs(4326, 5514, always_xy=True).transform
    to_wgs = Transformer.from_crs(5514, 4326, always_xy=True).transform
    names = ("building", "address", "places", "infrastructure", "segment")
    paths = [WORK / "data" / (name + ".parquet") for name in names]
    for path in paths:
        if not path.is_file() or path.stat().st_size > 30_000_000:
            raise ValueError(f"Missing or unexpectedly large local input: {path}")
    data = {name: pq.read_table(path, use_threads=False).to_pylist() for name, path in zip(names, paths)}
    buildings = {r["id"]: r for r in data["building"]}
    indexes = {key: shapely.STRtree(shapely.from_wkb([r["geometry"] for r in data[key]])) for key in names[1:]}
    features = []
    metric_geometries = []
    for ordinal, selection in enumerate(SAMPLE, 1):
        guard.check_budget()
        UUID(selection["building_id"])
        row = buildings[selection["building_id"]]
        geom = shapely.from_wkb(row["geometry"])
        if not geom.is_valid or geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
            raise ValueError("Invalid source geometry: " + row["id"])
        if not extent.covers(geom):
            raise ValueError("Selected footprint exceeds the true preview tile: " + row["id"])
        metric = shapely.transform(geom, to_metric, interleaved=False)
        centre = shapely.transform(metric.centroid, to_wgs, interleaved=False)
        metric_geometries.append(metric)
        addresses = [data["address"][int(i)] for i in indexes["address"].query(geom, predicate="covers")]
        expected = selection["required_address"]
        if expected and not any((a["street"], a["number"]) == expected for a in addresses):
            raise ValueError(f"Address no longer lies inside {row['id']}: {expected}")
        if selection["required_name"] and (row.get("names") or {}).get("primary") != selection["required_name"]:
            raise ValueError("Source building name changed: " + row["id"])
        places = [data["places"][int(i)] for i in indexes["places"].query(geom, predicate="covers")]
        infra = [data["infrastructure"][int(i)] for i in indexes["infrastructure"].query(geom, predicate="intersects")]
        transport = []
        for i in indexes["segment"].query(geom, predicate="intersects"):
            segment = data["segment"][int(i)]
            flags = segment.get("road_flags") or []
            if any(set(f.get("values") or []) & {"is_covered", "is_tunnel", "is_bridge"} for f in flags):
                transport.append({"id": segment["id"], "class": segment.get("class"), "road_flags": flags,
                                  "sources": segment.get("sources"), "osm_urls": osm_urls(segment.get("sources")),
                                  "note": "Průnik půdorysu s linií je pouze indicie; flag může platit jen pro interval between, nikoli zde."})
        polygons = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        props = {
            "pilot_id": f"CB-ROOF-{ordinal:02d}", "building_id": row["id"], "name": selection["name"],
            "category": selection["category"], "group_id": selection["group_id"],
            "selection_reason": selection["reason"], "detailed_candidate": selection["detailed_candidate"],
            "detail_priority": selection["priority"], "proposed_tests": selection["proposed_tests"],
            "experiment_status": "candidate_only_not_reconstructed_or_approved_fix",
            "centroid_wgs84": {"lon": round(centre.x, 9), "lat": round(centre.y, 9)},
            "bbox_wgs84": list(geom.bounds), "bbox_epsg5514": [round(v, 3) for v in metric.bounds],
            "footprint_area_m2": round(metric.area, 3),
            "exterior_vertex_count": sum(len(p.exterior.coords) - 1 for p in polygons),
            "inside_actual_preview_tile": True,
            "source_attributes": {key: row.get(key) for key in ("class", "subtype", "height", "min_height", "num_floors", "has_parts", "roof_shape", "roof_direction", "roof_orientation", "roof_height", "roof_material", "roof_color", "facade_color", "facade_material", "version")},
            "source_names": row.get("names"), "footprint_sources": row.get("sources"), "osm_urls": osm_urls(row.get("sources")),
            "addresses": [{k: a.get(k) for k in ("id", "street", "number", "postal_city", "sources")} for a in addresses],
            "contained_places": [{"id": p["id"], "name": (p.get("names") or {}).get("primary"), "websites": p.get("websites"), "confidence": p.get("confidence"), "note": "POI je pomocná indicie, nikoli samostatné ověření identity."} for p in places],
            "identity": {"status": "supported" if selection["reference_keys"] else "local_address_match", "note": selection["note"],
                         "reference_keys": selection["reference_keys"], "address_containment_checked": bool(expected),
                         "source_name_checked": bool(selection["required_name"]),
                         "infrastructure_evidence": [{"id": i["id"], "class": i.get("class"), "names": i.get("names"), "sources": i.get("sources")} for i in infra if i.get("class") in ("tower", "water_tower", "clock", "chimney")]},
            "opening_evidence": {"tagged_intersecting_transport_segments": transport, "absence_of_tag_is_not_absence_of_opening": True,
                                 "geometry_status": "not_reconstructed", "review": "experiments/arcades" if selection["group_id"] == "krajinska-arcades-43-45" else None},
            "roof_ground_truth": {"status": "not_surveyed", "note": "Zdrojové typy střech a podlaží nejsou nezávisle ověřená referenční geometrie."},
            "facade_ground_truth": {"status": "not_measured", "note": "Výběr nepřiřazuje žádnou novou barvu ani členění fasády; veřejné fotografie vyžadují samostatné ověření licence, data a světla."},
        }
        features.append({"type": "Feature", "id": row["id"], "bbox": list(geom.bounds), "geometry": mapping(geom), "properties": props})
    union = shapely.union_all(metric_geometries)
    groups = {}
    for feature in features:
        props = feature["properties"]
        groups.setdefault(props["group_id"], []).append(props["pilot_id"])
    dmp_manifest = WORK / "build/dmp/preview-manifest.json"
    dmp = json.loads(dmp_manifest.read_text(encoding="utf-8")) if dmp_manifest.exists() else None
    inputs = [fingerprint(p) for p in paths] + [fingerprint(config_path)]
    if dmp_manifest.exists():
        inputs.append(fingerprint(dmp_manifest))
    return {
        "type": "FeatureCollection", "schema_version": 1, "city": "ceske-budejovice", "selection_date": REVIEW_DATE,
        "selection_method": "reviewed_fixed_source_ids_and_primary_identity_sources",
        "feature_count": len(features), "detailed_candidate_count": sum(s["detailed_candidate"] for s in SAMPLE),
        "maximum_detailed_candidates": 20, "experiment_status": "selection_only",
        "bbox": list(shapely.transform(union, to_wgs, interleaved=False).bounds),
        "bbox_epsg5514": [round(v, 3) for v in union.bounds],
        "coordinate_system": {"geometry": "OGC:CRS84 (longitude, latitude)", "metric_bounds": "EPSG:5514"},
        "preview": {"center_lonlat": config["stred"], "size_m": [2300, 2300], "bbox_wgs84": list(extent.bounds), "all_footprints_fully_inside": True},
        "groups": groups, "category_counts": dict(sorted(Counter(f["properties"]["category"] for f in features).items())),
        "source_inputs": inputs, "identity_references": REFERENCES,
        "next_source_plan": {
            "dmp1g": {"status": "existing_basic_preview_data_only_not_sampled_for_this_pilot", "local_manifest": str(dmp_manifest.relative_to(ROOT)).replace("\\", "/"), "city_preview_sheets": dmp.get("sheets", []) if dmp else [], "atom_index": "https://atom.cuzk.gov.cz/DMP1G-SJTSK/DMP1G-SJTSK.xml", "next_step": "Vybrat listy pro tento vzorek a oříznout malé okolí; znovu nestahovat existující podklady."},
            "dmpok": {"status": "not_downloaded_by_this_selection", "atom_index": "https://atom.cuzk.gov.cz/DMPOK-SJTSK-LAZ/DMPOK-SJTSK-LAZ.xml", "next_step": "Až po základním preview ověřit pokrytí a dostupné listy v ATOM indexu, nepředpokládat shodu názvů ani datum snímkování."},
            "holdout": {"status": "not_prepared", "next_step": "Oddělit společnou sadu zadržených bodů před všemi metodami; hodnotit jednotlivé půdorysy i group_id."},
            "facades": {"status": "source_review_only", "path": "cities/ceske-budejovice/experiments/facades"},
            "arcades": {"status": "source_review_only", "path": "cities/ceske-budejovice/experiments/arcades"},
        },
        "limitations": [
            "Jde o výběr kandidátů; žádná podrobná rekonstrukce, oprava základní mapy ani potvrzení geometrie tím nevzniká.",
            "30 půdorysů není 30 nezávislých architektonických celků. Společné skupiny evidují arénu, domovní řady a navazující části.",
            "18 detailních kandidátů je pod maximem 20; dalších 12 půdorysů slouží ke kontrolnímu srovnání jednoduchých modelů.",
            "Adresní number v místní ČÚZK vrstvě je číslo popisné; orientační čísla v názvech pocházejí z citovaných primárních zdrojů nebo samostatné rešerše podloubí.",
            "Typ, sklon, hřeben, vikýře, římsy, barva fasády ani výška průchodu nebyly tímto výběrem nově vypočítány.",
            "Překryv tagované dopravní linie a budovy není důkaz rozměrů otvoru; chybějící tag neznamená chybějící podloubí.",
            "Účelový výběr geometrických případů není statisticky reprezentativní vzorek města.",
        ],
        "selection_metrics": {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "script_seconds": round(time.perf_counter() - started, 6), "timing_scope": "Local input reads, identity assertions, spatial joins and manifest construction; excludes human/source research and subsequent reconstruction", "cloud_points_processed": 0, "downloads": 0, "render_calls": 0},
        "features": features,
    }


def readme(document):
    lines = ["# České Budějovice — výběr pro další pilot střech", "",
             "Stav: pouze výběr kandidátů a podkladů. Základní preview se tím nemění. Následné experimenty začnou až po jeho dokončení.", "",
             f"Výběr obsahuje **{document['feature_count']} původních půdorysů**, {len(document['groups'])} skupin a **{document['detailed_candidate_count']} kandidátů** pro podrobnější práci (limit 20). Všech 30 půdorysů je celých uvnitř skutečné dlaždice centra 2,3 × 2,3 km.", "",
             "Priorita 1: hlavní dominanty, haly, podloubí a fasádní pilot. Priorita 2: doplňkové výrazné historické stavby. Priorita 3: běžné kontrolní případy; podrobná rekonstrukce zatím není navržena.", "",
             "| ID | Objekt | Detail | Priorita | Skupina |", "|---|---|---|---:|---|"]
    for feature in document["features"]:
        p = feature["properties"]
        group = p["group_id"] if not p["group_id"].startswith("building:") else "samostatný"
        lines.append(f"| {p['pilot_id']} | {p['name']} | {'kandidát' if p['detailed_candidate'] else 'kontrola'} | {p['detail_priority']} | {group} |")
    lines += ["", "Každá GeoJSON Feature zachovává UUID a přesnou geometrii z Overture, původní zdroje/licence, adresní body, metrický bbox EPSG:5514, jistotu identity a konkrétní navržené testy. Číslo zdrojové budovy je v `properties.building_id` i `Feature.id`.", "",
              "## Reprodukce a měření", "", "```powershell", ".venv\\Scripts\\python.exe -X utf8 scripts\\select_cb_roof_pilot.py", ".venv\\Scripts\\python.exe -X utf8 scripts\\select_cb_roof_pilot.py --check", "```", "",
              f"Poslední sestavení manifestu: {document['selection_metrics']['script_seconds']:.3f} s. Tento čas zahrnuje lokální načtení, spojení vrstev a kontroly; nezahrnuje rešerši ani budoucí výpočet střech. Zpracované body mraků: 0; stažení: 0; rendery: 0.", "",
              "`--check` kontroluje obsah proti lokálním vstupům; ignoruje pouze čas a datum samotného spuštění. SHA-256 a velikosti všech pěti vstupních GeoParquetů, konfigurace dlaždice a existujícího DMP manifestu jsou v `source_inputs`. Skript nepřipravuje holdout ani trénovací mrak.", "",
              "## Další podklady", "",
              "Pro DMP1G už existují listy základního preview. Nejprve se vyberou a oříznou potřebné části, bez opakovaného stahování. DMPOK je pouze návrh dalšího zdroje; dostupnost, datum a listy musí ověřit samostatný přípravný krok. Samotný výběr nepřebírá stejné názvy listů automaticky. Metadata a ATOM odkazy jsou v `next_source_plan`.", "",
              "Fasádní rešerše: `../experiments/facades/`. Rešerše podloubí: `../experiments/arcades/`. Stejná UUID propojují výběr a oba experimenty. U tří domů Krajinská 43–45 není chybějící tag dopravní sítě důkazem nepřítomnosti podloubí. Rozměry otvorů se teprve ověří.", "",
              "## Omezení", ""]
    lines += ["- " + limitation for limitation in document["limitations"]]
    lines += ["", "Rabenštejnská věž je vybrána jako samostatný pojmenovaný polygon. Adresa Panská 207/4 z turistického webu patří sousednímu objektu kulturního komplexu; nespojuje se násilně s věží. POI Masných krámů je mimo půdorys; přiřazení používá adresu. U Puklicova domu primární městský plán doložil čp.36/2, přímá karta NPÚ měla při rešerši chybu serveru.", "",
              "## Primární zdroje identity", ""]
    lines += [f"- **{key}** — [{r['provider']}]({r['url']}): {r['supports']}" + (" " + r["access_note"] if r.get("access_note") else "") for key, r in document["identity_references"].items()]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    document = create_sample()
    target = DEST / "sample.json"
    payload = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if len(payload.encode("utf-8")) > 2_000_000:
        raise ValueError("Unexpectedly large selection manifest")
    if args.check:
        previous = json.loads(target.read_text(encoding="utf-8"))
        current = deepcopy(document)
        previous.pop("selection_metrics", None); current.pop("selection_metrics", None)
        if previous != json.loads(json.dumps(current)):
            raise ValueError("Selection differs from current source files or reviewed specification")
    else:
        guard.check_budget(reserve_bytes=len(payload.encode("utf-8")) * 2, force=True)
        DEST.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(".json.partial")
        part.write_text(payload, encoding="utf-8"); part.replace(target)
        (DEST / "README.md").write_text(readme(document), encoding="utf-8")
    print(json.dumps({"output": str(target), "checked": args.check, "features": document["feature_count"], "groups": len(document["groups"]), "detailed_candidates": document["detailed_candidate_count"], "seconds": document["selection_metrics"]["script_seconds"], "all_inside_preview": True}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
