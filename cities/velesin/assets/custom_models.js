export const landmarks = {
  tiny_towns_mesh(building, { R, X, C255, tv, pushTri }) {
    const { vertices, faces, materials } = building.tt_mesh;
    const points = vertices.map(([east, north, up]) => tv(east, north, up));
    const surfaces = materials.map(({ color, kind }) => ({
      buffer: kind === 'roof' ? R : X,
      color: C255(color),
      attributes: kind === 'roof' ? [0, 0, 0, 0] : [0, 1, 0, 0],
    }));
    for (const [a, b, c, materialIndex] of faces) {
      const { buffer, color, attributes } = surfaces[materialIndex];
      pushTri(buffer, points[a], points[b], points[c], color, attributes);
    }
    return true;
  },
};
