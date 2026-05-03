# src/guard/guard.py
"""
Guard — Phase 1
---------------
A single guard agent.  Loads a visible node into the scene, then walks
a closed loop of Waypoints using Panda3D's taskMgr.

State machine (Phase 1 stub):
    Only IDLE is implemented.  The full enum arrives in Phase 3.

Public attributes (read by GuardManager and integration layer):
    state        str          -- current state label, e.g. "IDLE"
    node_path    NodePath     -- the guard's scene node (position / heading)
    waypoints    list[Waypoint]

Public methods:
    start()   -- register the patrol task with taskMgr
    stop()    -- remove the patrol task
    destroy() -- remove node from scene graph
"""

from __future__ import annotations
from typing import TYPE_CHECKING

from panda3d.core import (
    NodePath,
    Point3,
    Vec3,
    CardMaker,
    TextNode,
)
from direct.showbase.ShowBase import ShowBase

from src.guard.waypoint import Waypoint

if TYPE_CHECKING:
    # Only imported for type hints — avoids circular imports at runtime.
    pass

# ── tuneable constants ────────────────────────────────────────────────────────
MOVE_SPEED: float = 4.0          # units per second while patrolling
ARRIVE_THRESHOLD: float = 0.3   # distance (units) considered "arrived"
TURN_SPEED: float = 240.0        # degrees per second for heading rotation
# ─────────────────────────────────────────────────────────────────────────────


class Guard:
    """One guard agent.  Instantiate, then call start()."""

    # Auto-incrementing id so multiple guards can share one scene without
    # task-name collisions.
    _next_id: int = 0

    def __init__(
        self,
        base: ShowBase,
        waypoints: list[Waypoint],
        *,
        name: str | None = None,
    ) -> None:
        """
        Parameters
        ----------
        base       : the running ShowBase instance (gives us render / taskMgr).
        waypoints  : ordered patrol route; must contain at least 1 Waypoint.
        name       : optional human label, e.g. "GuardA".  Auto-assigned if
                     omitted.
        """
        if not waypoints:
            raise ValueError("Guard requires at least one Waypoint.")

        self._base = base
        self.waypoints: list[Waypoint] = waypoints
        self.state: str = "IDLE"

        # ── assign unique id / name ───────────────────────────────────────
        self._id: int = Guard._next_id
        Guard._next_id += 1
        self.name: str = name or f"Guard_{self._id}"

        # ── build a simple visible stand-in geometry ─────────────────────
        #   A flat card (CardMaker) so we can see the guard in the test scene
        #   without needing any art assets.  Phase 4 will swap this for a
        #   real model once Teammate B's assets are available.
        cm = CardMaker(self.name + "_card")
        cm.set_frame(-0.4, 0.4, 0.0, 1.4)      # width 0.8, height 1.4
        card_np: NodePath = NodePath(cm.generate())
        card_np.set_color(0.2, 0.8, 0.3, 1.0)  # bright green placeholder

        # Wrap in a parent NodePath so we can move/rotate the whole guard.
        self.node_path: NodePath = base.render.attach_new_node(self.name)
        card_np.reparent_to(self.node_path)

        # ── label rendered above the card so we know which guard is which ─
        tn = TextNode(self.name + "_label")
        tn.set_text(self.name)
        tn.set_align(TextNode.ACenter)
        label_np: NodePath = self.node_path.attach_new_node(tn)
        label_np.set_scale(0.35)
        label_np.set_pos(0.0, 0.0, 1.55)
        label_np.set_billboard_point_eye()   # always faces the camera

        # ── place guard at first waypoint ─────────────────────────────────
        start_pos: Point3 = waypoints[0].position
        self.node_path.set_pos(start_pos)

        # ── patrol state ──────────────────────────────────────────────────
        self._current_wp_index: int = 0
        self._waiting: bool = False
        self._wait_timer: float = 0.0
        self._task_name: str = f"guard_patrol_{self._id}"

    # ── public control ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Register the patrol task.  Call once after creating the guard."""
        self._base.taskMgr.add(self._patrol_task, self._task_name)

    def stop(self) -> None:
        """Pause patrol (task removed, position preserved)."""
        self._base.taskMgr.remove(self._task_name)

    def destroy(self) -> None:
        """Remove the guard from the scene and cancel its task."""
        self.stop()
        self.node_path.remove_node()

    # ── internal task ─────────────────────────────────────────────────────────

    def _patrol_task(self, task):
        """
        Called every frame by taskMgr.
        Moves the guard toward the current waypoint; when close enough,
        either waits (if wait_time > 0) or advances to the next waypoint.
        Route is a closed loop: after the last waypoint, wraps to index 0.
        """
        dt: float = globalClock.get_dt()

        if self._waiting:
            self._wait_timer -= dt
            if self._wait_timer <= 0.0:
                self._waiting = False
                self._advance_waypoint()
            return task.cont

        target: Point3 = self.waypoints[self._current_wp_index].position
        current_pos: Point3 = self.node_path.get_pos()

        # ── vector toward target ──────────────────────────────────────────
        to_target: Vec3 = target - current_pos
        distance: float = to_target.length()

        if distance <= ARRIVE_THRESHOLD:
            # Snap to exact position to avoid floating drift.
            self.node_path.set_pos(target)
            wait: float = self.waypoints[self._current_wp_index].wait_time
            if wait > 0.0:
                self._waiting = True
                self._wait_timer = wait
            else:
                self._advance_waypoint()
            return task.cont

        # ── move toward target ────────────────────────────────────────────
        direction: Vec3 = to_target.normalized()
        step: float = min(MOVE_SPEED * dt, distance)
        new_pos: Point3 = current_pos + direction * step
        self.node_path.set_pos(new_pos)

        # ── rotate to face direction of travel ────────────────────────────
        #   heading in Panda3D: 0° = +Y axis, positive = counter-clockwise
        #   atan2 gives us the angle from +Y in the XY plane.
        import math
        target_heading: float = math.degrees(math.atan2(-direction.x, direction.y))
        current_heading: float = self.node_path.get_h()

        # Shortest-path angular delta.
        delta: float = (target_heading - current_heading + 180.0) % 360.0 - 180.0
        max_turn: float = TURN_SPEED * dt
        applied: float = max(-max_turn, min(max_turn, delta))
        self.node_path.set_h(current_heading + applied)

        return task.cont

    def _advance_waypoint(self) -> None:
        """Move index to next waypoint, wrapping around to 0 at the end."""
        self._current_wp_index = (self._current_wp_index + 1) % len(self.waypoints)

    # ── helpers ───────────────────────────────────────────────────────────────

    def get_position(self) -> Point3:
        """Convenience accessor for the guard's current world position."""
        return self.node_path.get_pos()

    def __repr__(self) -> str:
        pos = self.get_position()
        return (
            f"<Guard '{self.name}' state={self.state} "
            f"pos=({pos.x:.1f},{pos.y:.1f},{pos.z:.1f}) "
            f"wp={self._current_wp_index}/{len(self.waypoints)}>"
        )