from panda3d.core import (
    AmbientLight, DirectionalLight, PointLight, Vec3, Vec4,
    CardMaker, CollisionPlane, Plane, CollisionNode,
    CollisionBox, Point3, NodePath, Shader, Texture,
    PTA_LVecBase3f, PTA_int, LVecBase3f,
    Fog, CullFaceAttrib,
)

import config as Cfg
from core.house_builder import HouseBuilder
# ShadowPass is retired — raytraced AABB shadows handle directional + point
# lights inside scene.frag.  Keep the import path noted here for history.


# Hard-coded cap matches MAX_POINT_LIGHTS in shaders/scene.frag.
SHADER_MAX_POINT_LIGHTS = 32
SHADER_MAX_AABBS        = 256


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
        self.upload_raytraced_geometry()

    # ------------------------------------------------------------------
    # Lights
    # ------------------------------------------------------------------

    def setup_lights(self):
        daylight = getattr(Cfg, "DAYLIGHT_MODE", False)

        if daylight:
            ambient_rgb = (0.70, 0.72, 0.75)
            sun_rgb     = (1.05, 1.00, 0.92)
            sun_hpr     = (35, -60, 0)
            candle_color = (0.35, 0.22, 0.10)
            candle_atten = (1.0, 0.30, 0.45)
            self.base.setBackgroundColor(0.55, 0.72, 0.92, 1)
        else:
            # Gloomy night: low but readable ambient, cool moonlight, hot torches.
            ambient_rgb = (0.055, 0.065, 0.090)
            sun_rgb     = (0.55, 0.66, 0.92)
            sun_hpr     = self._moon_hpr_from_dir(Cfg.MOON_DIR)
            candle_color = (2.20, 1.20, 0.45)
            candle_atten = (1.0, 0.14, 0.22)
            self.base.setBackgroundColor(0.012, 0.018, 0.040, 1)

        self._ambient_rgb = ambient_rgb
        self._sun_rgb     = sun_rgb

        alight = AmbientLight('ambient_light')
        alight.setColor(Vec4(*ambient_rgb, 1))
        self._ambient_np = self.base.render.attachNewNode(alight)
        self.base.render.setLight(self._ambient_np)

        dlight = DirectionalLight('moonlight')
        dlight.setColor(Vec4(*sun_rgb, 1))
        self._dir_light_np = self.base.render.attachNewNode(dlight)
        self._dir_light_np.setHpr(*sun_hpr)
        self.base.render.setLight(self._dir_light_np)
        if daylight:
            candle_positions = (
                ( 13,  13, 3.2),
                (-13,  13, 3.2),
                ( 13, -13, 3.2),
                (-13, -13, 3.2),
                (  0,   0, 3.5),
            )
            for i, pos in enumerate(candle_positions):
                self._add_point_light(
                    name=f"candle_{i}",
                    pos=Vec3(*pos),
                    color=candle_color,
                    attenuation=candle_atten,
                )

        if not daylight:
            torch_color = (2.40, 1.30, 0.50)
            torch_atten = (1.0, 0.10, 0.16)
            scale = Cfg.HOUSE_LAYOUT_SCALE
            exterior_torches = (
                (-18.0, -20.4 * scale - 0.2, 3.4),
                ( -6.0, -20.4 * scale - 0.2, 3.4),
                (  6.0, -20.4 * scale - 0.2, 3.4),
                ( 18.0, -20.4 * scale - 0.2, 3.4),
                (-26.0 * scale - 0.4, -10.0, 3.4),
                (-26.0 * scale - 0.4,  18.0, 3.4),
                ( 26.0 * scale + 0.4, -10.0, 3.4),
                ( 26.0 * scale + 0.4,  18.0, 3.4),
            )
            for i, pos in enumerate(exterior_torches):
                self._add_point_light(
                    name=f"torch_ext_{i}",
                    pos=Vec3(*pos),
                    color=torch_color,
                    attenuation=torch_atten,
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

        # Default 1x1 white texture so the shader's p3d_Texture0 sampler
        # has something valid to read on geometry that never calls
        # setTexture (otherwise sampling = black on macOS GL Core).
        white = Texture("scene_default_white")
        white.setup2dTexture(1, 1, Texture.T_unsigned_byte, Texture.F_rgb8)
        white.setRamImageAs(b"\xff\xff\xff", "RGB")
        self.base.render.setTexture(white, 0)

        # Static uniforms — set once.
        self.base.render.setShaderInput("ambient_color", Vec3(*self._ambient_rgb))

        if getattr(Cfg, "DAYLIGHT_MODE", False):
            self.base.render.setShaderInput("fog_color", Vec3(0, 0, 0))
            self.base.render.setShaderInput("fog_density", 0.0)
        else:
            self.base.render.setShaderInput("fog_color", Vec3(*Cfg.NIGHT_FOG_COLOR))
            self.base.render.setShaderInput("fog_density", Cfg.NIGHT_FOG_DENSITY)

        moonlight_dir = self._compute_dir_light_world_dir()
        self.base.render.setShaderInput("dir_light_dir",   moonlight_dir)
        self.base.render.setShaderInput("dir_light_color", Vec3(*self._sun_rgb))

        # Bind the PTA arrays once; we update entries in place each frame.
        self.base.render.setShaderInput("point_pos",   self._scene_pt_pos)
        self.base.render.setShaderInput("point_color", self._scene_pt_color)
        self.base.render.setShaderInput("point_atten", self._scene_pt_atten)

        # Raytraced AABB scene — empty until upload_raytraced_geometry runs.
        self._scene_aabb_min = PTA_LVecBase3f.empty_array(SHADER_MAX_AABBS)
        self._scene_aabb_max = PTA_LVecBase3f.empty_array(SHADER_MAX_AABBS)
        self.base.render.setShaderInput("aabb_min",  self._scene_aabb_min)
        self.base.render.setShaderInput("aabb_max",  self._scene_aabb_max)
        self.base.render.setShaderInput("num_aabbs", 0)

        self.base.taskMgr.add(self._scene_lighting_task, "scene_lighting")

    # ------------------------------------------------------------------
    # Raytraced shadow scene upload
    # ------------------------------------------------------------------

    def upload_raytraced_geometry(self):
        """Push the house's static AABB list to the scene shader.

        Walls and door frames generated by HouseBuilder._create_box are
        stamped into self.house.aabbs as ((minx,miny,minz),(maxx,maxy,maxz))
        tuples. We copy them into PTA arrays and bind the count uniform.
        Anything past SHADER_MAX_AABBS is dropped with a console warning so
        the shader's tight loop stays predictable.
        """
        boxes = list(getattr(self.house, "aabbs", ()))
        n = len(boxes)
        if n > SHADER_MAX_AABBS:
            print(f"[RT] {n} AABBs exceed cap {SHADER_MAX_AABBS}; truncating.")
            boxes = boxes[:SHADER_MAX_AABBS]

        for i, (mn, mx) in enumerate(boxes):
            self._scene_aabb_min.setElement(i, LVecBase3f(*mn))
            self._scene_aabb_max.setElement(i, LVecBase3f(*mx))

        self.base.render.setShaderInput("num_aabbs", len(boxes))
        self._aabb_count = len(boxes)
        print(f"[RT] Uploaded {len(boxes)} occluder AABBs for raytraced shadows.")

    def update_aabb(self, index, mn, mx):
        """Hot-swap a single AABB in the raytrace scene (called by Door
        toggles so light can spill through opened doorways live)."""
        if index is None or index < 0 or index >= SHADER_MAX_AABBS:
            return
        self._scene_aabb_min.setElement(index, LVecBase3f(*mn))
        self._scene_aabb_max.setElement(index, LVecBase3f(*mx))

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
        if not getattr(Cfg, "DAYLIGHT_MODE", False):
            self._setup_skydome()
            self._setup_fog()
        print("LevelManager: House test layout ready.")

    def _moon_hpr_from_dir(self, direction):
        """Convert a world-space direction TO the moon into HPR for a
        DirectionalLight (which projects along its local -Y)."""
        import math
        x, y, z = direction
        h = math.degrees(math.atan2(-x, -y))
        flat = math.sqrt(x * x + y * y)
        p = math.degrees(math.atan2(-z, flat))
        return (h, p, 0.0)

    def _setup_skydome(self):
        sphere = self.base.loader.loadModel("models/misc/sphere")
        sphere.reparentTo(self.base.camera)
        sphere.setScale(450.0)
        sphere.setBin("background", 0)
        sphere.setDepthWrite(False)
        sphere.setDepthTest(False)
        sphere.setLightOff(1)
        sphere.setTwoSided(True)
        sphere.setFogOff(1)
        sky_shader = Shader.load(
            Shader.SL_GLSL,
            vertex="shaders/skybox.vert",
            fragment="shaders/skybox.frag",
        )
        sphere.setShader(sky_shader, 100)
        moon_dir = Vec3(*Cfg.MOON_DIR).normalized()
        sphere.setShaderInput("moon_dir",   moon_dir)
        sphere.setShaderInput("moon_size",  Cfg.MOON_DISC_SIZE)
        sphere.setShaderInput("moon_color", Vec3(*Cfg.MOON_COLOR))
        sphere.setShaderInput("nebula_tint", Vec3(*Cfg.NEBULA_TINT))
        sphere.setShaderInput("camera_world_pos", Vec3(0, 0, 0))
        self._skydome = sphere
        self.base.taskMgr.add(self._skydome_task, "skydome_task")

    def _skydome_task(self, task):
        cam_pos = self.base.camera.getPos(self.base.render)
        self._skydome.setShaderInput(
            "camera_world_pos", Vec3(cam_pos.x, cam_pos.y, cam_pos.z)
        )
        self._skydome.setShaderInput("time", self.base.clock.getFrameTime())
        return task.cont

    def _setup_fog(self):
        density = getattr(Cfg, "NIGHT_FOG_DENSITY", 0.0)
        if density <= 0.0:
            return
        fog = Fog("night_fog")
        fog.setColor(*Cfg.NIGHT_FOG_COLOR)
        fog.setExpDensity(density)
        self.base.render.setFog(fog)

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
        if getattr(Cfg, "DAYLIGHT_MODE", False):
            ground.setColor(0.55, 0.68, 0.42, 1)
        else:
            ground.setColor(0.18, 0.24, 0.18, 1)
        ground.setTwoSided(True)

        cn = CollisionNode("ground_coll")
        cn.addSolid(CollisionPlane(Plane(Vec3(0, 0, 1), (0, 0, 0))))
        self.base.render.attachNewNode(cn)
