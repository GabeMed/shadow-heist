import math

from panda3d.core import (
    CardMaker, NodePath, Point3, Vec3, PointLight, BitMask32,
    TransparencyAttrib,
)

import config as Cfg


class RelicShard:
    """Glowing crystal shard. Picks up on proximity."""

    def __init__(self, base, index, name, pos, color):
        self.base = base
        self.index = index
        self.name = name
        self.color = color
        self.collected = False
        self._t0 = base.clock.getFrameTime()
        self._spawn_pos = Point3(pos.x, pos.y, pos.z)

        self.root = base.render.attachNewNode(f"shard_{index}_root")
        self.root.setPos(pos)

        # Visual: 4 perpendicular CardMaker quads forming a diamond billboard.
        cm = CardMaker(f"shard_{index}_card")
        cm.setFrame(-0.45, 0.45, -0.9, 0.9)
        self._spinner = self.root.attachNewNode(f"shard_{index}_spin")
        for h in (0.0, 45.0, 90.0, 135.0):
            face = self._spinner.attachNewNode(cm.generate())
            face.setH(h)
            face.setColor(*color)
            face.setTwoSided(True)
            face.setTransparency(TransparencyAttrib.MAlpha)
        self._spinner.setLightOff()
        self._spinner.setShaderOff()  # bypass scene shader so color is pure

        # Glow light so shard reads in dark rooms.
        plight = PointLight(f"shard_{index}_light")
        plight.setColor((color[0], color[1], color[2], 1.0))
        plight.setAttenuation(Vec3(1.0, 0.55, 0.45))
        self._light_np = self.root.attachNewNode(plight)
        self._light_np.setZ(1.2)
        base.render.setLight(self._light_np)

    def update(self, dt, player_pos):
        if self.collected:
            return False

        t = self.base.clock.getFrameTime() - self._t0
        bob = math.sin(t * Cfg.SHARD_BOB_SPEED * 2.0 * math.pi) * Cfg.SHARD_BOB_AMPLITUDE
        self.root.setZ(self._spawn_pos.z + 1.2 + bob)
        self._spinner.setH((t * Cfg.SHARD_SPIN_SPEED) % 360.0)

        d = (Point3(player_pos.x, player_pos.y, 0.0)
             - Point3(self._spawn_pos.x, self._spawn_pos.y, 0.0)).length()
        if d <= Cfg.SHARD_PICKUP_RADIUS:
            self._collect()
            return True
        return False

    def _collect(self):
        self.collected = True
        self.base.render.clearLight(self._light_np)
        self._light_np.removeNode()
        self.root.removeNode()

    def reset(self):
        if not self.collected:
            return
        self.collected = False
        self.root = self.base.render.attachNewNode(f"shard_{self.index}_root")
        self.root.setPos(self._spawn_pos)
        cm = CardMaker(f"shard_{self.index}_card")
        cm.setFrame(-0.45, 0.45, -0.9, 0.9)
        self._spinner = self.root.attachNewNode(f"shard_{self.index}_spin")
        for h in (0.0, 45.0, 90.0, 135.0):
            face = self._spinner.attachNewNode(cm.generate())
            face.setH(h)
            face.setColor(*self.color)
            face.setTwoSided(True)
            face.setTransparency(TransparencyAttrib.MAlpha)
        self._spinner.setLightOff()
        self._spinner.setShaderOff()
        plight = PointLight(f"shard_{self.index}_light")
        plight.setColor((self.color[0], self.color[1], self.color[2], 1.0))
        plight.setAttenuation(Vec3(1.0, 0.55, 0.45))
        self._light_np = self.root.attachNewNode(plight)
        self._light_np.setZ(1.2)
        self.base.render.setLight(self._light_np)
        self._t0 = self.base.clock.getFrameTime()
