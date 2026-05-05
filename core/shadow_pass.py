from panda3d.core import (
    Texture, FrameBufferProperties, WindowProperties, GraphicsOutput,
    GraphicsPipe, OrthographicLens, Camera, NodePath, Shader, Vec3,
    LColor, BitMask32,
)


SHADOW_CASTER_BIT = 7   # nodes whose draw mask includes bit 7 cast shadows
SHADOW_MAP_SIZE   = 2048


class ShadowPass:
    """
    Renders the scene from the directional light's POV into a depth-only
    FBO, then exposes (shadow_map, shadow_vp) shader inputs on render so
    scene.frag can do percentage-closer filtered shadow lookups.

    Notes:
      * Camera mask = bit(SHADOW_CASTER_BIT). Default node drawMask is
        allOn, so geometry casts by default. Hide bit 7 on a node to
        exclude it (used for billboard particles, glow halos).
      * vp = render→cam (view) * lens.proj. In Panda's row-major /
        vec*mat convention: clip = world_pt * vp. Panda passes matrices
        transposed for GLSL, so the shader does the standard
        `shadow_vp * vec4(world_pos, 1.0)`.
    """

    def __init__(self, base, light_np, scene_center=(0.0, 0.0, 0.0),
                 film_size=140.0, far_distance=120.0, near=1.0, far=260.0):
        self.base         = base
        self.light_np     = light_np
        self.scene_center = Vec3(*scene_center)
        self.far_distance = far_distance

        self.shadow_tex = Texture("shadow_map")
        self.shadow_tex.setFormat(Texture.F_depth_component24)
        self.shadow_tex.setComponentType(Texture.T_float)
        self.shadow_tex.setMinfilter(Texture.FT_linear)
        self.shadow_tex.setMagfilter(Texture.FT_linear)
        self.shadow_tex.setWrapU(Texture.WM_border_color)
        self.shadow_tex.setWrapV(Texture.WM_border_color)
        self.shadow_tex.setBorderColor(LColor(1, 1, 1, 1))

        fbp = FrameBufferProperties()
        fbp.setRgbColor(False)
        fbp.setRgbaBits(0, 0, 0, 0)
        fbp.setDepthBits(24)

        wp = WindowProperties.size(SHADOW_MAP_SIZE, SHADOW_MAP_SIZE)
        flags = GraphicsPipe.BFRefuseWindow | GraphicsPipe.BFFbPropsOptional
        self.buf = base.graphicsEngine.makeOutput(
            base.pipe, "shadow_buf", -10, fbp, wp,
            flags, base.win.getGsg(), base.win,
        )
        if self.buf is None:
            print("ShadowPass: failed to allocate offscreen buffer.")
            return
        self.buf.setClearColorActive(False)
        self.buf.setClearDepthActive(True)
        self.buf.addRenderTexture(
            self.shadow_tex,
            GraphicsOutput.RTMBindOrCopy,
            GraphicsOutput.RTPDepthStencil,
        )

        self.lens = OrthographicLens()
        self.lens.setFilmSize(film_size, film_size)
        self.lens.setNearFar(near, far)

        cam_node = Camera("shadow_cam", self.lens)
        cam_node.setScene(base.render)
        cam_node.setCameraMask(BitMask32.bit(SHADOW_CASTER_BIT))

        # Override shader for the entire shadow pass.
        shadow_shader = Shader.load(
            Shader.SL_GLSL,
            vertex="shaders/shadow.vert",
            fragment="shaders/shadow.frag",
        )
        ns = NodePath("shadow_init_state")
        ns.setShader(shadow_shader, 1000)
        ns.setColorOff(1000)
        cam_node.setInitialState(ns.getState())

        self.cam_np = base.render.attachNewNode(cam_node)

        dr = self.buf.makeDisplayRegion()
        dr.setCamera(self.cam_np)
        dr.setClearDepthActive(True)

        # Make the shadow map sampler + matrix available to scene shader.
        base.render.setShaderInput("shadow_map", self.shadow_tex)

        self._update()
        base.taskMgr.add(self._update_task, "shadow_pass_task")

    # ------------------------------------------------------------------

    def _update(self):
        # Direction TO the light (Panda DirectionalLight points along -Y
        # before HPR; "to light" is along +Y after HPR).
        light_dir_to = self.light_np.getQuat(self.base.render).xform(Vec3(0, 1, 0))
        light_dir_to.normalize()

        cam_pos = Vec3(
            self.scene_center.x + light_dir_to.x * self.far_distance,
            self.scene_center.y + light_dir_to.y * self.far_distance,
            self.scene_center.z + light_dir_to.z * self.far_distance,
        )
        self.cam_np.setPos(cam_pos)
        self.cam_np.lookAt(self.scene_center)

        view = self.base.render.getMat(self.cam_np)   # world → cam
        proj = self.lens.getProjectionMat()           # cam → clip
        vp   = view * proj                            # vec * mat order
        self.base.render.setShaderInput("shadow_vp", vp)

    def _update_task(self, task):
        self._update()
        return task.cont
