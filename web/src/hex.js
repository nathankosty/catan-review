// Hex-grid math for rendering Catanatron's cube coordinates (Red Blob Games).
// Catan tiles are pointy-top (a vertex points up = NORTH, down = SOUTH).

export const SIZE = 46; // hex "radius" in px

// Catanatron uses cube coords [x, y, z] with x + y + z = 0. Map to axial (q, r).
export function cubeToPixel([x, , z]) {
  const q = x, r = z;
  return {
    x: SIZE * Math.sqrt(3) * (q + r / 2),
    y: SIZE * (3 / 2) * r,
  };
}

// Corner offsets for a pointy-top hex, keyed by Catanatron NodeRef direction.
const ANGLE = {
  NORTH: -90, NORTHEAST: -30, SOUTHEAST: 30,
  SOUTH: 90, SOUTHWEST: 150, NORTHWEST: 210,
};

export function cornerOffset(direction) {
  const a = (ANGLE[direction] * Math.PI) / 180;
  return { x: SIZE * Math.cos(a), y: SIZE * Math.sin(a) };
}

export function hexPolygon(center) {
  return ["NORTH", "NORTHEAST", "SOUTHEAST", "SOUTH", "SOUTHWEST", "NORTHWEST"]
    .map((d) => {
      const o = cornerOffset(d);
      return `${(center.x + o.x).toFixed(1)},${(center.y + o.y).toFixed(1)}`;
    })
    .join(" ");
}

// Pixel position of a node, given the geometry node record {tile_coord, direction}.
export function nodePixel(node) {
  const c = cubeToPixel(node.tile_coord);
  const o = cornerOffset(node.direction);
  return { x: c.x + o.x, y: c.y + o.y };
}

// Compute pixel positions for every node id once.
export function nodePositions(nodes) {
  const pos = {};
  for (const [id, node] of Object.entries(nodes)) pos[id] = nodePixel(node);
  return pos;
}

export function bounds(points, pad = SIZE) {
  const xs = points.map((p) => p.x), ys = points.map((p) => p.y);
  const minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad;
  const minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
  return { minX, minY, w: maxX - minX, h: maxY - minY };
}
