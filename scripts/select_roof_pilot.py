"""Reproduce the small, reviewed Velesin roof pilot from existing local data.

Reads only the cached Overture GeoParquet files and the Sportcentrum reference.
Does not download data, infer roof truth, or render anything. The resulting
GeoJSON contains 30 source footprints; several belong to one historic complex.
Run with the project's Python: python scripts/select_roof_pilot.py
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

import pyarrow.parquet as pq
from pyproj import Transformer
import shapely
from shapely.geometry import mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / ".work/.preview/velesin/data"
DEFAULT_OUTPUT = ROOT / "cities/velesin/roof-pilot/sample.json"
REVIEW_DATE = "2026-11-15"
MIN_FREE_BYTES = 25 * 1024**3

# Public sources establish identities only. They are not survey ground truth.
REFERENCES = {
    "municipality_contact": {
        "provider": "Město Velešín",
        "url": "https://www2.velesin.cz/mestsky-urad-10/organizacni-struktura/",
        "supports": "Adresa městského úřadu náměstí J. V. Kamarýta 76.",
    },
    "townhall_history": {
        "provider": "Společnost přátel města Velešína",
        "url": "https://www.velesinpratele.cz/domains/velesinpratele.cz/index.php?Itemid=78&id=49&option=com_content&view=category",
        "supports": "Historická radnice čp. 77 a připojená část čp. 76.",
    },
    "jakub_three_numbers": {
        "provider": "Město Velešín",
        "url": "https://www.velesin.cz/document-open-00075-010/vzzm-10.pdf",
        "document_date": "2011-10-31",
        "page": 1,
        "supports": "Zápis zastupitelstva výslovně přiřazuje kostelu Jakub čp. 87, 88 a 89.",
    },
    "jakub_operator": {
        "provider": "Kulturní a informační centrum města Velešín",
        "url": "https://www.kicvelesin.cz/cenik-kratkodobeho-pronajmu-prostor/",
        "supports": "Budova bývalého kostela sv. Filipa a Jakuba na náměstí J. V. Kamarýta 89.",
    },
    "jakub_history": {
        "provider": "Město Velešín",
        "url": "https://www.velesin.cz/fotogalerie-historie/byvaly-kostel-sv-filipa-a-jakuba/",
        "supports": "Historický kostel, dodatečná věž a pozdější rozdělení lodi na obytné části.",
    },
    "vaclav_municipal": {
        "provider": "Město Velešín",
        "url": "https://www.velesin.cz/fotogalerie-historie/namesti-j-v-kamaryta/",
        "supports": "Kostel sv. Václava v dolní části náměstí; přesné přiřazení z názvu v lokálních datech.",
    },
    "school_addresses": {
        "provider": "Město Velešín",
        "url": "https://www.velesin.cz/mesto-34/soucasnost/skolstvi/",
        "supports": "Mateřská škola Školní 223; pro přiřazení polygonu použit adresní bod ČÚZK.",
    },
    "school_own": {
        "provider": "Mateřská škola ve Velešíně",
        "url": "https://www.msvelesin.cz/wp-content/uploads/2025/10/SVP-revidovany.pdf",
        "supports": "Potvrzuje adresu Školní 223, nikoliv rozsah či aktuální geometrii přístaveb.",
    },
    "water_tower_context": {
        "provider": "City Upgrade / studie regenerace pro Velešín",
        "url": "https://velesin.cityupgrade.cz/hlavni-strana/regenerace-uzemi-druzstevni/",
        "supports": "Vodárenská věž u hřiště v lokalitě Družstevní; přesný polygon propojen přes OSM way.",
    },
    "sportcentrum_reference": {
        "provider": "Tiny Towns / dřívější kontrola s uživatelem",
        "path": "cities/velesin/models/sportcentrum-velesin.source.json",
        "supports": "Identita Strahovská 661, tenisová válcová střecha, odlišné objemy a průchod; model není zaměření.",
    },
}


def spec(bid, name, category, reason, *, group=None, refs=(), status="address_match",
         note=None, address=None, check_name=None, infrastructure_way=None):
    return dict(building_id=bid, name=name, category=category, reason=reason,
                group_id=group, references=list(refs), identity_status=status,
                identity_note=note, required_address=address,
                required_name=check_name, infrastructure_way=infrastructure_way)


# Explicit stable source IDs keep the sample unchanged when rows are reordered.
SAMPLE = [
    spec("4f1c85c2-69eb-4e6d-8094-3eb1bd5f1208", "Radnice – čp. 77", "townhall",
         "Historická veřejná budova, návaznost odlišných střešních objemů.",
         group="townhall", refs=("townhall_history",), status="supported", address=("náměstí J. V. Kamarýta", "77")),
    spec("0278d20e-f2c2-4aa4-859b-368587e9c1a0", "Radnice – čp. 76", "townhall",
         "Druhá evidovaná část radnice; hodnotit společně s čp. 77.",
         group="townhall", refs=("municipality_contact", "townhall_history"), status="supported", address=("náměstí J. V. Kamarýta", "76")),
    spec("16e9927f-2022-4075-a27f-03bed8e750a5", "Kostel sv. Václava", "church",
         "Složitá střecha a věž, riziko přílišného zjednodušení významné dominanty.",
         group="church-vaclav", refs=("vaclav_municipal",), status="supported", check_name="Kostel Svatého Václava"),
    spec("4a9c59ba-655c-4e3c-a8a7-a28e050fd375", "Bývalý kostel sv. Filipa a Jakuba – čp. 87", "former_church",
         "Jeden ze tří zdrojových půdorysů kostela; nesmí se vynechat při hodnocení celku.",
         group="church-jakub", refs=("jakub_three_numbers", "jakub_history"), status="supported", address=("náměstí J. V. Kamarýta", "87")),
    spec("d6bd197e-ef4a-46f6-96ba-69741579f136", "Bývalý kostel sv. Filipa a Jakuba – čp. 88", "former_church",
         "Prostřední část komplexu; návaznost střešních rovin přes hranice evidovaných budov.",
         group="church-jakub", refs=("jakub_three_numbers",), status="supported", address=("náměstí J. V. Kamarýta", "88")),
    spec("dbcb145c-dfe2-4355-805e-fbe46b23b38f", "Bývalý kostel sv. Filipa a Jakuba – čp. 89", "former_church",
         "Galerie a infocentrum, v datech odlišný typ střechy od sousedních částí.",
         group="church-jakub", refs=("jakub_three_numbers", "jakub_operator"), status="supported", address=("náměstí J. V. Kamarýta", "89")),
    spec("7ec1c263-165d-428b-a9a3-ff9add05a3d9", "Vodárenská věž v Družstevní", "water_tower",
         "Malý půdorys vysokého objektu, jehlanová střecha dle zdrojového atributu.",
         refs=("water_tower_context",), status="supported", infrastructure_way="w104236088"),
    spec("c5bb605f-5e1b-4d00-b773-323365e9e4f9", "Mateřská škola – Školní 223", "kindergarten",
         "Veřejná budova v měnícím se areálu; kontrola stáří podkladů a přístaveb.",
         group="kindergarten-223", refs=("school_addresses", "school_own"), status="supported", address=("Školní", "223")),
    spec("12030eea-2246-4a6e-bcd1-80fa329153d8", "Členitý objekt západně od MŠ – kandidát části areálu", "kindergarten_extension_candidate",
         "Třicet vrcholů obrysu: rozklad členitého půdorysu a různé výšky částí.",
         group="kindergarten-223-candidate", status="candidate",
         note="Poloha sousedí s MŠ. Příslušnost objektu k MŠ ani identita nové přístavby nejsou potvrzeny; nejde o tvrzení, že jde o novou přístavbu 2026."),
    spec("988326aa-55e0-4e44-8479-b666954da3d2", "Základní škola – Družstevní 340", "school",
         "Velká školní budova, více střešních částí a výškové přechody.",
         status="local_address_and_place", address=("Družstevní", "340")),
    spec("78e32d1e-ecfa-4e1b-a00f-db417ea5af1b", "Sportcentrum – tenisová a squashová hala", "barrel_roof_complex",
         "Známá válcová střecha + ploché části různé výšky + otevřený průchod.",
         group="sportcentrum", refs=("sportcentrum_reference",), status="user_reviewed", address=("Strahovská", "661")),
    spec("7bf51833-2377-4271-8ddc-b5f8611e44a8", "Náměstí J. V. Kamarýta 131", "historic_square",
         "Řadový dům u náměstí; oddělení společných střech a dvorních částí.", address=("náměstí J. V. Kamarýta", "131")),
    spec("198527b2-b7a6-406f-9b2d-ebfc29d7f723", "Náměstí J. V. Kamarýta 69", "historic_square",
         "Protáhlý členitý dům s dvorní částí, nevhodný pro jednu univerzální sedlovou střechu.", address=("náměstí J. V. Kamarýta", "69")),
    spec("97d883e9-0f10-4399-b162-78c494a93d4e", "Náměstí J. V. Kamarýta 70", "historic_square",
         "Členitý půdorys vedle čp. 69; rozklad hmot a návaznost střech.", address=("náměstí J. V. Kamarýta", "70")),
    spec("2df261d0-83c4-4c17-beac-5cdbfa06b944", "Náměstí J. V. Kamarýta 57", "historic_square",
         "Nepravidelný historický půdorys, test zjednodušení bez ztráty významných ramen.", address=("náměstí J. V. Kamarýta", "57")),
    spec("22d5f84d-bc4b-46ae-ae1d-e9d2034672f2", "Náměstí J. V. Kamarýta 14", "historic_square",
         "Menší řadový dům jako jednoduchý protějšek členitých sousedů.", address=("náměstí J. V. Kamarýta", "14")),
    spec("43896dfe-74a3-4d28-a66b-62534438d9f7", "Bytový blok Sídliště 506", "apartment_block_candidate",
         "Vysoký blok: zdroj uvádí 9 podlaží a plochou střechu.", address=("Sídliště", "506"),
         note="Adresní identita potvrzena; panelová konstrukce ani počet skutečných podlaží nebyly zaměřeny."),
    spec("30491e38-7ddc-488b-b26d-c6cc44b7feaa", "Bytový blok Sídliště 463", "apartment_block_candidate",
         "Nižší blok: zdroj uvádí 5 podlaží, plochou střechu a členitější obrys.", address=("Sídliště", "463"),
         note="Adresní identita potvrzena; panelová konstrukce je pouze kandidátní kategorie."),
    spec("d0cbb8d8-2ce8-41f5-9dec-b00337bdd525", "Bytový dům Družstevní 336–337", "apartment_block_candidate",
         "Dva adresní body v jednom půdorysu a plochá střecha dle zdroje.", address=("Družstevní", "336"),
         note="Adresy 336 a 337 leží ve stejném zdrojovém polygonu; konstrukční systém neověřen."),
    spec("0de630cc-d74f-4e84-8a9e-3bb1b3525403", "Rodinný dům Školní 522", "ordinary_gabled",
         "Jednoduchý čtyřhranný půdorys se sedlovou střechou dle atributu; základní kontrolní případ.", address=("Školní", "522")),
    spec("2dd5e4d3-1624-4569-bde8-a79bc9723db2", "Dům Budějovická 215", "ordinary_hipped",
         "Valbová střecha dle atributu na členitějším půdorysu.", address=("Budějovická", "215")),
    spec("84441cdd-e38a-4c2c-9391-9162681d24e7", "Dům Družstevní 613", "ordinary_half_hipped",
         "Polovalbová střecha dle zdroje; rozlišení od sedlové a valbové.", address=("Družstevní", "613")),
    spec("b4692023-1a6f-4162-aa56-5b8df9c74fe4", "Dům Družstevní 648", "ordinary_skillion",
         "Pultová střecha dle zdroje; kontrola jednostranného sklonu.", address=("Družstevní", "648")),
    spec("2aa0f596-18d7-422f-a6ff-518d463ee5b0", "Nízký objekt u Školní – plochá střecha dle zdroje", "low_flat",
         "Malý nízký objekt jako protějšek plochých střech výškových domů.", status="source_geometry",
         note="Funkce objektu neověřena; název je popis polohy a zdrojového atributu."),
    spec("d73001a7-a401-4dcf-b0e6-3dcaffa5989a", "Dům Strahovská 272 – typ střechy chybí", "unknown_roof_house",
         "Skutečně chybějící roof_shape, běžný dům s adresním bodem.", address=("Strahovská", "272")),
    spec("4d5488dc-708f-46b1-b237-46eb2cc1080d", "Členitý objekt severně od Jihostroje – kandidát", "unknown_roof_irregular",
         "Chybí typ i podlaží, malý složitý obrys: zkouška opatrného fallbacku.", status="candidate",
         note="Funkce a skutečné členění hmot nejsou ověřeny. Výběr pouze podle obrysu a chybějících atributů."),
    spec("1398a139-65ca-4699-a6c5-bee7e12e0124", "Dům V Domkách 106", "source_ridge_orientation",
         "Jeden z mála objektů se zdrojovým roof_orientation=along; neověřený srovnávací údaj.", address=("V Domkách", "106")),
    spec("17100fb2-8669-4cd9-b825-2869359e41e5", "Velký průmyslový objekt – východ areálu Jihostroje", "industrial_flat_candidate",
         "Rozsáhlá střecha se zdrojovým flat, potenciální nástavby a lokální nerovnosti.", status="source_geometry",
         note="Průmyslová třída ze zdroje; identita konkrétní výrobní haly neověřena."),
    spec("89e6de12-a5b9-4a64-9853-743608e8e3d6", "Průmyslový objekt – střed areálu Jihostroje", "industrial_gabled_candidate",
         "Velká střecha se zdrojovým gabled: ověřit, zda je jednoduchá nebo složená.", status="source_geometry",
         note="Průmyslová třída ze zdroje; atribut gabled není ověřená pravda o jednotlivých střešních sekcích."),
    spec("2ad2977f-8e93-4ad1-a3d7-2c1228c064cd", "Garáž ve Strahovské – adresní číslo 14", "small_garage",
         "Drobný objekt kolem 17 m² v řadě; test minimálního počtu bodů a neslučování sousedů.", address=("Strahovská", "14")),
]


def fingerprint(path):
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def source_ids(row):
    return [s["record_id"].split("@")[0] for s in row.get("sources") or [] if s.get("record_id")]


def create_sample(data_dir):
    if len(SAMPLE) != 30 or len({s["building_id"] for s in SAMPLE}) != 30:
        raise ValueError("The reviewed sample must contain exactly 30 unique footprints")
    input_names = ("building", "address", "places", "infrastructure")
    paths = [data_dir / f"{name}.parquet" for name in input_names]
    for path in paths:
        if not path.is_file() or path.stat().st_size > 20 * 1024**2:
            raise ValueError(f"Missing or unexpectedly large local input: {path}")
    buildings = {r["id"]: r for r in pq.read_table(paths[0]).to_pylist()}
    addresses = pq.read_table(paths[1]).to_pylist()
    places = pq.read_table(paths[2]).to_pylist()
    infra = pq.read_table(paths[3]).to_pylist()
    to_m = Transformer.from_crs(4326, 5514, always_xy=True).transform
    to_ll = Transformer.from_crs(5514, 4326, always_xy=True).transform
    address_points = [(r, shapely.from_wkb(r["geometry"])) for r in addresses]
    place_points = [(r, shapely.from_wkb(r["geometry"])) for r in places]
    features, metric_geometries = [], []
    source_path = ROOT / REFERENCES["sportcentrum_reference"]["path"]
    sport_source = json.loads(source_path.read_text(encoding="utf-8"))
    for index, item in enumerate(SAMPLE, start=1):
        row = buildings[item["building_id"]]
        geom = shapely.from_wkb(row["geometry"])
        if geom.geom_type not in ("Polygon", "MultiPolygon") or not geom.is_valid or geom.is_empty:
            raise ValueError(f"Invalid source footprint: {row['id']}")
        gm = shapely.transform(geom, to_m, interleaved=False)
        metric_geometries.append(gm)
        centroid = shapely.transform(gm.centroid, to_ll, interleaved=False)
        matched_addresses = [r for r, point in address_points if geom.covers(point)]
        expected = item["required_address"]
        if expected and not any((r["street"], r["number"]) == tuple(expected) for r in matched_addresses):
            raise ValueError(f"Expected address no longer inside {row['id']}: {expected}")
        if item["required_name"] and (row.get("names") or {}).get("primary") != item["required_name"]:
            raise ValueError(f"Expected name changed for {row['id']}")
        infrastructure_evidence = []
        if item["infrastructure_way"]:
            way = item["infrastructure_way"]
            infrastructure_evidence = [{"id": r["id"], "class": r["class"], "sources": r["sources"],
                                        "source_tags": dict(r.get("source_tags") or [])}
                                       for r in infra if way in source_ids(r)]
            if way not in source_ids(row) or not any(r["class"] == "water_tower" for r in infrastructure_evidence):
                raise ValueError("Water tower cross-layer identity check failed")
        if item["group_id"] == "sportcentrum" and sport_source["source_building_id"] != row["id"]:
            raise ValueError("Sportcentrum source building no longer matches")
        polygons = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        attributes = {key: row.get(key) for key in (
            "class", "subtype", "height", "min_height", "num_floors", "has_parts", "roof_shape",
            "roof_direction", "roof_orientation", "roof_height", "roof_material", "version")}
        footprint_ids = source_ids(row)
        osm_links = ["https://www.openstreetmap.org/way/" + s[1:] for s in footprint_ids if s.startswith("w")]
        props = {
            "pilot_id": f"VEL-ROOF-{index:02d}", "building_id": row["id"],
            "name": item["name"], "category": item["category"],
            "group_id": item["group_id"] or f"building:{row['id']}",
            "selection_reason": item["reason"],
            "centroid_wgs84": {"lon": round(centroid.x, 9), "lat": round(centroid.y, 9)},
            "bbox_wgs84": list(geom.bounds),
            "bbox_epsg5514": [round(v, 3) for v in gm.bounds],
            "footprint_area_m2": round(gm.area, 3),
            "exterior_vertex_count": sum(len(p.exterior.coords) - 1 for p in polygons),
            "source_attributes": attributes, "source_names": row.get("names"),
            "footprint_sources": row["sources"], "osm_urls": osm_links,
            "addresses": [{"id": r["id"], "street": r["street"], "number": r["number"],
                           "postal_city": r["postal_city"], "sources": r["sources"]} for r in matched_addresses],
            "contained_places": [{"id": r["id"], "name": (r.get("names") or {}).get("primary"),
                                  "websites": r.get("websites"), "confidence": r.get("confidence"),
                                  "note": "POI poloha je pomocná indicie, nikoli samostatné ověření identity."}
                                 for r, point in place_points if geom.covers(point)],
            "identity": {"status": item["identity_status"], "note": item["identity_note"],
                         "reference_keys": item["references"],
                         "address_containment_checked": bool(expected),
                         "infrastructure_evidence": infrastructure_evidence},
            "roof_ground_truth": {"status": "not_surveyed",
                                  "note": "roof_shape/orientation jsou pouze zdrojové atributy, ne ověřená referenční pravda."},
        }
        if item["group_id"] == "sportcentrum":
            props["reference_model"] = REFERENCES["sportcentrum_reference"]["path"]
            props["roof_ground_truth"] = {"status": "user_reviewed_simplified_reference",
                "note": "Tenisová hala má válcovou střechu, celek více výšek a průchod; dřívější model není nezávislé zaměření."}
        features.append({"type": "Feature", "id": row["id"], "bbox": list(geom.bounds),
                         "geometry": mapping(geom), "properties": props})
    union = shapely.union_all(metric_geometries)
    wgs_union = shapely.transform(union, to_ll, interleaved=False)
    groups = {}
    for feature in features:
        p = feature["properties"]
        groups.setdefault(p["group_id"], []).append(p["pilot_id"])
    doc = {
        "type": "FeatureCollection", "schema_version": 1, "city": "velesin",
        "selection_date": REVIEW_DATE, "selection_method": "reviewed_fixed_source_ids",
        "feature_count": len(features), "bbox": list(wgs_union.bounds),
        "bbox_epsg5514": [round(v, 3) for v in union.bounds],
        "coordinate_system": {"geometry": "OGC:CRS84 (longitude, latitude)", "metric_bounds": "EPSG:5514"},
        "category_counts": dict(sorted(Counter(f["properties"]["category"] for f in features).items())),
        "groups": groups,
        "limitations": [
            "30 půdorysů není 30 samostatných architektonických celků: radnice má 2 a kostel Jakub 3 zdrojové budovy.",
            "Půdorysy jsou beze změny převzaty z lokální Overture cache; nejde o výsledek rekonstrukce ani zeměměřické ověření.",
            "Identita MŠ je ověřena adresou. Západní členitý objekt je pouze kandidát části areálu; nová přístavba není doložena.",
            "Zdrojové typy střech a počty podlaží slouží ke stratifikaci; při vyhodnocení metody se nesmějí vydávat za ground truth.",
            "Výběr je účelový pilot pro různé geometrie, nikoli statisticky reprezentativní vzorek celého města.",
            "Podloubí a průchody z těchto půdorysů nejsou odvozeny; Sportcentrum slouží jako známý samostatný příklad průchodu.",
        ],
        "source_inputs": [fingerprint(p) for p in paths] + [fingerprint(source_path)],
        "identity_references": {key: dict(value, checked_on=REVIEW_DATE) for key, value in REFERENCES.items()},
        "features": features,
    }
    return doc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true", help="Verify existing output exactly matches local inputs; do not write")
    args = parser.parse_args()
    document = create_sample(args.data_dir.resolve())
    payload = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if len(payload.encode("utf-8")) > 1024**2:
        raise ValueError("Unexpectedly large sample: refusing output above 1 MiB")
    output = args.output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("Output must remain inside this project")
    if args.check:
        if output.read_text(encoding="utf-8") != payload:
            raise ValueError("Existing sample does not match the reviewed selection and source inputs")
    else:
        free = shutil.disk_usage(ROOT).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f"Stopped: project drive free space is below 25 GiB ({free / 1024**3:.2f} GiB)")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(json.dumps({"output": str(output), "checked": args.check,
                      "features": document["feature_count"], "groups": len(document["groups"]),
                      "bytes": len(payload.encode("utf-8")), "bbox_epsg5514": document["bbox_epsg5514"],
                      "category_counts": document["category_counts"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
