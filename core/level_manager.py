from panda3d.core import (
    AmbientLight,
    CardMaker,
    CollisionNode,
    CollisionPlane,
    DirectionalLight,
    Plane,
    Vec3,
    Vec4,
)

import config as Cfg
from core.house_builder import HouseBuilder


class LevelManager:
    def __init__(self, base):
        self.base = base
        self.setup_lights()
        self.setup_environment()

    # ------------------------------------------------------------------
    # Lights
    # ------------------------------------------------------------------

    def setup_lights(self):
        alight = AmbientLight("ambient_light")
        alight.setColor(Vec4(0.35, 0.35, 0.35, 1))
        self.base.render.setLight(self.base.render.attachNewNode(alight))

        dlight = DirectionalLight("dir_light")
        dlight.setColor(Vec4(0.72, 0.72, 0.68, 1))
        dlnp = self.base.render.attachNewNode(dlight)
        dlnp.setHpr(35, -50, 0)
        self.base.render.setLight(dlnp)

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------

    def setup_environment(self):
        self._make_ground()
        self.house = HouseBuilder(self.base)
        self.house.build()
        print("LevelManager: House test layout ready.")

    # Interface para o sistema de guardas

    def is_position_lit(self, pos) -> bool:
        return True

    def get_active_light_nodes(self) -> list:
        return []

    def get_nav_mesh(self):
        return self.base.render

    def try_player_action(self, player_pos):
        return self.house.try_toggle_nearest_door(player_pos, Cfg.INTERACT_RANGE)

    def set_player_airborne(self, is_airborne):
        self.house.set_jump_windows_active(not is_airborne)

    def set_player_crouching(self, is_crouching):
        self.house.set_crouch_passages_active(not is_crouching)

    def get_player_spawn(self):
        return self.house.get_player_spawn()

    def _make_ground(self):
        cm = CardMaker("ground")
        cm.setFrame(-150, 150, -150, 150)
        ground = self.base.render.attachNewNode(cm.generate())
        ground.setP(-90)
        ground.setColor(0.18, 0.24, 0.18, 1)
        ground.setTwoSided(True)

        cn = CollisionNode("ground_coll")
        cn.addSolid(CollisionPlane(Plane(Vec3(0, 0, 1), (0, 0, 0))))
        self.base.render.attachNewNode(cn)
