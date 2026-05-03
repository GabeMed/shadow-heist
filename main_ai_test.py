# main_ai_test.py
"""
Phase 2 smoke test — Vision Cone & Light-Aware Detection
---------------------------------------------------------
Standalone: no ShadowHeist, Player, or LevelManager imported.
Uses minimal inline stubs that satisfy the interface contract so the guard
code runs identically to how it will run inside the real game.

Scene
-----
  • Dark ground plane.
  • Three red waypoint pillars.
  • One guard (green card) patrolling the route.
  • One mock player (yellow card) — move it with WASD.
  • Two invisible wall planes forming a cross — walk the player behind one
    to observe occlusion dropping confidence to 0.

Controls
--------
  W / A / S / D   Move mock player
  Q / E           Decrease / increase size factor (1.0 – 3.0)
  C               Toggle crouching
  V               Toggle camouflage (is_visible)
  L               Toggle global lighting (lit / dark)
  Escape          Quit

HUD (top-left)  Guard info + confidence bar.
HUD (mid-left)  Player info.

Run
---
  python main_ai_test.py
"""

from __future__ import annotations
import sys
import os
import math

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    Point3, Vec3,
    AmbientLight, DirectionalLight,
    CardMaker, TextNode,
    WindowProperties, NodePath,
    CollisionNode, CollisionPlane, Plane,
    BitMask32,
)

sys.path.insert(0, os.path.dirname(__file__))

from src.guard.waypoint import Waypoint
from src.guard.guard import Guard
from src.guard.fov_component import (
    WALL_BITMASK,
    CURIOUS_THRESHOLD,
    SUSPICIOUS_THRESHOLD,
)

# ── scene config ──────────────────────────────────────────────────────────────
TEST_WAYPOINTS = [
    # (x,    y,    z,   wait_seconds)
    ( 0.0,  8.0,  0.0,  2.5),
    ( 8.0, -4.0,  0.0,  1.0),
    (-8.0, -4.0,  0.0,  1.5),
]
PLAYER_MOVE_SPEED: float = 6.0
SIZE_STEP:         float = 0.25


# ── inline stubs (satisfy interface contract, nothing more) ───────────────────

class _StubPlayer:
    """Minimal player stub for the isolated smoke test."""

    def __init__(self, position: Point3) -> None:
        self._pos:         Point3 = Point3(position)
        self._size_factor: float  = 1.0
        self._crouching:   bool   = False
        self._visible:     bool   = True

    # interface contract
    def get_position(self)    -> Point3: return Point3(self._pos)
    def get_size_factor(self) -> float:  return self._size_factor
    def get_is_sprinting(self)-> bool:   return False
    def get_is_crouching(self)-> bool:   return self._crouching
    def get_node_path(self)   -> NodePath: return NodePath("stub_player")
    def is_visible(self)      -> bool:   return self._visible

    # test controls
    def move(self, dx: float, dy: float) -> None:
        self._pos = Point3(self._pos.x + dx, self._pos.y + dy, self._pos.z)

    def set_size_factor(self, v: float) -> None:
        self._size_factor = max(1.0, min(3.0, v))

    def toggle_crouch(self) -> None:
        self._crouching = not self._crouching

    def toggle_visible(self) -> None:
        self._visible = not self._visible


class _StubEnv:
    """Minimal env stub for the isolated smoke test."""

    def __init__(self) -> None:
        self._lit: bool = True

    def is_position_lit(self, pos: Point3) -> bool:
        return self._lit

    def get_active_light_nodes(self) -> list:
        return []

    def get_nav_mesh(self) -> NodePath:
        return NodePath("stub_nav")

    def toggle_lit(self) -> None:
        self._lit = not self._lit


# ── app ───────────────────────────────────────────────────────────────────────

class GuardTestApp(ShowBase):

    def __init__(self) -> None:
        super().__init__()
        self._configure_window()
        self._setup_lighting()
        self._build_ground()
        self._build_waypoint_markers()
        self._build_wall_occluders()

        self._stub_player = _StubPlayer(Point3(4.0, 4.0, 0.0))
        self._stub_env    = _StubEnv()

        self._spawn_guard()
        self._spawn_player_marker()
        self._setup_camera()
        self._setup_hud()
        self._setup_keybinds()

        self._keys: dict[str, bool] = {k: False for k in ("w", "s", "a", "d")}
        self.taskMgr.add(self._update_task, "frame_update")

    # ── window ────────────────────────────────────────────────────────────────

    def _configure_window(self) -> None:
        props = WindowProperties()
        props.setTitle("SHADOW-HEIST — Guard AI Test [Phase 2]")
        props.setSize(1280, 720)
        self.win.requestProperties(props)
        self.setBackgroundColor(0.08, 0.08, 0.12)

    # ── lighting ──────────────────────────────────────────────────────────────

    def _setup_lighting(self) -> None:
        al = AmbientLight("ambient")
        al.setColor((0.35, 0.35, 0.40, 1.0))
        self.render.setLight(self.render.attachNewNode(al))

        dl = DirectionalLight("sun")
        dl.setColor((0.85, 0.85, 0.75, 1.0))
        dl_np = self.render.attachNewNode(dl)
        dl_np.setHpr(45, -60, 0)
        self.render.setLight(dl_np)

    # ── ground ────────────────────────────────────────────────────────────────

    def _build_ground(self) -> None:
        cm = CardMaker("ground")
        cm.setFrame(-30, 30, -30, 30)
        g = self.render.attachNewNode(cm.generate())
        g.setColor(0.18, 0.18, 0.18, 1.0)
        g.setP(-90)
        g.setPos(0, 0, -0.01)

    # ── waypoint markers ──────────────────────────────────────────────────────

    def _build_waypoint_markers(self) -> None:
        for i, (x, y, z, _) in enumerate(TEST_WAYPOINTS):
            cm = CardMaker(f"wp_{i}")
            cm.setFrame(-0.15, 0.15, 0.0, 0.9)
            p = self.render.attachNewNode(cm.generate())
            p.setColor(0.9, 0.2, 0.2, 1.0)
            p.setPos(x, y, z)
            p.setBillboardPointEye()

            tn = TextNode(f"wpl_{i}")
            tn.setText(f"WP{i}")
            tn.setAlign(TextNode.ACenter)
            lbl = self.render.attachNewNode(tn)
            lbl.setScale(0.28)
            lbl.setPos(x, y, z + 1.05)
            lbl.setBillboardPointEye()

    # ── wall occluders ────────────────────────────────────────────────────────

    def _build_wall_occluders(self) -> None:
        """
        Two invisible collision planes (cross pattern) to demonstrate
        ray occlusion.  Tagged with WALL_BITMASK so FOVComponent picks them up.
        """
        walls = [
            (Vec3(1, 0, 0), "wall_vertical"),
            (Vec3(0, 1, 0), "wall_horizontal"),
        ]
        for normal, label in walls:
            cn = CollisionNode(label)
            cn.addSolid(CollisionPlane(Plane(normal, Point3(0, 0, 0))))
            cn.setFromCollideMask(BitMask32.allOff())
            cn.setIntoCollideMask(WALL_BITMASK)
            self.render.attachNewNode(cn)

    # ── guard ─────────────────────────────────────────────────────────────────

    def _spawn_guard(self) -> None:
        waypoints = [
            Waypoint(position=Point3(x, y, z), wait_time=w)
            for (x, y, z, w) in TEST_WAYPOINTS
        ]
        self._guard = Guard(
            base=self,
            waypoints=waypoints,
            player=self._stub_player,
            env=self._stub_env,
            name="GuardA",
            fov_debug=False,
        )
        self._guard.start()

    # ── player marker ─────────────────────────────────────────────────────────

    def _spawn_player_marker(self) -> None:
        cm = CardMaker("player_card")
        cm.setFrame(-0.35, 0.35, 0.0, 1.2)
        self._player_np: NodePath = self.render.attachNewNode(cm.generate())
        self._player_np.setColor(1.0, 0.9, 0.1, 1.0)

        tn = TextNode("player_lbl")
        tn.setText("PLAYER")
        tn.setAlign(TextNode.ACenter)
        lbl = self._player_np.attachNewNode(tn)
        lbl.setScale(0.3)
        lbl.setPos(0, 0, 1.35)
        lbl.setBillboardPointEye()

        self._player_np.setPos(self._stub_player.get_position())

    # ── camera ────────────────────────────────────────────────────────────────

    def _setup_camera(self) -> None:
        self.disableMouse()
        self.camera.setPos(0, -30, 24)
        self.camera.lookAt(Point3(0, 0, 0))

    # ── HUD ───────────────────────────────────────────────────────────────────

    def _setup_hud(self) -> None:
        self._hud_guard = OnscreenText(
            text="", pos=(-1.25, 0.92), scale=0.050,
            fg=(1, 1, 1, 1), shadow=(0, 0, 0, 0.65),
            align=TextNode.ALeft, mayChange=True,
        )
        self._hud_player = OnscreenText(
            text="", pos=(-1.25, 0.50), scale=0.050,
            fg=(1.0, 0.9, 0.1, 1), shadow=(0, 0, 0, 0.65),
            align=TextNode.ALeft, mayChange=True,
        )
        self._hud_conf = OnscreenText(
            text="", pos=(0.0, -0.80), scale=0.062,
            fg=(0.3, 1.0, 0.3, 1), shadow=(0, 0, 0, 0.8),
            align=TextNode.ACenter, mayChange=True,
        )
        OnscreenText(
            text=(
                "[WASD] Move   [Q/E] Size   [C] Crouch   "
                "[V] Camo   [L] Light   [Esc] Quit   —   Phase 2"
            ),
            pos=(0, -0.94), scale=0.042,
            fg=(0.65, 0.65, 0.65, 1), align=TextNode.ACenter,
        )

    def _refresh_hud(self) -> None:
        g   = self._guard
        pos = g.get_position()
        wp  = g.waypoints[g._current_wp_index].position
        act = f"waiting ({g._wait_timer:.1f}s)" if g._waiting else "moving"

        self._hud_guard.setText(
            f"Guard  : {g.name}\n"
            f"State  : {g.state}\n"
            f"Pos    : ({pos.x:+.1f}, {pos.y:+.1f})\n"
            f"Target : WP{g._current_wp_index}  ({wp.x:+.1f}, {wp.y:+.1f})\n"
            f"Action : {act}"
        )

        sp  = self._stub_player
        pp  = sp.get_position()
        lit = self._stub_env.is_position_lit(pp)
        self._hud_player.setText(
            f"Player pos   : ({pp.x:+.1f}, {pp.y:+.1f})\n"
            f"Size factor  : {sp.get_size_factor():.2f}\n"
            f"Crouching    : {sp.get_is_crouching()}\n"
            f"Camouflaged  : {not sp.is_visible()}\n"
            f"Lit          : {lit}"
        )

        c = g.confidence
        if c < CURIOUS_THRESHOLD:
            label, color = "UNDETECTED",  (0.3, 1.0, 0.3, 1.0)
        elif c < SUSPICIOUS_THRESHOLD:
            label, color = "CURIOUS",     (1.0, 0.85, 0.1, 1.0)
        else:
            label, color = "SUSPICIOUS",  (1.0, 0.25, 0.1, 1.0)

        filled  = int(c * 20)
        bar     = "█" * filled + "░" * (20 - filled)
        self._hud_conf.setText(f"Confidence: [{bar}] {c:.2f}   {label}")
        self._hud_conf["fg"] = color

    # ── per-frame ─────────────────────────────────────────────────────────────

    def _update_task(self, task):
        dt: float = globalClock.getDt()
        self._move_player(dt)
        self._refresh_hud()
        return task.cont

    def _move_player(self, dt: float) -> None:
        dx = dy = 0.0
        if self._keys["w"]: dy += 1.0
        if self._keys["s"]: dy -= 1.0
        if self._keys["a"]: dx -= 1.0
        if self._keys["d"]: dx += 1.0
        if dx or dy:
            self._stub_player.move(dx * PLAYER_MOVE_SPEED * dt,
                                   dy * PLAYER_MOVE_SPEED * dt)
            self._player_np.setPos(self._stub_player.get_position())

    # ── keybinds ──────────────────────────────────────────────────────────────

    def _setup_keybinds(self) -> None:
        self.accept("escape", sys.exit)

        for k in ("w", "s", "a", "d"):
            self.accept(k,        self._set_key, [k, True])
            self.accept(f"{k}-up",self._set_key, [k, False])

        for arrow, k in (
            ("arrow_up",    "w"), ("arrow_down",  "s"),
            ("arrow_left",  "a"), ("arrow_right", "d"),
        ):
            self.accept(arrow,          self._set_key, [k, True])
            self.accept(f"{arrow}-up",  self._set_key, [k, False])

        self.accept("q", self._change_size, [-SIZE_STEP])
        self.accept("e", self._change_size, [ SIZE_STEP])
        self.accept("c", self._stub_player.toggle_crouch)
        self.accept("v", self._stub_player.toggle_visible)
        self.accept("l", self._stub_env.toggle_lit)

    def _set_key(self, key: str, value: bool) -> None:
        self._keys[key] = value

    def _change_size(self, delta: float) -> None:
        self._stub_player.set_size_factor(
            self._stub_player.get_size_factor() + delta
        )


if __name__ == "__main__":
    GuardTestApp().run()