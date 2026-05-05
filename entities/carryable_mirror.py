from panda3d.core import Point3


class CarryableMirror:
    def __init__(self, base, pos):
        self.base = base
        self.is_held = False
        self.holder = None
        self._drop_hpr = None
        self.node = base.render.attachNewNode("carryable_mirror")

        try:
            model = base.loader.loadModel("assets/gilded_mirror.egg")
        except OSError:
            model = None

        if model is None or model.isEmpty():
            model = base.loader.loadModel("models/misc/sphere")
            model.setScale(0.8)

        model.reparentTo(self.node)
        model.setScale(2.30)
        self.node.setPos(pos[0], pos[1], 0.0)
        self.node.setH(180.0)

    def distance_to(self, player_pos):
        return (self.node.getPos() - player_pos).length()

    def pickup(self, holder_np):
        if self.is_held:
            return False

        self.holder = holder_np
        self.node.reparentTo(holder_np)
        self.node.setPos(0.0, 1.15, 0.12)
        self.node.setHpr(180.0, 0.0, 0.0)
        self.is_held = True
        return True

    def drop(self, world_pos):
        if not self.is_held:
            return False

        forward = self.holder.getRelativeVector(self.base.render, (0, 1, 0))
        forward.setZ(0.0)
        if forward.lengthSquared() > 0.0:
            forward.normalize()
        forward_offset = forward * -1.4

        self.node.wrtReparentTo(self.base.render)
        self.node.setPos(
            Point3(
                world_pos.x + forward_offset.x,
                world_pos.y + forward_offset.y,
                max(world_pos.z, 0.05),
            )
        )
        if self.holder is not None:
            self.node.setH(self.holder.getH(self.base.render) + 180.0)
        self.holder = None
        self.is_held = False
        return True
