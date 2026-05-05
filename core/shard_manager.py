import random

from panda3d.core import Point3

import config as Cfg
from entities.shard import RelicShard


class ShardManager:
    """Spawns the relic shards across distinct rooms; tracks collection."""

    def __init__(self, base):
        self.base = base
        self.shards = []
        self.collected_count = 0
        self._last_collected_index = -1

        spawns = self._pick_spawn_points()
        for i in range(min(Cfg.SHARD_COUNT, len(spawns))):
            sx, sy = spawns[i]
            shard = RelicShard(
                base=base,
                index=i,
                name=Cfg.SHARD_NAMES[i % len(Cfg.SHARD_NAMES)],
                pos=Point3(sx, sy, 0.0),
                color=Cfg.SHARD_COLORS[i % len(Cfg.SHARD_COLORS)],
            )
            self.shards.append(shard)

        base.taskMgr.add(self._task, "shard_manager_task")

    def _pick_spawn_points(self):
        house = getattr(self.base.level_manager, "house", None)
        if house is None:
            return [(0.0, 0.0)] * Cfg.SHARD_COUNT
        # Use distinct rooms, prefer rooms far from spawn / mirror room.
        rooms = [r for r in house.rooms if r.name != "salao_central"]
        random.shuffle(rooms)
        picks = []
        for room in rooms[:Cfg.SHARD_COUNT]:
            picks.append((room.center.x, room.center.y))
        while len(picks) < Cfg.SHARD_COUNT:
            picks.append((0.0, 0.0))
        return picks

    def _task(self, task):
        if getattr(self.base, "game_paused", True):
            return task.cont

        dt = self.base.clock.getDt()
        player = getattr(self.base, "player", None)
        if player is None:
            return task.cont
        ppos = player.player_node.getPos()

        for shard in self.shards:
            if shard.collected:
                continue
            if shard.update(dt, ppos):
                self.collected_count += 1
                self._last_collected_index = shard.index
                self._on_collected(shard)
        return task.cont

    def _on_collected(self, shard):
        # Hook for future audio / VFX. For now just trigger beholder alert.
        bm = getattr(self.base, "beholder_manager", None)
        if bm is not None and hasattr(bm, "alert_all"):
            bm.alert_all(shard._spawn_pos)

    def all_collected(self) -> bool:
        return self.collected_count >= len(self.shards)

    def remaining(self) -> int:
        return max(0, len(self.shards) - self.collected_count)

    def reset(self):
        self.collected_count = 0
        self._last_collected_index = -1
        for shard in self.shards:
            shard.reset()
