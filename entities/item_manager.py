import config
from entities.grabbable_object import GrabbableObject


class ItemManager:
    # Posições escolhidas para evitar sobreposição com paredes e pilares do nível
    _SPAWNS = [
        ("gold_bar",       ( 6.0,  -9.0)),
        ("diamond",        (-7.0,  10.0)),
        ("pearl_necklace", ( 3.0, -14.0)),
        ("money_bundle",   (-4.0,  14.0)),
        ("ruby",           (15.0,   5.0)),
        ("coin_pile",      (-15.0, -5.0)),
        ("gold_bar",       ( 9.0,   9.0)),
        ("diamond",        (-9.0,  -9.0)),
        ("money_bundle",   ( 0.0,  -4.0)),
        ("coin_pile",      ( 0.0,   4.0)),
    ]

    def __init__(self, base):
        self.base  = base
        self.items = []

        for item_type, pos in self._SPAWNS:
            self._spawn(item_type, pos)

        base.taskMgr.add(self._update_task, "item_manager_task")

    def _spawn(self, item_type, pos):
        item = GrabbableObject(self.base, item_type, pos)
        self.items.append(item)

    def try_grab_nearest(self, player_pos):
        """Retorna o valor do item mais próximo dentro do alcance, ou None."""
        best      = None
        best_dist = float("inf")
        for item in self.items:
            d = (item.node.getPos() - player_pos).length()
            if d < best_dist:
                best_dist = d
                best      = item

        if best is None or best_dist > config.GRAB_RANGE:
            return None

        self.items.remove(best)
        value = best.value
        best.remove()
        return value

    def _update_task(self, task):
        if getattr(self.base, "game_paused", True):
            return task.cont
        t = self.base.clock.getFrameTime()
        for item in self.items:
            item.update_highlight(t)
        return task.cont
