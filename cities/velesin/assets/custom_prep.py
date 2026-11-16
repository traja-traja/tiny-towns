SPORTCENTRUM_SOURCE = '78e32d1e-ecfa-4e1b-a00f-db417ea5af1b'


def _install_sportcentrum(source_info):
    from pathlib import Path

    model_path = Path('assets/models/sportcentrum-velesin.json')
    with model_path.open(encoding='utf-8') as stream:
        model = json.load(stream)
    if (model['schema_version'], model['source_building_id'], model['units'], model['coordinate_system']) != (
        1, SPORTCENTRUM_SOURCE, 'metres', 'local-east-north-up',
    ):
        raise ValueError(f'Neznámý formát nebo zdroj modelu: {model_path}')

    components = model['components']
    if not components:
        raise ValueError(f'V modelu chybí části budovy: {model_path}')

    anchor = model['anchor']
    anchor_x, anchor_y = map(float, to_local(anchor['lon'], anchor['lat']))
    datum = float(ground(anchor_x, anchor_y))
    materials = model['materials']
    if any(material['kind'] not in ('wall', 'roof') for material in materials):
        raise ValueError(f'Neznámý druh materiálu: {model_path}')

    source_index = source_info['id']
    first_append_index = len(buildings)
    placements = []
    for index, component in enumerate(components):
        mesh = component['mesh']
        footprint = [[round(anchor_x + east, 2), round(anchor_y + north, 2)] for east, north in component['footprint']]
        polygon = Polygon(footprint)
        vertices = [[round(anchor_x + east, 3), round(anchor_y + north, 3), round(datum + up, 3)]
                    for east, north, up in mesh['vertices']]
        faces = mesh['faces']
        if not polygon.is_valid or polygon.is_empty or not vertices or not faces:
            raise ValueError(f'V modelu chybí platná geometrie části {component["id"]}: {model_path}')
        for i, j, k, material in faces:
            if not all(0 <= vertex < len(vertices) for vertex in (i, j, k)) or not 0 <= material < len(materials):
                raise ValueError(f'Neplatný index sítě části {component["id"]}: {model_path}')

        colors = {}
        for _, _, _, material_index in faces:
            material = materials[material_index]
            colors.setdefault(material['kind'], material['color'])
        height, eave = component['height_m'], component['eave_height_m']
        rise = height - eave
        roof = 'barrel' if index == 0 else 'flat' if rise == 0 else None
        base = min(vertex[2] for vertex in vertices)
        building_id = source_index if index == 0 else first_append_index + index - 1
        lon, lat = to_lonlat(polygon.centroid.x, polygon.centroid.y)
        replacement = {
            'id': building_id, 'p': footprint, 'b': base, 'g': round(datum, 3),
            'e': round(datum + eave, 3), 'rh': round(rise, 3), 'r': roof or 'flat', 'parts': [],
            'wc': colors.get('wall', buildings[source_index]['wc']),
            'rc': colors.get('roof', buildings[source_index]['rc']),
            's': 0, 'only': 1, 'lm': 'tiny_towns_mesh',
            'tt_mesh': {'vertices': vertices, 'faces': faces, 'materials': materials},
        }
        info = {
            **source_info,
            'id': building_id,
            'oid': SPORTCENTRUM_SOURCE if index == 0 else f'{model["id"]}/{component["id"]}',
            'name': component['name'], 'ring': footprint, 'base': base,
            'h': round(height, 1), 'top': round(datum + height, 3), 'roof': roof,
            'lon': round(float(lon), 6), 'lat': round(float(lat), 6),
            'addr': source_info['addr'] if index == 0 else [],
        }
        info.pop('roof_geometry', None)
        placements.append((replacement, info))

    buildings[source_index], info = placements[0]
    source_info.clear()
    source_info.update(info)
    for replacement, info in placements[1:]:
        buildings.append(replacement)
        binfo.append(info)
    chimneys[:] = [chimney for chimney in chimneys if chimney[3] != source_index]


if HOOK == 'props':
    # binfo contains the owner tile only. The hall lies well inside the centre tile.
    _sportcentrum_source = next((item for item in binfo if item['oid'] == SPORTCENTRUM_SOURCE), None)
    if _sportcentrum_source is not None:
        _install_sportcentrum(_sportcentrum_source)
