# src/guard/guard.py
"""
Guard — Phase 3
---------------
Full alert state machine layered on top of Phase 2 patrol + FOV.

State machine summary
---------------------
IDLE
  • Patrols waypoints.
  • FOV confidence > 0 and < SUSPICIOUS_THRESHOLD  →  CURIOUS
  • FOV confidence >= SUSPICIOUS_THRESHOLD          →  SUSPICIOUS
  • Sound event received (via on_sound_event())     →  CURIOUS
  • Body spotted (tagged node in FOV range)         →  SUSPICIOUS

CURIOUS
  • Walks to last-known stimulus position.
  • If player re-enters FOV above suspicious threshold →  SUSPICIOUS
  • If investigate timer expires                       →  IDLE
  • Investigate timer resets on any new stimulus.

SUSPICIOUS
  • Chases player's last known position.
  • Alert meter fills at ALERT_FILL_RATE per second.
  • Alert meter drains at ALERT_DRAIN_RATE per second when player lost.
  • Meter reaches 100                →  HUNTING
  • Player lost + meter drains to 0  →  CURIOUS

HUNTING
  • Fast chase toward last known player position.
  • Emits on_hunting callback (GuardManager listens to count hunters).
  • GuardManager promotes to GENERAL_ALARM if 3+ guards hunt simultaneously.

GENERAL_ALARM
  • Guard converges on last known player position at full speed.
  • GuardManager.get_alert_level() returns 3.
  • No automatic exit — game logic must reset.

Public signals (callable hooks for GuardManager)
-------------------------------------------------
  on_state_change(guard, old_state, new_state)
  on_hunting(guard)
"""

from __future__ import annotations
import math
from typing import Callable

from panda3d.core import (
    NodePath,
    Point3,
    Vec3,
    CardMaker,
    TextNode,
)
from direct.showbase.ShowBase import ShowBase

from src.guard.waypoint import Waypoint
from src.guard.fov_component import FOVComponent, CURIOUS_THRESHOLD, SUSPICIOUS_THRESHOLD
from src.guard.alert_state import AlertState

# ── patrol constants (unchanged) ──────────────────────────────────────────────
MOVE_SPEED:       float = 4.0
HUNT_SPEED:       float = 7.5    # units/sec while HUNTING or GENERAL_ALARM
ARRIVE_THRESHOLD: float = 0.3
TURN_SPEED:       float = 240.0

# ── state machine timers & rates ──────────────────────────────────────────────
INVESTIGATE_TIME:  float = 5.0    # seconds CURIOUS guard walks to stimulus pos
                                   # before giving up and returning to IDLE
ALERT_FILL_RATE:   float = 35.0   # alert meter units/sec while seeing player
ALERT_DRAIN_RATE:  float = 15.0   # alert meter units/sec when player lost
ALERT_MAX:         float = 100.0  # meter value that triggers HUNTING

# ── body detection ────────────────────────────────────────────────────────────
BODY_DETECT_RANGE: float = 6.0    # units — guard must be this close to notice body
BODY_TAG:          str   = "guard_body"   # NodePath tag key used by GuardManager
# ─────────────────────────────────────────────────────────────────────────────


class Guard:
    """One guard agent: waypoint patrol + vision cone + full alert FSM."""

    _next_id: int = 0

    def __init__(
        self,
        base:      ShowBase,
        waypoints: list[Waypoint],
        *,
        player,
        env,
        name:      str | None = None,
        fov_debug: bool = False,
        on_state_change: Callable[["Guard", AlertState, AlertState], None] | None = None,
        on_hunting:      Callable[["Guard"], None] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        base             : running ShowBase instance.
        waypoints        : ordered patrol route — at least one entry required.
        player           : satisfies player interface contract.
        env              : satisfies env interface contract.
        name             : optional display label.
        fov_debug        : render collision rays visibly.
        on_state_change  : called whenever alert state changes.
                           Signature: (guard, old_state, new_state) -> None
        on_hunting       : called each time this guard enters HUNTING.
                           Signature: (guard,) -> None
        """
        if not waypoints:
            raise ValueError("Guard requires at least one Waypoint.")

        self._base   = base
        self._player = player
        self._env    = env

        self.waypoints: list[Waypoint] = waypoints
        self.alert_state: AlertState   = AlertState.IDLE
        self.confidence:  float        = 0.0

        # Callbacks wired by GuardManager.
        self._on_state_change = on_state_change
        self._on_hunting      = on_hunting

        self._id:  int = Guard._next_id
        Guard._next_id += 1
        self.name: str = name or f"Guard_{self._id}"

        # ── FSM internal data ─────────────────────────────────────────────
        self._alert_meter:        float        = 0.0
        self._investigate_timer:  float        = 0.0
        self._last_known_pos:     Point3 | None = None
        self._investigating_pos:  Point3 | None = None

        # ── placeholder geometry ──────────────────────────────────────────
        cm = CardMaker(self.name + "_card")
        cm.setFrame(-0.4, 0.4, 0.0, 1.4)
        card_np: NodePath = NodePath(cm.generate())
        card_np.setColor(0.2, 0.8, 0.3, 1.0)
        self._card_np = card_np   # kept for colour updates

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

        self._task_patrol = f"guard_patrol_{self._id}"
        self._task_fov    = f"guard_fov_{self._id}"
        self._task_fsm    = f"guard_fsm_{self._id}"

        # ── FOV component ─────────────────────────────────────────────────
        self._fov = FOVComponent(
            base=base,
            guard_np=self.node_path,
            debug_visible=fov_debug,
        )

    # ── public control ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Register all tasks with taskMgr."""
        self._base.taskMgr.add(self._patrol_task, self._task_patrol)
        self._base.taskMgr.add(self._fov_task,    self._task_fov)
        self._base.taskMgr.add(self._fsm_task,    self._task_fsm)

    def stop(self) -> None:
        """Pause all tasks (position and state preserved)."""
        self._base.taskMgr.remove(self._task_patrol)
        self._base.taskMgr.remove(self._task_fov)
        self._base.taskMgr.remove(self._task_fsm)

    def destroy(self) -> None:
        """Remove guard from scene and cancel all tasks."""
        self.stop()
        self._fov.destroy()
        self.node_path.removeNode()

    def on_sound_event(self, sound_pos: Point3, intensity: float) -> None:
        """
        Called by GuardManager when a sound event reaches this guard.
        Transitions IDLE → CURIOUS (or refreshes timer if already CURIOUS).
        Guards in SUSPICIOUS or above ignore sound — they already know.

        Parameters
        ----------
        sound_pos : world position of the sound source.
        intensity : 0.0–1.0 hint (reserved for future loudness scaling).
        """
        if self.alert_state in (AlertState.IDLE, AlertState.CURIOUS):
            self._investigating_pos  = Point3(sound_pos)
            self._investigate_timer  = INVESTIGATE_TIME
            self._transition(AlertState.CURIOUS)

    def on_body_spotted(self) -> None:
        """
        Called by GuardManager when this guard is close to a body node.
        Always escalates to at least SUSPICIOUS.
        """
        if self.alert_state in (AlertState.IDLE, AlertState.CURIOUS):
            self._transition(AlertState.SUSPICIOUS)

    # ── tasks ─────────────────────────────────────────────────────────────────

    def _fov_task(self, task):
        self.confidence = self._fov.check(self._player, self._env)
        return task.cont

    def _fsm_task(self, task):
        dt: float = globalClock.getDt()
        self._update_fsm(dt)
        self._update_card_color()
        return task.cont

    def _patrol_task(self, task):
        """
        Movement logic — destination depends on current alert state:
          IDLE              → next patrol waypoint
          CURIOUS           → investigating position
          SUSPICIOUS/above  → last known player position
        """
        dt: float = globalClock.getDt()

        # Determine move speed.
        speed = (
            HUNT_SPEED if self.alert_state in
            (AlertState.HUNTING, AlertState.GENERAL_ALARM)
            else MOVE_SPEED
        )

        # Determine destination.
        if self.alert_state == AlertState.IDLE:
            destination = self._get_patrol_destination(dt)
            if destination is None:
                return task.cont     # waiting at waypoint — handled inside
        elif self.alert_state == AlertState.CURIOUS:
            destination = self._investigating_pos or self._get_patrol_destination(dt)
            if destination is None:
                return task.cont
        else:
            # SUSPICIOUS / HUNTING / GENERAL_ALARM — chase last known pos.
            destination = self._last_known_pos
            if destination is None:
                return task.cont

        self._move_toward(destination, speed, dt)
        return task.cont

    # ── FSM update ────────────────────────────────────────────────────────────

    def _update_fsm(self, dt: float) -> None:
        conf   = self.confidence
        state  = self.alert_state

        if state == AlertState.IDLE:
            self._fsm_idle(conf)

        elif state == AlertState.CURIOUS:
            self._fsm_curious(conf, dt)

        elif state == AlertState.SUSPICIOUS:
            self._fsm_suspicious(conf, dt)

        elif state == AlertState.HUNTING:
            self._fsm_hunting(conf, dt)

        # GENERAL_ALARM has no automatic exit — GuardManager manages it.

    def _fsm_idle(self, conf: float) -> None:
        if conf >= SUSPICIOUS_THRESHOLD:
            self._last_known_pos = self._player.get_position()
            self._transition(AlertState.SUSPICIOUS)
        elif conf > CURIOUS_THRESHOLD:
            self._investigating_pos = self._player.get_position()
            self._investigate_timer = INVESTIGATE_TIME
            self._transition(AlertState.CURIOUS)

    def _fsm_curious(self, conf: float, dt: float) -> None:
        if conf >= SUSPICIOUS_THRESHOLD:
            self._last_known_pos = self._player.get_position()
            self._transition(AlertState.SUSPICIOUS)
            return

        # Update last-seen pos even for low confidence.
        if conf > CURIOUS_THRESHOLD:
            self._investigating_pos = self._player.get_position()
            self._investigate_timer = INVESTIGATE_TIME   # refresh

        self._investigate_timer -= dt
        if self._investigate_timer <= 0.0:
            self._investigate_timer = 0.0
            self._transition(AlertState.IDLE)

    def _fsm_suspicious(self, conf: float, dt: float) -> None:
        if conf >= SUSPICIOUS_THRESHOLD:
            # Player clearly visible — fill meter, update last known pos.
            self._last_known_pos  = self._player.get_position()
            self._alert_meter    += ALERT_FILL_RATE * dt
        else:
            # Player lost — drain meter.
            self._alert_meter -= ALERT_DRAIN_RATE * dt

        self._alert_meter = max(0.0, min(ALERT_MAX, self._alert_meter))

        if self._alert_meter >= ALERT_MAX:
            self._transition(AlertState.HUNTING)
        elif self._alert_meter <= 0.0:
            self._transition(AlertState.CURIOUS)

    def _fsm_hunting(self, conf: float, dt: float) -> None:
        if conf >= SUSPICIOUS_THRESHOLD:
            self._last_known_pos = self._player.get_position()
        # Promotion to GENERAL_ALARM is handled externally by GuardManager.
        # Demotion back to SUSPICIOUS only happens if GuardManager calls it
        # (when the simultaneous hunter count drops below 3).

    # ── transition helper ─────────────────────────────────────────────────────

    def _transition(self, new_state: AlertState) -> None:
        if new_state == self.alert_state:
            return

        old_state = self.alert_state
        self.alert_state = new_state

        # Reset meter on certain transitions.
        if new_state == AlertState.CURIOUS:
            self._alert_meter = 0.0
        if new_state == AlertState.HUNTING:
            self._alert_meter = ALERT_MAX

        # Fire callbacks.
        if self._on_state_change:
            self._on_state_change(self, old_state, new_state)
        if new_state == AlertState.HUNTING and self._on_hunting:
            self._on_hunting(self)

    # ── patrol helpers ────────────────────────────────────────────────────────

    def _get_patrol_destination(self, dt: float) -> Point3 | None:
        """
        Handles waypoint waiting logic and returns the current target Point3,
        or None while the guard is standing still at a waypoint.
        """
        if self._waiting:
            self._wait_timer -= dt
            if self._wait_timer <= 0.0:
                self._waiting = False
                self._advance_waypoint()
            return None   # signal: don't move this frame

        return self.waypoints[self._current_wp_index].position

    def _advance_waypoint(self) -> None:
        self._current_wp_index = (self._current_wp_index + 1) % len(self.waypoints)

    def _move_toward(self, target: Point3, speed: float, dt: float) -> None:
        """Move and rotate toward target at the given speed."""
        current: Point3 = self.node_path.getPos()
        to_target: Vec3 = target - current
        distance: float = to_target.length()

        if distance <= ARRIVE_THRESHOLD:
            self.node_path.setPos(target)
            # Only wait at waypoints when patrolling.
            if (self.alert_state == AlertState.IDLE and
                    target == self.waypoints[self._current_wp_index].position):
                wait = self.waypoints[self._current_wp_index].wait_time
                if wait > 0.0:
                    self._waiting    = True
                    self._wait_timer = wait
                else:
                    self._advance_waypoint()
            return

        direction: Vec3  = to_target.normalized()
        step:      float = min(speed * dt, distance)
        self.node_path.setPos(current + direction * step)

        target_h: float  = math.degrees(math.atan2(-direction.x, direction.y))
        current_h: float = self.node_path.getH()
        delta:     float = (target_h - current_h + 180.0) % 360.0 - 180.0
        max_turn:  float = TURN_SPEED * dt
        self.node_path.setH(current_h + max(-max_turn, min(max_turn, delta)))

    # ── visual feedback ───────────────────────────────────────────────────────

    def _update_card_color(self) -> None:
        """Tint the placeholder card to reflect alert state at a glance."""
        colors = {
            AlertState.IDLE:          (0.2,  0.8,  0.3,  1.0),   # green
            AlertState.CURIOUS:       (0.9,  0.85, 0.1,  1.0),   # yellow
            AlertState.SUSPICIOUS:    (1.0,  0.45, 0.0,  1.0),   # orange
            AlertState.HUNTING:       (1.0,  0.1,  0.1,  1.0),   # red
            AlertState.GENERAL_ALARM: (0.9,  0.1,  0.9,  1.0),   # magenta
        }
        self._card_np.setColor(*colors.get(self.alert_state, (1, 1, 1, 1)))

    # ── helpers ───────────────────────────────────────────────────────────────

    def get_position(self) -> Point3:
        return self.node_path.getPos()

    @property
    def alert_meter(self) -> float:
        """Alert meter value 0–100, readable by HUD."""
        return self._alert_meter

    def __repr__(self) -> str:
        pos = self.get_position()
        return (
            f"<Guard '{self.name}' {self.alert_state} "
            f"conf={self.confidence:.2f} meter={self._alert_meter:.0f} "
            f"pos=({pos.x:.1f},{pos.y:.1f},{pos.z:.1f})>"
        )