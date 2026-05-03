# src/guard/guard_manager.py
"""
GuardManager — Phase 3
-----------------------
Singleton that owns all Guard instances and coordinates between them.

Responsibilities
----------------
1. Register / unregister guards.
2. Dispatch sound events to all guards within radius.
3. Scan for body nodes in the scene every BODY_SCAN_INTERVAL seconds;
   notify guards that are close enough to spot one.
4. Count simultaneous HUNTING guards; promote to GENERAL_ALARM at threshold.
5. Expose get_alert_level() → int 0–3 for HUD / Environment module.
6. Expose register_sound_event() for the player module and environment
   to call when something noisy happens (thrown objects, footsteps, etc.).

Alert level mapping
-------------------
  0 → all guards IDLE or CURIOUS
  1 → at least one guard SUSPICIOUS
  2 → at least one guard HUNTING
  3 → GENERAL_ALARM active

Usage
-----
    manager = GuardManager(base)
    manager.add_guard(guard_a)
    manager.add_guard(guard_b)
    manager.start()

    # From anywhere in the game:
    manager.register_sound_event(pos=Point3(x,y,z), radius=8.0, intensity=0.9)
    manager.get_alert_level()   # → int 0–3

Singleton pattern
-----------------
Access the running instance via GuardManager.instance after creation.
There should only ever be one GuardManager per game session.
"""

from __future__ import annotations

from panda3d.core import Point3, NodePath
from direct.showbase.ShowBase import ShowBase

from src.guard.guard import Guard
from src.guard.alert_state import AlertState

# ── constants ─────────────────────────────────────────────────────────────────
HUNTING_THRESHOLD:    int   = 3      # simultaneous hunters needed for GENERAL_ALARM
BODY_SCAN_INTERVAL:   float = 0.5    # seconds between body-detection sweeps
BODY_DETECT_RANGE:    float = 6.0    # units — must be within this range to spot body
# ─────────────────────────────────────────────────────────────────────────────


class GuardManager:
    """
    Singleton coordinator for all guards.

    Parameters
    ----------
    base : running ShowBase instance.
    """

    instance: "GuardManager | None" = None

    def __init__(self, base: ShowBase) -> None:
        if GuardManager.instance is not None:
            raise RuntimeError(
                "GuardManager is a singleton. "
                "Access the existing instance via GuardManager.instance."
            )
        GuardManager.instance = self

        self._base:   ShowBase    = base
        self._guards: list[Guard] = []

        self._general_alarm_active: bool  = False
        self._body_scan_timer:      float = 0.0
        self._task_name: str = "guard_manager_task"

    # ── guard registration ────────────────────────────────────────────────────

    def add_guard(self, guard: Guard) -> None:
        """
        Register a guard with the manager and wire its callbacks.
        Call before start().
        """
        guard._on_state_change = self._on_guard_state_change
        guard._on_hunting      = self._on_guard_hunting
        self._guards.append(guard)

    def remove_guard(self, guard: Guard) -> None:
        """Unregister a guard (e.g. when it is destroyed mid-game)."""
        if guard in self._guards:
            self._guards.remove(guard)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start all registered guards and the manager's own update task."""
        for guard in self._guards:
            guard.start()
        self._base.taskMgr.add(self._manager_task, self._task_name)

    def stop(self) -> None:
        """Pause all guards and the manager task."""
        for guard in self._guards:
            guard.stop()
        self._base.taskMgr.remove(self._task_name)

    def destroy(self) -> None:
        """Destroy all guards, remove task, and clear the singleton."""
        self.stop()
        for guard in self._guards:
            guard.destroy()
        self._guards.clear()
        GuardManager.instance = None

    # ── public API (integration layer) ───────────────────────────────────────

    def register_sound_event(
        self,
        pos:       Point3,
        radius:    float,
        intensity: float,
    ) -> None:
        """
        Broadcast a sound event.  Every guard whose current position is
        within `radius` units of `pos` is notified.

        Parameters
        ----------
        pos       : world position where the sound originated.
        radius    : how far the sound carries (units).
        intensity : 0.0–1.0 loudness hint (reserved for future scaling).
        """
        for guard in self._guards:
            dist = (guard.get_position() - pos).length()
            if dist <= radius:
                guard.on_sound_event(pos, intensity)

    def get_alert_level(self) -> int:
        """
        Returns the global alert level as an int 0–3.
          0 = calm      (all IDLE or CURIOUS)
          1 = elevated  (at least one SUSPICIOUS)
          2 = high      (at least one HUNTING)
          3 = alarm     (GENERAL_ALARM active)
        """
        if self._general_alarm_active:
            return 3
        states = {g.alert_state for g in self._guards}
        if AlertState.HUNTING in states:
            return 2
        if AlertState.SUSPICIOUS in states:
            return 1
        return 0

    def get_all_guards(self) -> list[Guard]:
        """Return a snapshot of the current guard list."""
        return list(self._guards)

    # ── manager task ──────────────────────────────────────────────────────────

    def _manager_task(self, task):
        dt: float = globalClock.getDt()
        self._check_general_alarm()
        self._scan_bodies(dt)
        return task.cont

    # ── general alarm logic ───────────────────────────────────────────────────

    def _check_general_alarm(self) -> None:
        """
        Promote all guards to GENERAL_ALARM if HUNTING_THRESHOLD or more
        guards are simultaneously in the HUNTING state.
        """
        if self._general_alarm_active:
            return   # already in alarm — no further check needed

        hunting_count = sum(
            1 for g in self._guards
            if g.alert_state == AlertState.HUNTING
        )
        if hunting_count >= HUNTING_THRESHOLD:
            self._trigger_general_alarm()

    def _trigger_general_alarm(self) -> None:
        """Promote every guard to GENERAL_ALARM."""
        self._general_alarm_active = True
        for guard in self._guards:
            guard._transition(AlertState.GENERAL_ALARM)
        print("[GuardManager] ⚠ GENERAL ALARM triggered!")

    # ── body detection ────────────────────────────────────────────────────────

    def _scan_bodies(self, dt: float) -> None:
        """
        Periodically scan render for NodePaths tagged with BODY_TAG.
        Any guard within BODY_DETECT_RANGE of a body transitions to
        at least SUSPICIOUS.

        Teammate A tags a knocked-out guard node like this:
            knocked_out_guard_np.setTag("guard_body", "1")
        """
        self._body_scan_timer -= dt
        if self._body_scan_timer > 0.0:
            return
        self._body_scan_timer = BODY_SCAN_INTERVAL

        # Collect all body nodes currently in the scene.
        bodies: list[NodePath] = self._base.render.findAllMatches(
            f"**" ).asList()
        body_positions: list[Point3] = []
        for np in bodies:
            if np.hasTag("guard_body"):
                body_positions.append(np.getPos(self._base.render))

        if not body_positions:
            return

        for guard in self._guards:
            if guard.alert_state in (AlertState.SUSPICIOUS,
                                     AlertState.HUNTING,
                                     AlertState.GENERAL_ALARM):
                continue   # already alarmed — body doesn't add new info

            guard_pos = guard.get_position()
            for body_pos in body_positions:
                if (guard_pos - body_pos).length() <= BODY_DETECT_RANGE:
                    guard.on_body_spotted()
                    break   # one body is enough to trigger this guard

    # ── guard callbacks ───────────────────────────────────────────────────────

    def _on_guard_state_change(
        self,
        guard:     Guard,
        old_state: AlertState,
        new_state: AlertState,
    ) -> None:
        """Called by individual guards when their state changes."""
        print(
            f"[GuardManager] {guard.name}: "
            f"{old_state} → {new_state}"
        )

    def _on_guard_hunting(self, guard: Guard) -> None:
        """Called each time a guard enters HUNTING."""
        print(f"[GuardManager] {guard.name} is now HUNTING — checking alarm threshold.")
        self._check_general_alarm()

    # ── helpers ───────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<GuardManager guards={len(self._guards)} "
            f"alert_level={self.get_alert_level()} "
            f"alarm={self._general_alarm_active}>"
        )