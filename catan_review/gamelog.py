"""Versioned JSON game format + board extraction (brief §6.3).

One schema serves three roles: import/export, the replay source, and the
self-play log. A log is reproducible from ``seed`` (engine + policy are
deterministic), so we store seed + the ordered action list and reconstruct
exactly by re-running. The recorded actions double as an integrity check.

Also here: board *geometry* (emitted once, drives hex rendering) and per-frame
board *occupancy* snapshots (drive the replay), plus human-readable action text.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional

from catanatron import Game, Color, Action, ActionType
import catanatron.json as J
import catanatron.state_functions as sf

from .engine import GameConfig, Trajectory, RESOURCES

SCHEMA_VERSION = "catan-review/1"
AT = ActionType


# --------------------------------------------------------------------------- #
# Action (de)serialization
# --------------------------------------------------------------------------- #

def _norm(v):
    if isinstance(v, Color):
        return {"__color__": v.value}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    return v


def _denorm(v):
    if isinstance(v, dict) and "__color__" in v:
        return Color(v["__color__"])
    if isinstance(v, list):
        return tuple(_denorm(x) for x in v)
    return v


def action_to_dict(a: Action) -> dict:
    return {"color": a.color.value, "type": a.action_type.name, "value": _norm(a.value)}


def action_from_dict(d: dict) -> Action:
    return Action(Color(d["color"]), ActionType[d["type"]], _denorm(d["value"]))


# --------------------------------------------------------------------------- #
# Human-readable action text (seeds annotations + the move list)
# --------------------------------------------------------------------------- #

RES_ICON = {"WOOD": "🌲", "BRICK": "🧱", "SHEEP": "🐑", "WHEAT": "🌾", "ORE": "⛰️"}


def _res(v):
    return v if isinstance(v, str) else str(v)


def _tile_tag(tile) -> Optional[str]:
    """'6🌾' for a numbered tile, 'desert' for the desert."""
    res = getattr(tile, "resource", None)
    if res is None:
        return "desert"
    num = getattr(tile, "number", None)
    return f"{num}{RES_ICON.get(res, res[0])}" if num is not None else None


def _node_desc(game: Game, node_id) -> str:
    """Describe an intersection by its adjacent tiles: 'the 6🌾/9⛰️ corner'."""
    try:
        tiles = game.state.board.map.adjacent_tiles.get(node_id, [])

        def pips(tile):  # strongest tiles first, desert last
            n = getattr(tile, "number", None)
            return 6 - abs(7 - n) if n is not None else -1

        tags = [t for t in (_tile_tag(x) for x in sorted(tiles, key=pips, reverse=True)) if t]
        loc = "/".join(tags[:3]) if tags else f"node {node_id}"
        for resource, node_ids in game.state.board.map.port_nodes.items():
            if node_id in node_ids:
                loc += f" ({'3:1' if resource is None else '2:1 ' + RES_ICON.get(resource, resource)} port)"
                break
        return f"the {loc} corner"
    except Exception:
        return f"node {node_id}"


def _edge_desc(game: Game, edge) -> str:
    """Describe a road edge by the tiles it borders."""
    try:
        a, b = tuple(edge)
        m = game.state.board.map
        ta = {id(t): t for t in m.adjacent_tiles.get(a, [])}
        tb = {id(t): t for t in m.adjacent_tiles.get(b, [])}
        shared = [t for k, t in ta.items() if k in tb]
        tags = [x for x in (_tile_tag(t) for t in (shared or list(ta.values()))) if x]
        return f"along the {'/'.join(tags[:2])} hex{'es' if len(tags[:2]) > 1 else ''}" if tags else f"road {tuple(edge)}"
    except Exception:
        return f"road {tuple(edge)}"


def _coord_desc(game: Game, coord) -> str:
    """Describe a hex by its token: 'the 8🐑 hex'."""
    try:
        tile = game.state.board.map.land_tiles.get(tuple(coord))
        tag = _tile_tag(tile) if tile is not None else None
        return f"the {tag} hex" if tag else "that hex"
    except Exception:
        return "that hex"


def action_to_human(a: Action, game: Optional[Game] = None) -> str:
    """One-line description. With ``game``, board locations are described by
    their adjacent tiles ('the 6🌾/9⛰️ corner') instead of raw node ids,
    players don't know what 'node 14' means."""
    c = a.color.value.title()
    t, v = a.action_type, a.value
    if t == AT.ROLL:
        total = sum(v) if isinstance(v, (list, tuple)) else "?"
        return f"{c} rolls {total}"
    if t == AT.BUILD_SETTLEMENT:
        where = _node_desc(game, v) if game is not None else f"node {v}"
        return f"{c} builds a settlement at {where}"
    if t == AT.BUILD_CITY:
        where = _node_desc(game, v) if game is not None else f"node {v}"
        return f"{c} upgrades to a city at {where}"
    if t == AT.BUILD_ROAD:
        where = _edge_desc(game, v) if game is not None else f"{tuple(v)}"
        return f"{c} builds a road {where}"
    if t == AT.BUY_DEVELOPMENT_CARD:
        return f"{c} buys a development card"
    if t == AT.PLAY_KNIGHT_CARD:
        return f"{c} plays a Knight"
    if t == AT.PLAY_YEAR_OF_PLENTY:
        picks = ", ".join(_res(x) for x in v if x) if isinstance(v, (list, tuple)) else _res(v)
        return f"{c} plays Year of Plenty (takes {picks})"
    if t == AT.PLAY_MONOPOLY:
        res = v[0] if isinstance(v, (list, tuple)) else v
        return f"{c} plays Monopoly on {_res(res)}"
    if t == AT.PLAY_ROAD_BUILDING:
        return f"{c} plays Road Building"
    if t == AT.MARITIME_TRADE:
        gives = [x for x in v[:-1] if x]
        return f"{c} trades {len(gives)} {_res(gives[0]) if gives else '?'} → 1 {_res(v[-1])} with the bank"
    if t == AT.MOVE_ROBBER:
        coord, victim, _ = v
        where = f" to {_coord_desc(game, coord)}" if game is not None else ""
        vt = f", steals from {Color(victim).value.title() if not isinstance(victim, Color) else victim.value.title()}" if victim else ""
        return f"{c} moves the robber{where}{vt}"
    if t == AT.DISCARD:
        return f"{c} discards (half of hand)"
    if t == AT.END_TURN:
        return f"{c} ends the turn"
    return f"{c} {t.name} {v}"


# --------------------------------------------------------------------------- #
# Board geometry (once) and occupancy snapshot (per frame)
# --------------------------------------------------------------------------- #

def board_geometry(game: Game) -> dict:
    """Static layout for the renderer: land hexes (cube coords + number/resource),
    node corner refs, edges, ports. Pixel math lives in the frontend."""
    enc = json.loads(json.dumps(game, cls=J.GameEncoder))
    land = [
        {
            "coord": t["coordinate"],
            "type": t["tile"]["type"],
            "resource": t["tile"].get("resource"),
            "number": t["tile"].get("number"),
            "id": t["tile"].get("id"),
        }
        for t in enc["tiles"]
        if t["tile"]["type"] in ("RESOURCE_TILE", "DESERT")
    ]
    # Restrict to the 54 land nodes / land edges (drop the ocean ring).
    land_nodes = set(game.state.board.map.land_nodes)
    nodes = {
        nid: {"tile_coord": n["tile_coordinate"], "direction": n["direction"]}
        for nid, n in enc["nodes"].items()
        if int(nid) in land_nodes
    }
    edges = [{"nodes": list(e["id"]), "tile_coord": e["tile_coordinate"], "direction": e["direction"]}
             for e in enc["edges"]
             if e["id"][0] in land_nodes and e["id"][1] in land_nodes]
    # Ports: Catanatron groups nodes by port *resource* (all four generic 3:1
    # ports arrive as one 8-node group). Split each group into the actual
    # 2-node ports by pairing adjacent nodes, so the renderer can place one
    # badge per physical port instead of a centroid in the middle of the board.
    adjacency = set()
    for e in enc["edges"]:
        a, b = e["id"]
        adjacency.add((min(a, b), max(a, b)))
    ports = []
    for resource, node_ids in game.state.board.map.port_nodes.items():
        remaining = sorted(node_ids)
        used = set()
        for a in remaining:
            if a in used:
                continue
            mate = next((b for b in remaining
                         if b != a and b not in used
                         and (min(a, b), max(a, b)) in adjacency), None)
            pair = [a] if mate is None else sorted([a, mate])
            used.update(pair)
            ports.append({"resource": resource, "nodes": pair})
    return {"tiles": land, "nodes": nodes, "edges": edges, "ports": ports}


def board_snapshot(game: Game) -> dict:
    """Per-frame occupancy + public player info for the replay."""
    enc = json.loads(json.dumps(game, cls=J.GameEncoder))
    buildings = {
        nid: {"color": n["color"], "type": n["building"]}
        for nid, n in enc["nodes"].items()
        if n["building"]
    }
    roads = [{"nodes": list(e["id"]), "color": e["color"]} for e in enc["edges"] if e["color"]]
    players = []
    s = game.state
    for c in s.colors:
        players.append({
            "color": c.value,
            "vp": sf.get_visible_victory_points(s, c),   # public VP only (no hidden cards)
            "resources": sf.player_num_resource_cards(s, c),
            "dev_cards": sf.get_dev_cards_in_hand(s, c),
            "longest_road": sf.get_longest_road_length(s, c),
            "played_knights": sf.get_played_dev_cards(s, c, "KNIGHT"),
            "has_longest_road": sf.get_longest_road_color(s) == c,
            "has_largest_army": (sf.get_largest_army(s) or (None,))[0] == c,
        })
    return {
        "buildings": buildings,
        "roads": roads,
        "robber": enc["robber_coordinate"],
        "players": players,
    }


# --------------------------------------------------------------------------- #
# GameLog
# --------------------------------------------------------------------------- #

@dataclass
class GameLog:
    version: str
    config: dict
    actions: List[dict]
    result: dict

    @staticmethod
    def from_trajectory(traj: Trajectory) -> "GameLog":
        actions = [action_to_dict(p.chosen) for p in traj.plies]
        return GameLog(
            version=SCHEMA_VERSION,
            config={
                "num_players": traj.config.num_players,
                "seed": traj.config.seed,
                "discard_limit": traj.config.discard_limit,
                "vps_to_win": traj.config.vps_to_win,
                "policy": "reference(eps=0.05)",
            },
            actions=actions,
            result={
                "winner": traj.winner.value if traj.winner else None,
                "num_turns": traj.num_turns,
                "hit_watchdog": traj.hit_watchdog,
            },
        )

    def to_json(self) -> dict:
        return asdict(self)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.to_json(), f, indent=2)

    @staticmethod
    def load(path: str) -> "GameLog":
        with open(path) as f:
            d = json.load(f)
        return GameLog(**d)
