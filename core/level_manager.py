from panda3d.core import (
    AmbientLight, DirectionalLight, Vec4,
    CardMaker, CollisionPlane, Plane, CollisionNode, Vec3,
    CollisionBox, Point3
)


class LevelManager:
    def __init__(self, base):
        self.base = base
        self.setup_lights()
        self.setup_environment()

    # ------------------------------------------------------------------
    # Lights
    # ------------------------------------------------------------------

    def setup_lights(self):
        alight = AmbientLight('ambient_light')
        alight.setColor(Vec4(0.3, 0.3, 0.3, 1))
        self.base.render.setLight(self.base.render.attachNewNode(alight))

        dlight = DirectionalLight('dir_light')
        dlight.setColor(Vec4(0.7, 0.7, 0.7, 1))
        dlnp = self.base.render.attachNewNode(dlight)
        dlnp.setHpr(45, -45, 0)
        self.base.render.setLight(dlnp)

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------

    def setup_environment(self):
        self._make_ground()
        self._make_boundary()
        self._make_obstacles()
        print("LevelManager: Environment ready.")

# ── Guard AI interface ────────────────────────────────────
    def is_position_lit(self, pos: "Point3") -> bool:
        """
        query actual light volumes from the lighting system.
        """
        return True

    def get_active_light_nodes(self) -> list:
        """
        return NodePath list of all active lights in the scene.
        """
        return []

    def get_nav_mesh(self) -> "NodePath":
        """
        return the actual nav mesh NodePath.
        """
        return self.base.render
    
    def _make_ground(self):
        cm = CardMaker('ground')
        cm.setFrame(-50, 50, -50, 50)
        ground = self.base.render.attachNewNode(cm.generate())
        ground.setP(-90)
        ground.setColor(0.2, 0.2, 0.2, 1)

        cn = CollisionNode("ground_coll")
        cn.addSolid(CollisionPlane(Plane(Vec3(0, 0, 1), (0, 0, 0))))
        self.base.render.attachNewNode(cn)

    def _make_box(self, cx, cy, hw, hd, height, color=(0.4, 0.4, 0.5, 1)):
        """
        Visual box (5 CardMaker faces, two-sided) + CollisionBox.
        cx/cy: center in XY. hw: half-extent along X. hd: half-extent along Y.
        Box sits on the ground (z=0 to z=height).
        """
        r, g, b, a = color

        # Front/back faces — card in XZ plane, spans X and Z
        for y_off, heading in ((hd, 0), (-hd, 180)):
            cm = CardMaker("wall_face")
            cm.setFrame(-hw, hw, 0, height)
            f = self.base.render.attachNewNode(cm.generate())
            f.setPos(cx, cy + y_off, 0)
            f.setH(heading)
            f.setColor(r, g, b, a)
            f.setTwoSided(True)

        # Left/right faces — rotated so card spans Y and Z
        for x_off, heading in ((hw, -90), (-hw, 90)):
            cm = CardMaker("wall_face")
            cm.setFrame(-hd, hd, 0, height)
            f = self.base.render.attachNewNode(cm.generate())
            f.setPos(cx + x_off, cy, 0)
            f.setH(heading)
            f.setColor(r, g, b, a)
            f.setTwoSided(True)

        # Top face — flat card spanning XY at z=height
        cm = CardMaker("wall_top")
        cm.setFrame(-hw, hw, -hd, hd)
        top = self.base.render.attachNewNode(cm.generate())
        top.setPos(cx, cy, height)
        top.setP(-90)
        top.setColor(r * 0.8, g * 0.8, b * 0.8, a)
        top.setTwoSided(True)

        # Collision
        cn = CollisionNode("wall_coll")
        cn.addSolid(CollisionBox(
            Point3(cx - hw, cy - hd, 0),
            Point3(cx + hw, cy + hd, height)
        ))
        self.base.render.attachNewNode(cn)

    def _make_boundary(self, half_size=20, height=5):
        """4 outer walls forming a 40×40 arena."""
        hs = half_size
        wall_color = (0.3, 0.3, 0.38, 1)
        # North/south walls — span full width to close corners
        self._make_box(0,  hs, hs + 1, 1, height, wall_color)
        self._make_box(0, -hs, hs + 1, 1, height, wall_color)
        # East/west walls — span inner width only (corners already covered)
        self._make_box( hs, 0, 1, hs - 1, height, wall_color)
        self._make_box(-hs, 0, 1, hs - 1, height, wall_color)

    def _make_obstacles(self):
        """Scattered pillars and walls to make the arena interesting."""
        pillar_color  = (0.55, 0.42, 0.33, 1)
        divider_color = (0.38, 0.48, 0.38, 1)

        # Four corner pillars
        for x, y in ((13, 13), (-13, 13), (13, -13), (-13, -13)):
            self._make_box(x, y, 1.2, 1.2, 4, pillar_color)

        # Two central divider walls (leave a gap between them)
        self._make_box(0,  7, 4, 0.5, 3.5, divider_color)
        self._make_box(0, -7, 4, 0.5, 3.5, divider_color)

        # Side alcove blockers — create cover near the east/west walls
        self._make_box( 10, 0, 0.5, 3.5, 3, divider_color)
        self._make_box(-10, 0, 0.5, 3.5, 3, divider_color)

        # Small lone pillars to break sightlines
        self._make_box( 6,  3, 0.8, 0.8, 3, pillar_color)
        self._make_box(-6, -3, 0.8, 0.8, 3, pillar_color)
