# src/guard/guard.py
"""
- Accepts `player` and `env` objects at construction time (duck-typed —
  any object satisfying the interface contract works, real or stub).
- Creates an FOVComponent and runs check() every frame via a dedicated task.
- Exposes self.confidence (float 0–1) for the HUD and future state machine.

Phase 1 patrol logic is completely unchanged.
"""

from __future__ import annotations
import math

from panda3d.core import (
    NodePath,
    Point3,
    Vec3,
    CardMaker,
    TextNode,
)
from direct.showbase.ShowBase import ShowBase

from src.guard.waypoint import Waypoint
from src.guard.fov_component import FOVComponent

# ── patrol constants (unchanged from Phase 1) ─────────────────────────────────
MOVE_SPEED:        float = 4.0
ARRIVE_THRESHOLD:  float = 0.3
TURN_SPEED:        float = 240.0
# ─────────────────────────────────────────────────────────────────────────────


class Guard:
    """One guard agent: waypoint patrol + vision-cone detection."""

    _next_id: int = 0

    def __init__(
        self,
        base:      ShowBase,
        waypoints: list[Waypoint],
        *,
        player,                         # satisfies player interface contract
        env,                            # satisfies env interface contract
        name:      str | None = None,
        fov_debug: bool       = False,
    ) -> None:
        """
        Parameters
        ----------
        base      : running ShowBase instance.
        waypoints : ordered patrol route — at least one entry required.
        player    : player object (real Player or any stub with same methods).
        env       : environment object (real LevelManager or any stub).
        name      : optional display label; auto-assigned if omitted.
        fov_debug : render collision rays visibly for debugging.
        """
        if not waypoints:
            raise ValueError("Guard requires at least one Waypoint.")

        self._base     = base
        self._player   = player
        self._env      = env
        self.waypoints: list[Waypoint] = waypoints
        self.state:     str            = "IDLE"
        self.confidence: float         = 0.0

        self._id:  int = Guard._next_id
        Guard._next_id += 1
        self.name: str = name or f"Guard_{self._id}"

        # ── placeholder geometry (card + billboard label) ─────────────────
        cm = CardMaker(self.name + "_card")
        cm.setFrame(-0.4, 0.4, 0.0, 1.4)
        card_np: NodePath = NodePath(cm.generate())
        card_np.setColor(0.2, 0.8, 0.3, 1.0)

        self.node_path: NodePath = base.render.attachNewNode(self.name)
        card_np.reparentTo(self.node_path)

        tn = TextNode(self.name + "_label")
        tn.setText(self.name)
        tn.setAlign(TextNode.ACenter)
        label_np = self.node_path.attachNewNode(tn)
        label_np.setScale(0.35)
        label_np.setPos(0.0, 0.0, 1.55)
        label_np.setBillboardPointEye()

        self.node_path.setPos(waypoints[0].position)

        # ── patrol state ──────────────────────────────────────────────────
        self._current_wp_index: int   = 0
        self._waiting:          bool  = False
        self._wait_timer:       float = 0.0
        self._task_patrol: str = f"guard_patrol_{self._id}"
        self._task_fov:    str = f"guard_fov_{self._id}"

        # ── FOV component ─────────────────────────────────────────────────
        self._fov = FOVComponent(
            base=base,
            guard_np=self.node_path,
            debug_visible=fov_debug,
        )

    # ── public control ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Register patrol and FOV tasks with taskMgr."""
        self._base.taskMgr.add(self._patrol_task, self._task_patrol)
        self._base.taskMgr.add(self._fov_task,    self._task_fov)

    def stop(self) -> None:
        """Pause both tasks (position preserved)."""
        self._base.taskMgr.remove(self._task_patrol)
        self._base.taskMgr.remove(self._task_fov)

    def destroy(self) -> None:
        """Remove guard from scene and cancel all tasks."""
        self.stop()
        self._fov.destroy()
        self.node_path.removeNode()

    # ── FOV task ──────────────────────────────────────────────────────────────

    def _fov_task(self, task):
        self.confidence = self._fov.check(self._player, self._env)
        return task.cont

    # ── patrol task (unchanged from Phase 1) ──────────────────────────────────

    def _patrol_task(self, task):
        dt: float = globalClock.getDt()

        if self._waiting:
            self._wait_timer -= dt
            if self._wait_timer <= 0.0:
                self._waiting = False
                self._advance_waypoint()
            return task.cont

        target:      Point3 = self.waypoints[self._current_wp_index].position
        current_pos: Point3 = self.node_path.getPos()
        to_target:   Vec3   = target - current_pos
        distance:    float  = to_target.length()

        if distance <= ARRIVE_THRESHOLD:
            self.node_path.setPos(target)
            wait: float = self.waypoints[self._current_wp_index].wait_time
            if wait > 0.0:
                self._waiting    = True
                self._wait_timer = wait
            else:
                self._advance_waypoint()
            return task.cont

        direction: Vec3  = to_target.normalized()
        step:      float = min(MOVE_SPEED * dt, distance)
        self.node_path.setPos(current_pos + direction * step)

        target_heading:  float = math.degrees(math.atan2(-direction.x, direction.y))
        current_heading: float = self.node_path.getH()
        delta:           float = (target_heading - current_heading + 180.0) % 360.0 - 180.0
        max_turn:        float = TURN_SPEED * dt
        self.node_path.setH(current_heading + max(-max_turn, min(max_turn, delta)))

        return task.cont

    def _advance_waypoint(self) -> None:
        self._current_wp_index = (self._current_wp_index + 1) % len(self.waypoints)

    # ── helpers ───────────────────────────────────────────────────────────────

    def get_position(self) -> Point3:
        return self.node_path.getPos()

    def __repr__(self) -> str:
        pos = self.get_position()
        return (
            f"<Guard '{self.name}' state={self.state} "
            f"conf={self.confidence:.2f} "
            f"pos=({pos.x:.1f},{pos.y:.1f},{pos.z:.1f})>"
        )