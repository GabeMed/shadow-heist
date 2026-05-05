import config
from entities.grabbable_object import GrabbableObject
from entities.carryable_mirror import CarryableMirror


class ItemManager:
    _ITEM_TYPES = [
        "gold_bar",
        "diamond",
        "pearl_necklace",
        "money_bundle",
        "ruby",
        "coin_pile",
        "gold_bar",
        "diamond",
        "money_bundle",
        "coin_pile",
    ]

    def __init__(self, base):
        self.base = base
        self.items = []
        self.mirror = None

        for item_type, pos in self._get_spawn_plan():
            self._spawn(item_type, pos)

        self._spawn_mirror()

        base.taskMgr.add(self._update_task, "item_manager_task")

    def _spawn(self, item_type, pos):
        item = GrabbableObject(self.base, item_type, pos)
        self.items.append(item)

    def _spawn_mirror(self):
        if not hasattr(self.base, "level_manager") or not hasattr(self.base.level_manager, "house"):
            return
        pos = self.base.level_manager.house.get_mirror_spawn_point()
        self.mirror = CarryableMirror(self.base, pos)

    def _get_spawn_plan(self):
        if hasattr(self.base, "level_manager") and hasattr(self.base.level_manager, "house"):
            points = self.base.level_manager.house.get_item_spawn_points(len(self._ITEM_TYPES))
            for item_type, (x, y) in zip(self._ITEM_TYPES, points):
                yield item_type, (x, y)
            return

        scale = config.HOUSE_LAYOUT_SCALE
        fallback = [
            (-9.0, -11.0),
            (-6.0, -7.0),
            (6.0, -11.0),
            (9.0, -7.0),
            (-8.5, 1.0),
            (-5.5, 3.0),
            (6.0, 1.0),
            (9.0, 3.0),
            (-7.5, 10.0),
            (8.0, 10.5),
        ]
        for item_type, (x, y) in zip(self._ITEM_TYPES, fallback):
            yield item_type, (x * scale, y * scale)

    def try_grab_nearest(self, player_pos):
        """Retorna o valor do item mais proximo dentro do alcance, ou None."""
        best = None
        best_dist = float("inf")
        for item in self.items:
            d = (item.node.getPos() - player_pos).length()
            if d < best_dist:
                best_dist = d
                best = item

        if best is None or best_dist > config.GRAB_RANGE:
            return None

        self.items.remove(best)
        value = best.value
        best.remove()
        return value

    def try_pickup_mirror(self, player_pos, player_node):
        if self.mirror is None or self.mirror.is_held:
            return False
        if self.mirror.distance_to(player_pos) > config.GRAB_RANGE:
            return False
        return self.mirror.pickup(player_node)

    def drop_mirror(self, player_pos):
        if self.mirror is None or not self.mirror.is_held:
            return False
        return self.mirror.drop(player_pos)

    def is_mirror_held(self):
        return self.mirror is not None and self.mirror.is_held

    def _update_task(self, task):
        if getattr(self.base, "game_paused", True):
            return task.cont
        t = self.base.clock.getFrameTime()
        for item in self.items:
            item.update_highlight(t)
        return task.cont
