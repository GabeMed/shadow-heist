import math
import random

from panda3d.core import (
    CardMaker, NodePath, Vec3, Vec4, ColorBlendAttrib,
    TransparencyAttrib, BillboardEffect, Point3, BitMask32,
)

from core.shadow_pass import SHADOW_CASTER_BIT


class _Particle:
    __slots__ = ("np", "vx", "vy", "vz", "life", "max_life", "size0")

    def __init__(self, np, life, vx, vy, vz, size0):
        self.np = np
        self.life = life
        self.max_life = life
        self.vx, self.vy, self.vz = vx, vy, vz
        self.size0 = size0


class TorchFire:
    """
    Lightweight CPU particle flame anchored above a torch. Emits warm
    billboarded quads that rise, shrink, and fade. Additive blend gives
    the glow look without needing a real particle texture.
    """

    NUM_PARTICLES = 14

    def __init__(self, base, parent_np, offset=(0.0, 0.0, 1.0)):
        self.base = base
        self.root = parent_np.attachNewNode("torch_fire")
        self.root.setPos(*offset)
        self.root.setLightOff()      # flame should not be lit by scene
        self.root.setShaderOff()     # bypass scene shader
        self.root.setBin("fixed", 50)
        self.root.setDepthWrite(False)
        # Don't cast shadows — additive billboards have no meaningful depth.
        self.root.hide(BitMask32.bit(SHADOW_CASTER_BIT))

        cm = CardMaker("flame_card")
        cm.setFrame(-0.18, 0.18, 0.0, 0.36)

        self._particles: list[_Particle] = []
        for _ in range(self.NUM_PARTICLES):
            np = self.root.attachNewNode(cm.generate())
            np.setBillboardPointEye()
            np.setTransparency(TransparencyAttrib.M_alpha)
            np.setAttrib(ColorBlendAttrib.make(
                ColorBlendAttrib.M_add,
                ColorBlendAttrib.O_incoming_alpha,
                ColorBlendAttrib.O_one,
            ))
            np.setColor(1.0, 0.7, 0.2, 1.0)
            self._particles.append(self._spawn_particle(np, initial=True))

    def _spawn_particle(self, np, initial=False):
        max_life = random.uniform(0.45, 0.85)
        life = random.uniform(0.0, max_life) if initial else max_life
        vx = random.uniform(-0.15, 0.15)
        vy = random.uniform(-0.15, 0.15)
        vz = random.uniform(0.6, 1.1)
        size0 = random.uniform(0.7, 1.3)
        np.setPos(random.uniform(-0.06, 0.06),
                  random.uniform(-0.06, 0.06),
                  random.uniform(0.0, 0.15))
        return _Particle(np, life, vx, vy, vz, size0)

    def update(self, dt):
        for p in self._particles:
            p.life -= dt
            if p.life <= 0.0:
                # Recycle.
                new = self._spawn_particle(p.np, initial=False)
                p.life = new.life
                p.max_life = new.max_life
                p.vx, p.vy, p.vz = new.vx, new.vy, new.vz
                p.size0 = new.size0
                continue
            t = 1.0 - (p.life / p.max_life)  # 0 → 1 across life
            pos = p.np.getPos()
            p.np.setPos(pos.x + p.vx * dt,
                        pos.y + p.vy * dt,
                        pos.z + p.vz * dt)
            # Color: yellow → orange → red as t grows.
            r = 1.0
            g = max(0.05, 0.85 - 0.85 * t)
            b = max(0.0, 0.2 - 0.4 * t)
            a = (1.0 - t) ** 1.4
            p.np.setColor(r, g, b, a)
            # Size: grows then shrinks.
            s = p.size0 * (1.0 + 0.6 * math.sin(t * math.pi))
            p.np.setScale(s)


class TorchFireManager:
    """
    Finds every node named 'castle_torch_*' under render and attaches a
    TorchFire to the torch tip. Tickes them every frame from a single task.
    """

    def __init__(self, base, tip_offset=(0.0, 0.0, 1.0)):
        self.base = base
        self.fires: list[TorchFire] = []

        torches = base.render.findAllMatches("**/castle_torch_*")
        for i in range(torches.getNumPaths()):
            torch = torches.getPath(i)
            self.fires.append(TorchFire(base, torch, offset=tip_offset))

        base.taskMgr.add(self._update_task, "torch_fire_task")

    def _update_task(self, task):
        dt = globalClock.getDt()
        for f in self.fires:
            f.update(dt)
        return task.cont
