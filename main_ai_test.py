# main_ai_test.py
"""
Phase 1 smoke test — Guard Patrol
----------------------------------
Launches a minimal Panda3D scene with:
  • A flat ground plane (grey card).
  • Three waypoints marked with small red pillars.
  • One Guard walking the 3-waypoint route in a loop.

No teammate files are imported.  Everything is self-contained so any
team member can run this immediately after 'pip install panda3d'.

Controls:
  Arrow keys / WASD  -- orbit the camera (Panda3D default trackball is off;
                        we use a simple mouse-look orbit instead).
  Mouse wheel        -- zoom in / out.
  Escape             -- quit.

Run:
  cd glutton_heist
  python main_ai_test.py
"""

from __future__ import annotations
import sys
import math

from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    Point3,
    Vec3,
    AmbientLight,
    DirectionalLight,
    CardMaker,
    TextNode,
    WindowProperties,
    ClockObject,
    NodePath,
)

# Ensure the project root is on sys.path so 'src.*' imports resolve.
import os
sys.path.insert(0, os.path.dirname(__file__))

from src.guard.waypoint import Waypoint
from src.guard.guard import Guard


# ── waypoint positions for the test scene ────────────────────────────────────
TEST_WAYPOINTS: list[tuple[float, float, float, float]] = [
    # (x,    y,    z,   wait_seconds)
    ( 0.0,  8.0,  0.0,  2.5),
    ( 8.0, -4.0,  0.0,  1.0),
    (-8.0, -4.0,  0.0,  1.5),
]


class GuardTestApp(ShowBase):
    """Minimal ShowBase app for Phase 1 guard patrol testing."""

    def __init__(self) -> None:
        super().__init__()

        self._configure_window()
        self._setup_lighting()
        self._build_ground()
        self._build_waypoint_markers()
        self._spawn_guard()
        self._setup_camera()
        self._setup_hud()
        self._setup_keybinds()

        # Update HUD every frame.
        self.taskMgr.add(self._update_hud_task, "update_hud")

    # ── window ────────────────────────────────────────────────────────────────

    def _configure_window(self) -> None:
        props = WindowProperties()
        props.set_title("Glutton Heist — Guard AI Test [Phase 1]")
        props.set_size(1280, 720)
        self.win.request_properties(props)
        self.set_background_color(0.08, 0.08, 0.12)   # dark navy — night feel

    # ── lighting ──────────────────────────────────────────────────────────────

    def _setup_lighting(self) -> None:
        # Soft ambient so the ground and cards are visible.
        ambient = AmbientLight("ambient")
        ambient.set_color((0.35, 0.35, 0.40, 1.0))
        self.render.set_light(self.render.attach_new_node(ambient))

        # Single directional light from above-right.
        sun = DirectionalLight("sun")
        sun.set_color((0.85, 0.85, 0.75, 1.0))
        sun_np: NodePath = self.render.attach_new_node(sun)
        sun_np.set_hpr(45, -60, 0)
        self.render.set_light(sun_np)

    # ── ground plane ──────────────────────────────────────────────────────────

    def _build_ground(self) -> None:
        cm = CardMaker("ground")
        size = 30.0
        cm.set_frame(-size, size, -size, size)
        ground: NodePath = self.render.attach_new_node(cm.generate())
        ground.set_color(0.22, 0.22, 0.22, 1.0)   # dark grey
        ground.set_p(-90)                           # rotate flat (XY plane)
        ground.set_pos(0, 0, -0.01)                 # just below origin

    # ── waypoint markers ──────────────────────────────────────────────────────

    def _build_waypoint_markers(self) -> None:
        """
        Place a small red pillar and a label at each waypoint position so
        the patrol route is visible in the scene.
        """
        for i, (x, y, z, _wait) in enumerate(TEST_WAYPOINTS):
            # Pillar (tall thin card, red).
            cm = CardMaker(f"wp_marker_{i}")
            cm.set_frame(-0.15, 0.15, 0.0, 0.9)
            pillar: NodePath = self.render.attach_new_node(cm.generate())
            pillar.set_color(0.9, 0.2, 0.2, 1.0)
            pillar.set_pos(x, y, z)
            pillar.set_billboard_point_eye()

            # Label.
            tn = TextNode(f"wp_label_{i}")
            tn.set_text(f"WP {i}")
            tn.set_align(TextNode.ACenter)
            label: NodePath = self.render.attach_new_node(tn)
            label.set_scale(0.28)
            label.set_pos(x, y, z + 1.0)
            label.set_billboard_point_eye()

    # ── guard spawn ───────────────────────────────────────────────────────────

    def _spawn_guard(self) -> None:
        waypoints: list[Waypoint] = [
            Waypoint(position=Point3(x, y, z), wait_time=wait)
            for (x, y, z, wait) in TEST_WAYPOINTS
        ]
        self._guard = Guard(base=self, waypoints=waypoints, name="GuardA")
        self._guard.start()

    # ── camera ────────────────────────────────────────────────────────────────

    def _setup_camera(self) -> None:
        """
        Fixed overhead-ish camera looking at the scene centre.
        Disable the default mouse control so the view stays stable.
        """
        self.disable_mouse()
        self.camera.set_pos(0, -28, 22)
        self.camera.look_at(Point3(0, 0, 0))

    # ── HUD ───────────────────────────────────────────────────────────────────

    def _setup_hud(self) -> None:
        self._hud_text = OnscreenText(
            text="",
            pos=(-1.25, 0.92),
            scale=0.055,
            fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 0.6),
            align=TextNode.ALeft,
            mayChange=True,
        )
        # Static legend at bottom.
        OnscreenText(
            text="[Escape] Quit    Phase 1 — Waypoint Patrol Smoke Test",
            pos=(0, -0.95),
            scale=0.045,
            fg=(0.7, 0.7, 0.7, 1),
            align=TextNode.ACenter,
        )

    def _update_hud_task(self, task):
        g = self._guard
        pos = g.get_position()
        wp_pos = g.waypoints[g._current_wp_index].position
        waiting_str = f"waiting ({g._wait_timer:.1f}s)" if g._waiting else "moving"

        self._hud_text.setText(
            f"Guard : {g.name}\n"
            f"State : {g.state}\n"
            f"Pos   : ({pos.x:+.1f}, {pos.y:+.1f}, {pos.z:+.1f})\n"
            f"Target: WP{g._current_wp_index} "
            f"({wp_pos.x:+.1f}, {wp_pos.y:+.1f})\n"
            f"Action: {waiting_str}\n"
            f"FPS   : {round(globalClock.get_average_frame_rate())}"
        )
        return task.cont

    # ── keybinds ──────────────────────────────────────────────────────────────

    def _setup_keybinds(self) -> None:
        self.accept("escape", sys.exit)


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = GuardTestApp()
    app.run()