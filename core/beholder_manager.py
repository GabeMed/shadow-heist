import random

from panda3d.core import (
    BitMask32, CollisionTraverser, Point3,
)

import config as Cfg
from entities.beholder import Beholder, BeholderState


class BeholderManager:
    """
    Spawns and ticks the castle's beholders. Builds patrol routes from the
    house's room centers (avoids the spawn room and the trophy room so the
    player has a soft start and a final dash to the goal).
    """

    def __init__(self, base, on_caught):
        self.base       = base
        self.on_caught  = on_caught
        self.beholders  = []
        self._cones_visible = True

        self.los_traverser = CollisionTraverser("beholder_los_trav")
        self.los_mask      = BitMask32.bit(1)

        self._spawn_all()

        self.base.taskMgr.add(self._update_task, "beholder_manager_task")
        self.base.accept("v", self._toggle_cones)

    # ------------------------------------------------------------------
    # Spawning
    # ------------------------------------------------------------------

    def _spawn_all(self):
        house = getattr(self.base.level_manager, "house", None)
        if house is None or house.beholder_model is None:
            return

        rooms = list(house.rooms)
        excluded = {"portaria", "tesouro"}
        patrol_rooms = [r for r in rooms if r.name not in excluded]
        if len(patrol_rooms) < 2:
            return

        random.shuffle(patrol_rooms)
        count = min(Cfg.BEHOLDER_COUNT, max(1, len(patrol_rooms) // 2))

        # Each beholder gets a 3-room loop.
        for i in range(count):
            base_idx = (i * 3) % len(patrol_rooms)
            picks = [patrol_rooms[(base_idx + k) % len(patrol_rooms)]
                     for k in range(3)]
            waypoints = [Point3(r.center.x, r.center.y, 0.0) for r in picks]
            beholder = Beholder(
                base           = self.base,
                model_template = house.beholder_model,
                waypoints      = waypoints,
                on_caught      = self._handle_caught,
                los_traverser  = self.los_traverser,
                los_mask       = self.los_mask,
            )
            self.beholders.append(beholder)

    def _handle_caught(self):
        # Latch — only fire once per ALERT contact.
        if getattr(self, "_caught_fired", False):
            return
        self._caught_fired = True
        self.on_caught()

    def reset_caught(self):
        self._caught_fired = False

    # ------------------------------------------------------------------
    # Per-frame
    # ------------------------------------------------------------------

    def _update_task(self, task):
        if getattr(self.base, "game_paused", True):
            return task.cont
        dt = globalClock.getDt()

        player = getattr(self.base, "player", None)
        if player is None:
            return task.cont

        player_pos = player.player_node.getPos()
        camo       = bool(getattr(player, "is_camouflaged", False))

        for b in self.beholders:
            b.update(dt, player_pos, camo)
        return task.cont

    def _toggle_cones(self):
        self._cones_visible = not self._cones_visible
        for b in self.beholders:
            b.set_cone_visible(self._cones_visible)

    # ------------------------------------------------------------------
    # Queries (used by HUD)
    # ------------------------------------------------------------------

    def max_detection(self) -> float:
        if not self.beholders:
            return 0.0
        return max(b.detection for b in self.beholders)

    def any_alert(self) -> bool:
        return any(b.state == BeholderState.ALERT for b in self.beholders)

    def any_suspicious(self) -> bool:
        return any(b.state == BeholderState.SUSPICIOUS for b in self.beholders)

    def alert_all(self, pos):
        """Force every beholder into ALERT toward `pos` (e.g. shard pickup)."""
        if pos is None:
            return
        target = Point3(pos.x, pos.y, 0.0)
        for b in self.beholders:
            b.detection = 1.0
            b.state = BeholderState.ALERT
            b.last_seen_pos = target
            b.search_timer = Cfg.BEHOLDER_SEARCH_TIME

    def closest_pos(self, ref_pos):
        if not self.beholders:
            return None
        best = None
        best_d = float("inf")
        for b in self.beholders:
            p = b.get_pos()
            d = (p - ref_pos).length()
            if d < best_d:
                best_d = d
                best = p
        return best
