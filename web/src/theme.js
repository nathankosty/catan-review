// Player + resource palettes and the chess.com-style label styling.

export const PLAYER_COLORS = {
  RED: "#e03131",
  BLUE: "#1c7ed6",
  ORANGE: "#f08c00",
  WHITE: "#ced4da",
};
export const PLAYER_TEXT = { WHITE: "#212529" }; // readable label on light chip

export const RES_ICON = {
  WOOD: "🌲", BRICK: "🧱", SHEEP: "🐑", WHEAT: "🌾", ORE: "⛰️",
};

export const RESOURCE_COLORS = {
  WOOD: "#2f9e44",
  BRICK: "#e8590c",
  SHEEP: "#94d82d",
  WHEAT: "#fcc419",
  ORE: "#868e96",
  DESERT: "#e9d8a6",
};

// Label -> { color, glyph } for the move list / decision panel.
export const LABEL_STYLE = {
  Brilliant: { color: "#1098ad", glyph: "✦" },
  Great: { color: "#0ca678", glyph: "★" },
  Best: { color: "#37b24d", glyph: "✓" },
  Excellent: { color: "#74b816", glyph: "▲" },
  Good: { color: "#82a33d", glyph: "•" },
  Book: { color: "#7048e8", glyph: "📖" },
  Inaccuracy: { color: "#f59f00", glyph: "?!" },
  Mistake: { color: "#f76707", glyph: "?" },
  Miss: { color: "#e8590c", glyph: "⦰" },
  Blunder: { color: "#e03131", glyph: "??" },
  Forced: { color: "#868e96", glyph: "·" },
};

export const LABEL_ORDER = [
  "Brilliant", "Great", "Best", "Excellent", "Good", "Book",
  "Inaccuracy", "Mistake", "Miss", "Blunder",
];

export function playerColor(c) {
  return PLAYER_COLORS[c] || "#868e96";
}
