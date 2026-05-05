from panda3d.core import (
    AmbientLight, DirectionalLight, PointLight, Vec3, Vec4,
    CardMaker, CollisionPlane, Plane, CollisionNode,
    CollisionBox, Point3, NodePath, Shader,
    PTA_LVecBase3f, PTA_int, LVecBase3f,
)

import config as Cfg
from core.house_builder import HouseBuilder


# Hard-coded cap matches MAX_POINT_LIGHTS in shaders/scene.frag.
SHADER_MAX_POINT_LIGHTS = 16


class LevelManager:
    def __init__(self, base):
        self.base = base
        self._scene_shader = None
        self._point_lights: list[NodePath] = []   # tracked PointLight nodes
        self._scene_pt_pos    = PTA_LVecBase3f.empty_array(SHADER_MAX_POINT_LIGHTS)
        self._scene_pt_color  = PTA_LVecBase3f.empty_array(SHADER_MAX_POINT_LIGHTS)
        self._scene_pt_atten  = PTA_LVecBase3f.empty_array(SHADER_MAX_POINT_LIGHTS)

        self.setup_lights()
        self.setup_environment()
        self.setup_scene_shader()

    # ------------------------------------------------------------------
    # Lights
    # ------------------------------------------------------------------

    def setup_lights(self):
        # Night-mansion mood: very low blue-ish ambient, cool dim moonlight,
        # warm candle point lights for visual contrast.
        alight = AmbientLight('ambient_light')
        alight.setColor(Vec4(0.06, 0.07, 0.10, 1))
        self._ambient_np = self.base.render.attachNewNode(alight)
        self.base.render.setLight(self._ambient_np)

        # Moonlight: cool, slightly dim, pitched from above-east.
        dlight = DirectionalLight('moonlight')
        dlight.setColor(Vec4(0.45, 0.55, 0.75, 1))
        self._dir_light_np = self.base.render.attachNewNode(dlight)
        self._dir_light_np.setHpr(45, -55, 0)
        self.base.render.setLight(self._dir_light_np)

        # Candle point lights. Quadratic-dominated attenuation gives a
        # tight, falloff-driven pool of warm light around each candle.
        candle_color = (1.40, 0.80, 0.32)   # >1 lets it punch through ambient
        candle_atten = (1.0, 0.10, 0.18)    # const, linear, quad
        candle_positions = (
            ( 13,  13, 3.2),
            (-13,  13, 3.2),
            ( 13, -13, 3.2),
            (-13, -13, 3.2),
            (  0,   0, 3.5),                # central chandelier
        )
        for i, pos in enumerate(candle_positions):
            self._add_point_light(
                name=f"candle_{i}",
                pos=Vec3(*pos),
                color=candle_color,
                attenuation=candle_atten,
            )

    def _add_point_light(self, name, pos, color, attenuation):
        plight = PointLight(name)
        plight.setColor(Vec4(*color, 1.0))
        plight.setAttenuation(Vec3(*attenuation))
        np = self.base.render.attachNewNode(plight)
        np.setPos(pos)
        self.base.render.setLight(np)
        self._point_lights.append(np)
        return np

    # ------------------------------------------------------------------
    # Scene shader
    # ------------------------------------------------------------------

    def setup_scene_shader(self):
        """
        Apply the custom multi-light shader to render. Player slime
        nodes carry their own setShader, so they override this on
        their own subtree without affecting level/item geometry.
        """
        shader = Shader.load(
            Shader.SL_GLSL,
            vertex="shaders/scene.vert",
            fragment="shaders/scene.frag",
        )
        self._scene_shader = shader
        self.base.render.setShader(shader)

        # Static uniforms — set once.
        self.base.render.setShaderInput("ambient_color", Vec3(0.06, 0.07, 0.10))

        moonlight_dir = self._compute_dir_light_world_dir()
        moonlight_col = Vec3(0.45, 0.55, 0.75)
        self.base.render.setShaderInput("dir_light_dir",   moonlight_dir)
        self.base.render.setShaderInput("dir_light_color", moonlight_col)

        # Bind the PTA arrays once; we update entries in place each frame.
        self.base.render.setShaderInput("point_pos",   self._scene_pt_pos)
        self.base.render.setShaderInput("point_color", self._scene_pt_color)
        self.base.render.setShaderInput("point_atten", self._scene_pt_atten)

        self.base.taskMgr.add(self._scene_lighting_task, "scene_lighting")

    def _compute_dir_light_world_dir(self) -> Vec3:
        """Return the world-space direction TO the directional light."""
        # DirectionalLight in Panda points along its local -Y after HPR.
        # The vector "from light origin towards the world" is the inverse.
        forward_local = Vec3(0, 1, 0)   # we want direction TO the light
        v = self._dir_light_np.getQuat(self.base.render).xform(forward_local)
        v.normalize()
        return v

    def _scene_lighting_task(self, task):
        # Pull every PointLight currently parented under render. Cheap at
        # our scale (handful of lights) and avoids manual registration when
        # other systems (e.g. Player.eye_light) attach lights elsewhere.
        all_pt_nps = self.base.render.findAllMatches("**/+PointLight")

        cam_pos = self.base.camera.getPos(self.base.render)
        self.base.render.setShaderInput("camera_world_pos",
                                        Vec3(cam_pos.x, cam_pos.y, cam_pos.z))

        count = min(all_pt_nps.getNumPaths(), SHADER_MAX_POINT_LIGHTS)
        for i in range(count):
            np    = all_pt_nps.getPath(i)
            light = np.node()
            wpos  = np.getPos(self.base.render)
            color = light.getColor()
            atten = light.getAttenuation()
            self._scene_pt_pos  .setElement(i, LVecBase3f(wpos.x,  wpos.y,  wpos.z))
            self._scene_pt_color.setElement(i, LVecBase3f(color.x, color.y, color.z))
            self._scene_pt_atten.setElement(i, LVecBase3f(atten.x, atten.y, atten.z))

        self.base.render.setShaderInput("num_point_lights", count)
        return task.cont

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------

    def setup_environment(self):
        self._make_ground()
        self.house = HouseBuilder(self.base)
        self.house.build()
        print("LevelManager: House test layout ready.")

    # ── Light query stub kept for future systems ──────────────────────────

    def is_position_lit(self, pos) -> bool:
        return True

    def get_active_light_nodes(self) -> list:
        return list(self._point_lights) + [self._dir_light_np]

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
