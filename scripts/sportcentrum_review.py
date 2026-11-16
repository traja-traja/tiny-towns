"""Make exact, local review figures from the saved survey data (no network)."""
import csv
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "podklady/sportcentrum-velesin"
SOURCE = ROOT / "cities/velesin/models/sportcentrum-velesin.source.json"
PALETTE = [(240, 190, 30), (240, 100, 60), (240, 150, 80), (60, 190, 240), (200, 100, 230)]


def font(size):
    path = Path("C:/Windows/Fonts/segoeui.ttf")
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)


def main():
    model = json.loads(SOURCE.read_text(encoding="utf-8"))
    manifest = json.loads((OUT / "download-manifest.json").read_text(encoding="utf-8"))
    bbox = manifest["bbox"]
    angle = math.radians(model["axis_bearing_degrees"])
    u = np.array([math.sin(angle), math.cos(angle)])
    v = np.array([-u[1], u[0]])
    transform = Transformer.from_crs(4326, 5514, always_xy=True)
    kx = math.cos(math.radians(48.82944)) * 111320
    def pixel(uv):
        east, north = u * uv[0] + v * uv[1]
        x, y = transform.transform(model["anchor"]["lon"] + east / kx,
                                   model["anchor"]["lat"] + north / 110574)
        return ((x - bbox[0]) * 1280 / (bbox[2] - bbox[0]),
                (bbox[3] - y) * 1280 / (bbox[3] - bbox[1]))
    image = Image.new("RGB", (1280, 1485), "#18232a")
    image.paste(Image.open(OUT / "ortofoto-cuzk-detail.jpg"), (0, 0))
    draw = ImageDraw.Draw(image)
    for number, part in enumerate(model["components"], 1):
        points = [pixel(p) for p in part["footprint_uv"]]
        color = PALETTE[number - 1]
        draw.line(points + points[:1], fill=color, width=3)
        cx, cy = np.mean(points, axis=0)
        draw.ellipse((cx - 14, cy - 14, cx + 14, cy + 14), fill=color, outline="#111111", width=2)
        draw.text((cx, cy - 1), str(number), fill="#111111", font=font(20), anchor="mm")
        draw.text((24 + (number > 3) * 690, 1295 + ((number - 1) % 3) * 38),
                  f"{number}. {part['name'].replace('Sportcentrum Velešín – ', '').replace('Sportcentrum – ', '')}",
                  font=font(23), fill=color)
    draw.text((24, 1435), "ČÚZK · CC BY 4.0 · výřez 160 × 160 m · barevné hranice jsou interpretace modelu", fill="white", font=font(21))
    image.save(OUT / "ortofoto-s-vyznacenim.png")

    heights = np.asarray(Image.open(OUT / "dmp-cuzk-05m.tif"))
    low, high = 530, 545
    stops = np.array([[25, 36, 80], [30, 125, 155], [120, 190, 100], [250, 210, 70]], dtype=float)
    t = np.clip((heights - low) / (high - low), 0, 1) * 3
    i = np.minimum(t.astype(int), 2)
    rgb = (stops[i] * (1 - (t-i)[..., None]) + stops[i+1] * (t-i)[..., None]).astype("uint8")
    figure = Image.new("RGB", (1000, 1110), "#18232a")
    figure.paste(Image.fromarray(rgb).resize((1000, 1000), Image.Resampling.NEAREST))
    draw = ImageDraw.Draw(figure)
    for j in range(800):
        a = min(j / 800 * 3, 2.999)
        c = (stops[int(a)] * (1-a % 1) + stops[int(a)+1] * (a % 1)).astype(int)
        draw.line((100+j, 1020, 100+j, 1040), fill=tuple(c))
    draw.text((100, 1044), "530 m", fill="white", font=font(20))
    draw.text((900, 1044), "545 m n. m.", fill="white", font=font(20), anchor="ra")
    draw.text((25, 1080), "ČÚZK DMP · buňka 0,5 m · výška povrchu včetně stromů a budov", fill="white", font=font(20))
    figure.save(OUT / "dmp-vysky.png")

    rows = list(csv.DictReader((OUT / "strecha-profil.csv").open(encoding="utf-8")))
    chart = Image.new("RGB", (1280, 700), "#f7f8fa")
    draw = ImageDraw.Draw(chart)
    def point(vv, zz):
        return (100 + (vv + 20) / 21 * 1110, 570 - zz / 13 * 450)
    draw.text((50, 28), "Tenisová hala: příčný profil střechy", fill="#172b38", font=font(30))
    draw.text((50, 70), "Výška nad referenčním terénem 533,5 m · profil odvozený z dat ČÚZK", fill="#455867", font=font(20))
    for z in range(0, 13, 2):
        x0, y = point(-20, z)
        draw.line((x0, y, 1210, y), fill="#ccd4da", width=1)
        draw.text((80, y), str(z), fill="#233746", font=font(18), anchor="rm")
    for vv in range(-20, 1, 5):
        x, y = point(vv, 0)
        draw.text((x, y + 12), str(vv), fill="#233746", font=font(18), anchor="ma")
    roof = model["components"][0]["roof"]
    ps = []
    for vv in np.linspace(-19.35, 0, 250):
        h = roof["ridge_m"] - roof["radius_m"] + math.sqrt(max(0, roof["radius_m"]**2-(vv-roof["centre_v"])**2))
        ps.append(point(vv, h))
    draw.line(ps, fill="#218650", width=4)
    for row in rows:
        if row["laz_median_m"] and row["fit"] == "1":
            x, y = point(float(row["v_m"]), float(row["laz_median_m"]) - 533.5)
            draw.ellipse((x-5, y-5, x+5, y+5), fill="#dc692b")
    draw.text((80, 625), "● Laserové body: medián v pásu     — Zjednodušený půlválec v modelu", fill="#233746", font=font(23))
    draw.text((80, 662), "Okraje oblouku jsou méně jisté; křivka je přizpůsobena šířce půdorysu.", fill="#52606b", font=font(20))
    chart.save(OUT / "profil-strechy.png")
    print("Saved ortho annotation, surface height map and measured roof profile")


if __name__ == "__main__":
    main()
