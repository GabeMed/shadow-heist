# entities/guard/alert_state.py
"""
AlertState — Phase 3
---------------------
Enum for all guard alert levels.

Transition map (enforced in guard.py):

  IDLE
    → CURIOUS      on sound event within hearing range, or
                   confidence > 0 but < SUSPICIOUS_THRESHOLD
    → SUSPICIOUS   if a body node is spotted while IDLE (skip CURIOUS)

  CURIOUS
    → IDLE         if investigate timer expires with no further stimulus
    → SUSPICIOUS   if confidence >= SUSPICIOUS_THRESHOLD while investigating

  SUSPICIOUS
    → CURIOUS      if alert meter drains back to 0 (player lost for long enough)
    → HUNTING      if alert meter reaches 100

  HUNTING
    → SUSPICIOUS   if all guards drop below 3 simultaneous HUNTING
    → GENERAL_ALARM if 3+ guards are in HUNTING at the same time
                   (managed by GuardManager, not individual guard)

  GENERAL_ALARM
    → no automatic exit; requires game-level reset (Phase 4 / game logic)
"""

from enum import Enum, auto


class AlertState(Enum):
    IDLE          = auto()
    CURIOUS       = auto()
    SUSPICIOUS    = auto()
    HUNTING       = auto()
    GENERAL_ALARM = auto()

    def __str__(self) -> str:
        return self.name