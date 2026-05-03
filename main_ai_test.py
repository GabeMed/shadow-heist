# main_ai_test.py
"""
Phase 3 smoke test — Alert State Machine & Sound Events
--------------------------------------------------------
Standalone: no ShadowHeist, Player, or LevelManager imported.

Scene
-----
  • Dark ground plane + two invisible cross-shaped wall occluders.
  • Three red waypoint pillars.
  • Two guards (GuardA and GuardB) sharing the same route,
    offset so they are not on top of each other.
  • One mock player (yellow card) — move with WASD.
  • One body node (white card) — press [B] to drop/remove it.

Guard card colours reflect alert state:
  Green   = IDLE
  Yellow  = CURIOUS
  Orange  = SUSPICIOUS
  Red     = HUNTING
  Magenta = GENERAL_ALARM

Controls
--------
  W / A / S / D   Move mock player
  Q / E           Decrease / increase player size factor
  C               Toggle crouching
  V               Toggle camouflage
  L               Toggle global lighting
  F               Fire a sound event at the player's current position
  B               Toggle a body node on/off at position (3, 3, 0)
  Escape          Quit

Run
---
  python main_ai_test.py
"""

from __future__ import annotations
import sys
import os

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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from entities.guard.waypoint import Waypoint
from entities.guard.guard import Guard
from entities.guard.guard_manager import GuardManager
from entities.guard.alert_state import AlertState
from entities.guard.fov_component import (
    WALL_BITMASK,
    CURIOUS_THRESHOLD,
    SUSPICIOUS_THRESHOLD,
)

# ── scene config ──────────────────────────────────────────────────────────────
TEST_WAYPOINTS = [
    ( 0.0,  8.0, 0.0, 2.5),
    ( 8.0, -4.0, 0.0, 1.0),
    (-8.0, -4.0, 0.0, 1.5),
]
PLAYER_MOVE_SPEED: float = 6.0
SIZE_STEP:         float = 0.25

ALERT_LEVEL_LABELS = {0: "CALM", 1: "ELEVATED", 2: "HIGH", 3: "⚠ GENERAL ALARM"}
ALERT_LEVEL_COLORS = {
    0: (0.3, 1.0, 0.3, 1.0),
    1: (1.0, 0.85, 0.1, 1.0),
    2: (1.0, 0.45, 0.0, 1.0),
    3: (1.0, 0.1,  0.9, 1.0),
}
STATE_COLORS = {
    AlertState.IDLE:          (0.6,  1.0, 0.6,  1.0),
    AlertState.CURIOUS:       (1.0,  0.9, 0.3,  1.0),
    AlertState.SUSPICIOUS:    (1.0,  0.55, 0.1, 1.0),
    AlertState.HUNTING:       (1.0,  0.25, 0.25, 1.0),
    AlertState.GENERAL_ALARM: (1.0,  0.3,  1.0, 1.0),
}


# ── inline stubs ──────────────────────────────────────────────────────────────

class _StubPlayer:
    def __init__(self, position: Point3) -> None:
        self._pos:         Point3 = Point3(position)
        self._size_factor: float  = 1.0
        self._crouching:   bool   = False
        self._visible:     bool   = True

    def get_position(self)     -> Point3:   return Point3(self._pos)
    def get_size_factor(self)  -> float:    return self._size_factor
    def get_is_sprinting(self) -> bool:     return False
    def get_is_crouching(self) -> bool:     return self._crouching
    def get_node_path(self)    -> NodePath: return NodePath("stub_player")
    def is_visible(self)       -> bool:     return self._visible

    def move(self, dx: float, dy: float) -> None:
        self._pos = Point3(self._pos.x + dx, self._pos.y + dy, self._pos.z)

    def set_size_factor(self, v: float) -> None:
        self._size_factor = max(1.0, min(3.0, v))

    def toggle_crouch(self)  -> None: self._crouching = not self._crouching
    def toggle_visible(self) -> None: self._visible   = not self._visible


class _StubEnv:
    def __init__(self) -> None:
        self._lit: bool = True

    def is_position_lit(self, pos: Point3) -> bool: return self._lit
    def get_active_light_nodes(self)        -> list: return []
    def get_nav_mesh(self)        -> NodePath:       return NodePath("stub_nav")
    def toggle_lit(self)          -> None:           self._lit = not self._lit


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

        self._manager = GuardManager(self)

        self._spawn_guards()
        self._spawn_player_marker()
        self._body_np: NodePath | None = None

        self._manager.start()

        self._setup_camera()
        self._setup_hud()
        self._setup_keybinds()

        self._keys: dict[str, bool] = {k: False for k in ("w", "s", "a", "d")}
        self.taskMgr.add(self._update_task, "frame_update")

    # ── window ────────────────────────────────────────────────────────────────

    def _configure_window(self) -> None:
        props = WindowProperties()
        props.setTitle("SHADOW-HEIST — Guard AI Test [Phase 3]")
        props.setSize(1280, 720)
        self.win.requestProperties(props)
        self.setBackgroundColor(0.06, 0.06, 0.10)

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
        for normal, label in (
            (Vec3(1, 0, 0), "wall_vertical"),
            (Vec3(0, 1, 0), "wall_horizontal"),
        ):
            cn = CollisionNode(label)
            cn.addSolid(CollisionPlane(Plane(normal, Point3(0, 0, 0))))
            cn.setFromCollideMask(BitMask32.allOff())
            cn.setIntoCollideMask(WALL_BITMASK)
            self.render.attachNewNode(cn)

    # ── guards ────────────────────────────────────────────────────────────────

    def _spawn_guards(self) -> None:
        base_waypoints = [
            Waypoint(position=Point3(x, y, z), wait_time=w)
            for (x, y, z, w) in TEST_WAYPOINTS
        ]
        offset_waypoints = base_waypoints[1:] + base_waypoints[:1]

        self._guard_a = Guard(
            base=self, waypoints=base_waypoints,
            player=self._stub_player, env=self._stub_env,
            name="GuardA",
        )
        self._guard_b = Guard(
            base=self, waypoints=offset_waypoints,
            player=self._stub_player, env=self._stub_env,
            name="GuardB",
        )

        self._manager.add_guard(self._guard_a)
        self._manager.add_guard(self._guard_b)

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

    # ── body node ─────────────────────────────────────────────────────────────

    def _toggle_body(self) -> None:
        if self._body_np is not None:
            self._body_np.removeNode()
            self._body_np = None
            print("[Test] Body removed.")
            return

        body_pos = Point3(3.0, 3.0, 0.0)
        cm = CardMaker("body_card")
        cm.setFrame(-0.5, 0.5, 0.0, 0.25)
        self._body_np = self.render.attachNewNode(cm.generate())
        self._body_np.setColor(0.9, 0.9, 0.9, 1.0)
        self._body_np.setPos(body_pos)
        self._body_np.setP(-90)
        self._body_np.setTag("guard_body", "1")
        print(f"[Test] Body placed at {body_pos}.")

    # ── camera ────────────────────────────────────────────────────────────────

    def _setup_camera(self) -> None:
        self.disableMouse()
        self.camera.setPos(0, -32, 26)
        self.camera.lookAt(Point3(0, 0, 0))

    # ── HUD ───────────────────────────────────────────────────────────────────

    def _setup_hud(self) -> None:
        self._hud_guard_a = OnscreenText(
            text="", pos=(-1.25, 0.94), scale=0.047,
            fg=(0.6, 1.0, 0.6, 1), shadow=(0, 0, 0, 0.7),
            align=TextNode.ALeft, mayChange=True,
        )
        self._hud_guard_b = OnscreenText(
            text="", pos=(-1.25, 0.60), scale=0.047,
            fg=(0.6, 1.0, 0.6, 1), shadow=(0, 0, 0, 0.7),
            align=TextNode.ALeft, mayChange=True,
        )
        self._hud_player = OnscreenText(
            text="", pos=(-1.25, 0.26), scale=0.047,
            fg=(1.0, 0.9, 0.1, 1), shadow=(0, 0, 0, 0.7),
            align=TextNode.ALeft, mayChange=True,
        )
        self._hud_alert = OnscreenText(
            text="", pos=(0.0, -0.82), scale=0.068,
            fg=(0.3, 1.0, 0.3, 1), shadow=(0, 0, 0, 0.85),
            align=TextNode.ACenter, mayChange=True,
        )
        OnscreenText(
            text=(
                "[WASD] Move   [Q/E] Size   [C] Crouch   [V] Camo   "
                "[L] Light   [F] Sound event   [B] Body   [Esc] Quit"
            ),
            pos=(0, -0.95), scale=0.038,
            fg=(0.6, 0.6, 0.6, 1), align=TextNode.ACenter,
        )

    def _guard_hud_text(self, guard: Guard) -> str:
        pos      = guard.get_position()
        meter    = guard.alert_meter
        bar      = "█" * int(meter / 5) + "░" * (20 - int(meter / 5))
        conf_bar = "█" * int(guard.confidence * 10) + "░" * (10 - int(guard.confidence * 10))
        return (
            f"{guard.name}  [{guard.alert_state}]\n"
            f"Pos    : ({pos.x:+.1f}, {pos.y:+.1f})\n"
            f"Conf   : [{conf_bar}] {guard.confidence:.2f}\n"
            f"Meter  : [{bar}] {meter:.0f}/100"
        )

    def _refresh_hud(self) -> None:
        state_a = self._guard_a.alert_state
        self._hud_guard_a.setText(self._guard_hud_text(self._guard_a))
        self._hud_guard_a["fg"] = STATE_COLORS.get(state_a, (1, 1, 1, 1))

        state_b = self._guard_b.alert_state
        self._hud_guard_b.setText(self._guard_hud_text(self._guard_b))
        self._hud_guard_b["fg"] = STATE_COLORS.get(state_b, (1, 1, 1, 1))

        sp  = self._stub_player
        pp  = sp.get_position()
        lit = self._stub_env.is_position_lit(pp)
        body_active = self._body_np is not None and not self._body_np.isEmpty()
        self._hud_player.setText(
            f"Player pos   : ({pp.x:+.1f}, {pp.y:+.1f})\n"
            f"Size factor  : {sp.get_size_factor():.2f}\n"
            f"Crouching    : {sp.get_is_crouching()}\n"
            f"Camouflaged  : {not sp.is_visible()}\n"
            f"Lit          : {lit}   |   Body in scene: {body_active}"
        )

        level = self._manager.get_alert_level()
        self._hud_alert.setText(
            f"ALERT LEVEL {level}  —  {ALERT_LEVEL_LABELS[level]}"
        )
        self._hud_alert["fg"] = ALERT_LEVEL_COLORS[level]

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

    def _fire_sound_event(self) -> None:
        pos = self._stub_player.get_position()
        self._manager.register_sound_event(pos=pos, radius=10.0, intensity=1.0)
        print(f"[Test] Sound event at ({pos.x:.1f}, {pos.y:.1f})")

    # ── keybinds ──────────────────────────────────────────────────────────────

    def _setup_keybinds(self) -> None:
        self.accept("escape", sys.exit)

        for k in ("w", "s", "a", "d"):
            self.accept(k,         self._set_key, [k, True])
            self.accept(f"{k}-up", self._set_key, [k, False])

        for arrow, k in (
            ("arrow_up",    "w"), ("arrow_down",  "s"),
            ("arrow_left",  "a"), ("arrow_right", "d"),
        ):
            self.accept(arrow,         self._set_key, [k, True])
            self.accept(f"{arrow}-up", self._set_key, [k, False])

        self.accept("q", self._change_size,              [-SIZE_STEP])
        self.accept("e", self._change_size,              [ SIZE_STEP])
        self.accept("c", self._stub_player.toggle_crouch)
        self.accept("v", self._stub_player.toggle_visible)
        self.accept("l", self._stub_env.toggle_lit)
        self.accept("f", self._fire_sound_event)
        self.accept("b", self._toggle_body)

    def _set_key(self, key: str, value: bool) -> None:
        self._keys[key] = value

    def _change_size(self, delta: float) -> None:
        self._stub_player.set_size_factor(
            self._stub_player.get_size_factor() + delta
        )


if __name__ == "__main__":
    GuardTestApp().run()