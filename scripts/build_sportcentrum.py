"""Build portable Sportcentrum geometry from the reviewed city source description.

No network or renderer dependencies. Coordinates are metres east/north/up from a
WGS84 anchor; GLB uses x=east, y=up, z=-north. Run with the project's Python.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import struct

from shapely.geometry import Polygon
from shapely.ops import triangulate

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cities/velesin/models/sportcentrum-velesin.source.json"
OUTPUT = ROOT / "cities/velesin/assets/models"


def build_model(source):
    angle = math.radians(source["axis_bearing_degrees"])
    along = (math.sin(angle), math.cos(angle))
    across = (-along[1], along[0])
    def xyz(u, v, z):
        return [round(u * along[0] + v * across[0], 5),
                round(u * along[1] + v * across[1], 5), round(z, 5)]

    result = {key: source[key] for key in (
        "schema_version", "id", "source_building_id", "units", "coordinate_system",
        "anchor", "reference_ground_absolute_m", "materials", "sources", "uncertainties")}
    result["components"] = []
    for part in source["components"]:
        vertices, faces = [], []
        vertex_ids = {}
        def vertex(p):
            key = tuple(p)
            if key not in vertex_ids:
                vertex_ids[key] = len(vertices)
                vertices.append(p)
            return vertex_ids[key]
        def tri(points, material):
            faces.append([*(vertex(xyz(*p)) for p in points), material])
        def quad(points, material):
            tri(points[:3], material)
            tri([points[0], points[2], points[3]], material)

        footprint = part["footprint_uv"]
        poly = Polygon(footprint)
        if not poly.is_valid or poly.area <= 0:
            raise ValueError(f"Invalid footprint: {part['id']}")
        # All rings and outward wall normals use counterclockwise ENU order.
        from shapely.geometry.polygon import orient
        footprint = list(orient(poly, sign=1).exterior.coords)[:-1]
        poly = Polygon(footprint)
        wall, roof = part["wall_material"], part["roof_material"]
        bottom = part.get("base_m", -2.0)
        if part["roof"]["type"] == "circular_segment":
            data = part["roof"]
            u0, v0, u1, v1 = poly.bounds
            centre = data.get("centre_v", (v0 + v1) / 2)
            radius = data["radius_m"]
            ridge = data["ridge_m"]
            def z(v):
                return ridge - radius + math.sqrt(max(0, radius * radius - (v - centre) ** 2))
            vs = [v0 + (v1 - v0) * i / 32 for i in range(33)]
            # Add the actual crest to preserve the documented maximum height.
            vs = sorted(set(vs + ([centre] if v0 < centre < v1 else [])))
            for a, b in zip(vs, vs[1:]):
                za, zb = z(a), z(b)
                quad([(u0, a, za), (u1, a, za), (u1, b, zb), (u0, b, zb)], roof)
                quad([(u0, b, bottom), (u0, a, bottom), (u0, a, za), (u0, b, zb)], wall)
                quad([(u1, a, bottom), (u1, b, bottom), (u1, b, zb), (u1, a, za)], wall)
                quad([(u0, b, bottom), (u1, b, bottom), (u1, a, bottom), (u0, a, bottom)], wall)
            quad([(u0, v0, bottom), (u1, v0, bottom), (u1, v0, z(v0)), (u0, v0, z(v0))], wall)
            quad([(u1, v1, bottom), (u0, v1, bottom), (u0, v1, z(v1)), (u1, v1, z(v1))], wall)
            height, eave = ridge, min(z(v0), z(v1))
        elif part["roof"]["type"] == "flat":
            height = eave = part["roof"]["height_m"]
            for a, b in zip(footprint, footprint[1:] + footprint[:1]):
                quad([(*a, bottom), (*b, bottom), (*b, height), (*a, height)], wall)
            roof_area = 0.0
            for triangle in triangulate(poly):
                if not poly.covers(triangle):
                    continue
                pts = list(orient(triangle, sign=1).exterior.coords)[:3]
                tri([(*p, height) for p in pts], roof)
                tri([(*p, bottom) for p in reversed(pts)], wall)
                roof_area += triangle.area
            if abs(roof_area - poly.area) > 1e-6:
                raise ValueError(f"Incomplete roof triangulation: {part['id']}")
        else:
            raise ValueError("Unknown roof type")
        result["components"].append({
            "id": part["id"], "name": part["name"],
            "footprint": [xyz(u, v, 0)[:2] for u, v in footprint],
            "height_m": round(height, 5), "eave_height_m": round(eave, 5),
            "mesh": {"vertices": vertices, "faces": faces},
        })
    return result


def glb_bytes(model):
    """Small self-contained glTF 2.0 exporter; indexed triangles and PBR colors."""
    binary = bytearray()
    document = {"asset": {"version": "2.0", "generator": "Tiny Towns / build_sportcentrum.py"},
                "scene": 0, "scenes": [{"nodes": []}], "nodes": [], "meshes": [],
                "buffers": [], "bufferViews": [], "accessors": [], "materials": [],
                "extras": {"anchorWGS84": model["anchor"], "units": "metres",
                           "approximateGroundElevationMetres": model["reference_ground_absolute_m"],
                           "axes": "X east, Y up, Z south", "sources": model["sources"],
                           "uncertainties": model["uncertainties"]}}
    def accessor(values, fmt, component_type, kind, target, bounds=None):
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        for item in values:
            binary.extend(struct.pack("<" + fmt, *item))
        view = len(document["bufferViews"])
        document["bufferViews"].append({"buffer": 0, "byteOffset": offset,
                                       "byteLength": len(binary) - offset, "target": target})
        record = {"bufferView": view, "componentType": component_type,
                  "count": len(values), "type": kind}
        if bounds:
            record.update(min=bounds[0], max=bounds[1])
        document["accessors"].append(record)
        return len(document["accessors"]) - 1
    def linear(channel):
        c = channel / 255
        return c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
    for material in model["materials"]:
        document["materials"].append({"name": material["id"], "pbrMetallicRoughness": {
            "baseColorFactor": [*(linear(c) for c in material["color"]), 1],
            "metallicFactor": 0, "roughnessFactor": .85}})
    for part in model["components"]:
        positions = [(x, z, -y) for x, y, z in part["mesh"]["vertices"]]
        bounds = [[min(p[i] for p in positions) for i in range(3)],
                  [max(p[i] for p in positions) for i in range(3)]]
        pos = accessor(positions, "fff", 5126, "VEC3", 34962, bounds)
        primitives = []
        for mat in range(len(model["materials"])):
            indices = [(i,) for face in part["mesh"]["faces"] if face[3] == mat for i in face[:3]]
            if indices:
                idx = accessor(indices, "I", 5125, "SCALAR", 34963)
                primitives.append({"attributes": {"POSITION": pos}, "indices": idx, "material": mat})
        document["meshes"].append({"name": part["name"], "primitives": primitives})
        document["nodes"].append({"mesh": len(document["meshes"]) - 1, "name": part["name"]})
        document["scenes"][0]["nodes"].append(len(document["nodes"]) - 1)
    while len(binary) % 4:
        binary.append(0)
    document["buffers"] = [{"byteLength": len(binary)}]
    encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    length = 12 + 8 + len(encoded) + 8 + len(binary)
    return (struct.pack("<III", 0x46546C67, 2, length) + struct.pack("<II", len(encoded), 0x4E4F534A)
            + encoded + struct.pack("<II", len(binary), 0x004E4942) + binary)


def main():
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    model = build_model(source)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "sportcentrum-velesin.json").write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "sportcentrum-velesin.glb").write_bytes(glb_bytes(model))
    print(f"Built {len(model['components'])} parts, {sum(len(p['mesh']['faces']) for p in model['components'])} triangles")


if __name__ == "__main__":
    main()
