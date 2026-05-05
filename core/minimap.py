from direct.gui.DirectGui import DirectFrame
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import TextNode

import config as Cfg


# Map bounds (world units). Tuned to fit the full castle + south escape zone.
MAP_X_MIN, MAP_X_MAX = -75.0, 75.0
MAP_Y_MIN, MAP_Y_MAX = -95.0, 90.0


class Minimap:
    """
    Fixed-north minimap in the top-right corner. Renders dots for the player,
    beholders (color = state), the mirror, and the escape zone.
    """

    def __init__(self, base):
        self.base = base

        self._size = 0.32  # half-width/half-height in aspect2d units

        # Anchor to top-right — leave margin from edges.
        self._cx = base.a2dRight - self._size - 0.04
        self._cy = base.a2dTop   - self._size - 0.04

        self._frame = DirectFrame(
            frameColor=(0.05, 0.06, 0.08, 0.55),
            frameSize=(-self._size, self._size, -self._size, self._size),
            pos=(self._cx, 0, self._cy),
            parent=base.aspect2d,
        )

        # Border lines (cheap — DirectFrame thin strips).
        b = 0.005
        for fx in (-self._size, self._size):
            DirectFrame(
                frameColor=(0.95, 0.85, 0.4, 0.85),
                frameSize=(fx - b, fx + b, -self._size, self._size),
                parent=self._frame,
            )
        for fy in (-self._size, self._size):
            DirectFrame(
                frameColor=(0.95, 0.85, 0.4, 0.85),
                frameSize=(-self._size, self._size, fy - b, fy + b),
                parent=self._frame,
            )

        OnscreenText(
            text="MAPA",
            pos=(0, self._size - 0.04),
            scale=0.035,
            fg=(1, 0.95, 0.7, 0.9),
            parent=self._frame,
            align=TextNode.ACenter,
            mayChange=False,
        )

        # Static markers (mirror + exit) — created once; positions refreshed.
        self._mirror_dot = self._make_dot(0.012, (0.6, 0.95, 1.0, 1.0))
        self._exit_dot   = self._make_dot(0.014, (0.4, 1.0, 0.4, 1.0))
        self._player_dot = self._make_dot(0.014, (1.0, 0.85, 0.2, 1.0))

        self._beholder_dots = []

        base.taskMgr.add(self._update_task, "minimap_task")

    # ------------------------------------------------------------------

    def _make_dot(self, radius, color):
        return DirectFrame(
            frameColor=color,
            frameSize=(-radius, radius, -radius, radius),
            parent=self._frame,
        )

    def _world_to_local(self, x, y):
        # Note: aspect2d X = world X (left-right), aspect2d Z (Y param of pos)
        # = vertical (world Y). Map -75..75 → -size..size.
        nx = (x - MAP_X_MIN) / (MAP_X_MAX - MAP_X_MIN)
        ny = (y - MAP_Y_MIN) / (MAP_Y_MAX - MAP_Y_MIN)
        lx = (nx * 2.0 - 1.0) * self._size
        ly = (ny * 2.0 - 1.0) * self._size
        return lx, ly

    def _set_dot(self, dot, x, y):
        lx, ly = self._world_to_local(x, y)
        dot.setPos(lx, 0, ly)

    # ------------------------------------------------------------------

    def _update_task(self, task):
        # Player.
        player = getattr(self.base, "player", None)
        if player is not None:
            p = player.player_node.getPos()
            self._set_dot(self._player_dot, p.x, p.y)

        # Mirror.
        item_mgr = getattr(self.base, "item_manager", None)
        if item_mgr is not None and item_mgr.mirror is not None:
            m = item_mgr.mirror
            held = getattr(m, "is_held", False)
            if held and player is not None:
                # Mirror rides with player — hide separate dot.
                self._mirror_dot.hide()
            else:
                self._mirror_dot.show()
                if hasattr(m, "node"):
                    mp = m.node.getPos()
                    self._set_dot(self._mirror_dot, mp.x, mp.y)

        # Exit.
        ex, ey = Cfg.HEIST_EXIT_POS
        self._set_dot(self._exit_dot, ex, ey)

        # Beholders — keep dot count synced.
        bm = getattr(self.base, "beholder_manager", None)
        if bm is not None:
            self._sync_beholder_dots(bm.beholders)
        return task.cont

    def _sync_beholder_dots(self, beholders):
        from entities.beholder import BeholderState
        while len(self._beholder_dots) < len(beholders):
            self._beholder_dots.append(self._make_dot(0.012, (1, 0.2, 0.2, 1)))
        while len(self._beholder_dots) > len(beholders):
            d = self._beholder_dots.pop()
            d.destroy()

        for dot, b in zip(self._beholder_dots, beholders):
            p = b.get_pos()
            self._set_dot(dot, p.x, p.y)
            if b.state == BeholderState.ALERT:
                dot["frameColor"] = (1.0, 0.15, 0.15, 1.0)
            elif b.state == BeholderState.SUSPICIOUS:
                dot["frameColor"] = (1.0, 0.85, 0.15, 1.0)
            else:
                dot["frameColor"] = (0.85, 0.4, 0.4, 0.95)
