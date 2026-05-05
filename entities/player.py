import math
from enum import Enum, auto
from panda3d.core import (
    CollisionSphere, CollisionNode, NodePath,
    CollisionSegment, CollisionHandlerQueue, CollisionTraverser,
    BitMask32, Point3, TransparencyAttrib, Shader, Vec3, Vec4, PointLight,
)
import config as Cfg


class PlayerState(Enum):
    IDLE   = auto()
    WALK   = auto()
    CROUCH = auto()
    GRAB   = auto()


class Player:
    """
    Câmera e controles no estilo do Roaming Ralph (sample do Panda3D).

    Diferenças em relação a uma câmera orbital convencional:
      - A câmera NÃO é filha do personagem. Ela permanece no mundo e
        "arrasta" atrás dele dentro de uma faixa elástica de distância.
      - Quando o personagem se afasta demais, a câmera é puxada na
        direção dele; quando ele se aproxima demais, é empurrada para fora.
      - A câmera olha sempre para um nó "floater", posicionado acima da
        cabeça do personagem — isso evita olhar para o chão quando
        o personagem está abaixo da câmera.
      - Controles puramente via teclado: A/D giram o personagem e
        W/S deslocam para frente/trás no eixo local dele.
    """

    def __init__(self, base):
        self.base = base

        # ── Personagem ──────────────────────────────────────────────────
        self.player_node = self.base.render.attachNewNode("player_node")
        spawn = Point3(0, 0, Cfg.GROUND_LEVEL)
        if hasattr(self.base, "level_manager"):
            spawn = self.base.level_manager.get_player_spawn()
            spawn.setZ(Cfg.GROUND_LEVEL)
        self.player_node.setPos(spawn)

        self._build_slime()

        # ── Floater: alvo da câmera, sempre acima da cabeça do player ──
        self.floater = self.base.render.attachNewNode("floater")

        # ── Câmera começa atrás do personagem ───────────────────────────
        _init_pitch = math.radians(Cfg.CAM_PITCH_DEFAULT)
        self.base.camera.setPos(
            self.player_node.getX(),
            self.player_node.getY() - Cfg.CAM_DIST_MAX * math.cos(_init_pitch),
            self.player_node.getZ() + Cfg.CAM_DIST_MAX * math.sin(_init_pitch),
        )
        self.base.camera.lookAt(self.player_node)

        self.setup_collision()
        self.setup_cam_collision()

        self.body_scale              = Vec3(1.3, 1.3, 1.3)
        self.growth_scale            = 1.0   # cresce ao pegar itens
        self.cam_dist_current        = Cfg.CAM_DIST_MAX
        self.cam_pitch               = Cfg.CAM_PITCH_DEFAULT
        self.cam_pitch_adj           = 0.0
        # Yaw stored explicitly (degrees, world-space). 0 = camera south of
        # player looking north. Decoupling from camera position prevents
        # dolly-shrink from shrinking orbit radius mid-rotation.
        self.cam_yaw                 = 0.0
        self.state                   = PlayerState.IDLE
        self.crouch_transition_timer = 0.0
        self.vel_z                   = 0.0
        self.is_grounded             = True
        self.land_squash_timer       = 0.0
        # 0=inativo; 1=t1_in 2=t2_in 3=hold 4=t2_out 5=t1_out
        self.grab_phase              = 0
        self.grab_phase_timer        = 0.0
        self.is_camouflaged          = False
        self.camo_active_timer       = 0.0
        self.camo_cooldown_timer     = 0.0
        # Acumulador para osciladores procedurais (idle/walk/crouch-walk).
        # Avança em _update_state e zera ao aterrissar para sincronizar o
        # bounce do walk com o instante do pouso.
        self.anim_time               = 0.0

        # ── Entrada (teclado apenas) ────────────────────────────────────
        self.key_map = {
            "forward": False, "backward": False,
            "left":    False, "right":    False,
            "crouch":  False,
        }

        bindings = [
            ("w",           "forward"),  ("control-w",  "forward"),  ("shift-w",  "forward"),
            ("arrow_up",    "forward"),
            ("s",           "backward"), ("control-s",  "backward"), ("shift-s",  "backward"),
            ("arrow_down",  "backward"),
            ("a",           "left"),     ("control-a",  "left"),     ("shift-a",  "left"),
            ("arrow_left",  "left"),
            ("d",           "right"),    ("control-d",  "right"),    ("shift-d",  "right"),
            ("arrow_right", "right"),
            ("lshift",      "crouch"),
        ]
        for key, action in bindings:
            self.base.accept(key,         self.update_key_map, [action, True])
            self.base.accept(key + "-up", self.update_key_map, [action, False])

        self.base.accept("e",      self.toggle_camouflage)
        self.base.accept("f",      self.try_action)
        self.base.accept("space",  self.do_jump)
        self.base.accept("mouse1", self.do_primary_action)
        self.base.accept("mouse1-up", self.release_primary_action)

        self.base.taskMgr.add(self.control_task, "control_task")

    # ── Propriedade dinâmica de nível do chão ────────────────────────────
    @property
    def _ground_z(self):
        """Z mínimo do player_node; cresce junto com growth_scale."""
        return Cfg.GROUND_LEVEL * self.growth_scale

    # ── Configuração de colisão ──────────────────────────────────────────
    def setup_collision(self):
        coll_node = CollisionNode("player_coll")
        coll_node.addSolid(CollisionSphere(0, 0, 0, Cfg.GROUND_LEVEL))
        # into_mask = 0: a esfera do player nunca é alvo INTO
        coll_node.setIntoCollideMask(BitMask32.allOff())
        self.coll_np = self.player_node.attachNewNode(coll_node)
        self.base.pusher.addCollider(self.coll_np, self.player_node)
        self.base.cTrav.addCollider(self.coll_np, self.base.pusher)

    def setup_cam_collision(self):
        """Traverser exclusivo para raycast câmera→player (não interfere no pusher)."""
        self.cam_trav  = CollisionTraverser()
        self.cam_queue = CollisionHandlerQueue()

        self.cam_seg_solid = CollisionSegment(0, 0, 0, 0, -1, 0)

        seg_node = CollisionNode("cam_seg")
        seg_node.addSolid(self.cam_seg_solid)
        seg_node.setFromCollideMask(BitMask32.bit(1))
        seg_node.setIntoCollideMask(BitMask32.allOff())

        self.cam_seg_np = self.base.render.attachNewNode(seg_node)
        self.cam_trav.addCollider(self.cam_seg_np, self.cam_queue)

    def _build_slime(self):
        """Carrega os modelos do personagem e aplica o shader GLSL."""
        shader = Shader.load(
            Shader.SL_GLSL,
            vertex="shaders/slime.vert",
            fragment="shaders/slime.frag",
        )
        shader_inputs = {
            "light_color":    Vec4(0.7, 0.7, 0.7, 1),
            "ambient_color":  Vec4(0.3, 0.3, 0.3, 1),
            "rim_color":      Vec4(0.15, 0.45, 1.0, 1),
            "rim_power":      3.5,
            "time":           0.0,
            "light_dir_view": Vec3(0, 0, 1),
        }

        def _load_centered(path, name):
            wrap = self.player_node.attachNewNode(name)
            m = self.base.loader.loadModel(path)
            m.reparentTo(wrap)
            m.setP(90)
            m.setH(180)
            mn, mx = m.getTightBounds()
            cx = (mn.x + mx.x) * 0.5
            cy = (mn.y + mx.y) * 0.5
            m.setPos(-cx, -cy, -mn.z - 0.75)
            wrap.setShader(shader)
            for k, v in shader_inputs.items():
                wrap.setShaderInput(k, v)
            return wrap

        self.model_normal    = _load_centered("assets/player-normal.egg",    "model_normal")
        self.model_crunch_t1 = _load_centered("assets/player-crunch-t1.egg", "model_crunch_t1")
        self.model_crunch    = _load_centered("assets/player-crunch.egg",    "model_crunch")
        self.model_crunch_t1.hide()
        self.model_crunch.hide()

        self.model_grab_t1 = _load_centered("assets/player-grab-t1.egg", "model_grab_t1")
        self.model_grab_t2 = _load_centered("assets/player-grab-t2.egg", "model_grab_t2")
        self.model_grab    = _load_centered("assets/player-grab.egg",    "model_grab")
        self.model_grab_t1.hide()
        self.model_grab_t2.hide()
        self.model_grab.hide()

        self.model = self.model_normal

        eye_light = PointLight("eye_light")
        eye_light.setColor((0.9, 0.70, 0.10, 1))
        eye_light.setAttenuation((1, 0, 0.05))
        self.eye_light_np = self.player_node.attachNewNode(eye_light)
        self.eye_light_np.setPos(0, 0.8, 0.5)
        self.base.render.setLight(self.eye_light_np)

    def _update_active_model(self):
        """Troca o modelo visível ao mudar de estado; transfere camuflagem."""
        if self.grab_phase in (1, 5):
            target = self.model_grab_t1
        elif self.grab_phase in (2, 4):
            target = self.model_grab_t2
        elif self.grab_phase == 3:
            target = self.model_grab
        elif self.crouch_transition_timer > 0:
            target = self.model_crunch_t1
        elif self.state == PlayerState.CROUCH:
            target = self.model_crunch
        else:
            target = self.model_normal
        if target is self.model:
            return
        old = self.model
        old.hide()
        target.show()
        self.model = target
        if self.is_camouflaged:
            old.clearColorScale()
            old.clearTransparency()
            self.model.setTransparency(TransparencyAttrib.M_alpha)
            self.model.setColorScale(0.4, 0.9, 1.0, Cfg.CAMO_ALPHA)
        self.model.setScale(self.body_scale * self.growth_scale)

    def _apply_squish(self, dt):
        """Lerp linear da escala do corpo com base no estado e física de pulo.

        Targets dos estados grounded usam osciladores senoidais sobre
        ``self.anim_time`` para dar vida (respiração, bounce de passada,
        ondulação rastejante). A física do pulo e o lerp permanecem
        inalterados — o SQUISH_SPEED suaviza qualquer transição.
        """
        if self.land_squash_timer > 0:
            target = Vec3(1.55, 1.55, 0.80)
        elif not self.is_grounded and self.vel_z > 0:
            target = Vec3(0.90, 0.90, 1.55)
        elif not self.is_grounded:
            target = Vec3(0.95, 0.95, 1.30)
        else:
            t = self.anim_time
            is_moving = self.key_map["forward"] or self.key_map["backward"]

            if self.state == PlayerState.WALK:
                # Bounce de passada: abs(sin) gera 2 picos por ciclo,
                # imitando os dois "saltos" do slime se impulsionando.
                bounce = abs(math.sin(t * Cfg.ANIM_WALK_FREQ))
                base_xy = 1.35 - 0.08 * bounce      # estreita quando alto
                base_z  = 1.25 + 0.12 * bounce      # sobe a cada passo
                # Ondulação lateral: alterna squeeze entre X e Y.
                wobble = 0.03 * math.sin(t * Cfg.ANIM_WALK_FREQ)
                target = Vec3(base_xy + wobble, base_xy - wobble, base_z)

            elif self.state == PlayerState.CROUCH:
                if is_moving:
                    # Rastejando: shape achatado com forte ondulação
                    # horizontal alternada entre X e Y.
                    crawl = math.sin(t * Cfg.ANIM_CRAWL_FREQ)
                    target = Vec3(
                        1.40 + 0.10 * crawl,
                        1.40 - 0.10 * crawl,
                        1.00 + 0.06 * abs(crawl),
                    )
                else:
                    # Agachado parado: flat e estático.
                    target = Vec3(1.38, 1.38, 1.00)

            elif self.state == PlayerState.IDLE:
                # Respiração: largo↔baixo / estreito↔alto, ~5s por ciclo.
                breath = math.sin(t * Cfg.ANIM_IDLE_FREQ)
                target = Vec3(1.30 + 0.04 * breath,
                              1.30 + 0.04 * breath,
                              1.30 - 0.04 * breath)

            else:  # GRAB
                target = Vec3(1.30, 1.30, 1.30)
        step = Cfg.SQUISH_SPEED * dt
        for i in range(3):
            diff = target[i] - self.body_scale[i]
            if abs(diff) <= step:
                self.body_scale[i] = target[i]
            else:
                self.body_scale[i] += math.copysign(step, diff)
        # growth_scale é aplicado multiplicando body_scale para não perder o squish
        self.model.setScale(self.body_scale * self.growth_scale)

    def attach_camera(self, camera):
        """Reposiciona a câmera atrás do personagem (saída do free-cam)."""
        pitch_rad = math.radians(self.cam_pitch)
        camera.setPos(
            self.player_node.getX(),
            self.player_node.getY() - Cfg.CAM_DIST_MAX * math.cos(pitch_rad),
            self.player_node.getZ() + Cfg.CAM_DIST_MAX * math.sin(pitch_rad),
        )
        camera.lookAt(self.player_node)

    def update_key_map(self, key, state):
        self.key_map[key] = state

    def do_grab(self):
        if getattr(self.base, "game_paused", True):
            return
        if self.grab_phase != 0:
            return
        self.grab_phase       = 1
        self.grab_phase_timer = Cfg.GRAB_T1_TIME

    def do_primary_action(self):
        if getattr(self.base, "game_paused", True):
            return
        if hasattr(self.base, "item_manager") and self.base.item_manager.is_mirror_held():
            return
        if hasattr(self.base, "item_manager") and self.base.item_manager.try_pickup_mirror(
            self.player_node.getPos(),
            self.player_node,
        ):
            return
        if self.try_action():
            return
        self.do_grab()

    def release_primary_action(self):
        if getattr(self.base, "game_paused", True):
            return
        if hasattr(self.base, "item_manager"):
            self.base.item_manager.drop_mirror(self.player_node.getPos())

    def do_jump(self):
        if getattr(self.base, "game_paused", True):
            return
        if self.is_grounded and self.state != PlayerState.CROUCH and self.grab_phase == 0:
            self.vel_z       = Cfg.JUMP_SPEED
            self.is_grounded = False
            if hasattr(self.base, "level_manager"):
                self.base.level_manager.set_player_airborne(True)

    def try_action(self):
        if getattr(self.base, "game_paused", True):
            return False
        if hasattr(self.base, "level_manager"):
            return self.base.level_manager.try_player_action(self.player_node.getPos())
        return False

    # ── Crescimento ──────────────────────────────────────────────────────
    def apply_growth(self, value):
        """Aumenta a escala do player proporcionalmente ao valor do item coletado."""
        self.growth_scale = min(
            self.growth_scale + value * Cfg.GROWTH_PER_VALUE_UNIT,
            Cfg.MAX_GROWTH_SCALE,
        )
        self._update_collision_radius()
        # Levanta o player imediatamente para o novo nível do chão
        if self.player_node.getZ() < self._ground_z:
            self.player_node.setZ(self._ground_z)

    def _update_collision_radius(self):
        """Recalcula o raio da CollisionSphere após crescimento."""
        coll_node = self.coll_np.node()
        coll_node.clearSolids()
        coll_node.addSolid(CollisionSphere(0, 0, 0, self._ground_z))

    def _try_grab_item(self):
        """Verifica e coleta o item mais próximo dentro do alcance."""
        if not hasattr(self.base, "item_manager"):
            return
        player_pos = self.player_node.getPos()
        if self.base.item_manager.is_mirror_held():
            return
        value = self.base.item_manager.try_grab_nearest(player_pos)
        if value is not None:
            self.apply_growth(value)

    # ── Loop de atualização ──────────────────────────────────────────────
    def _move_local_y(self, distance):
        if abs(distance) < 1e-6:
            return

        max_step = 0.35
        steps = max(1, int(math.ceil(abs(distance) / max_step)))
        step = distance / steps

        for _ in range(steps):
            self.player_node.setY(self.player_node, step)
            self.base.cTrav.traverse(self.base.render)

    def _move_world_xy(self, dx, dy):
        """Translate the player along world X/Y with collision substeps."""
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return
        max_step = 0.35
        dist = math.hypot(dx, dy)
        steps = max(1, int(math.ceil(dist / max_step)))
        sx = dx / steps
        sy = dy / steps
        for _ in range(steps):
            p = self.player_node.getPos()
            self.player_node.setPos(p.x + sx, p.y + sy, p.z)
            self.base.cTrav.traverse(self.base.render)

    def _sync_environment_interactions(self):
        if hasattr(self.base, "level_manager"):
            self.base.level_manager.set_player_airborne(not self.is_grounded)
            self.base.level_manager.set_player_crouching(
                self.state == PlayerState.CROUCH
            )

    def control_task(self, task):
        if getattr(self.base, "game_paused", True):
            return task.cont

        dt = self.base.clock.getDt()

        self._update_state(dt)
        self._sync_environment_interactions()

        # Atualiza inputs do shader: wobble time + direção da luz em view space
        ld = Vec3(0.5, -0.5, 1.0).normalized()
        lv = self.base.render.getRelativeVector(self.base.camera, ld)
        ft = self.base.clock.getFrameTime()
        for m in (self.model_normal, self.model_crunch_t1, self.model_crunch,
                  self.model_grab_t1, self.model_grab_t2, self.model_grab):
            m.setShaderInput("light_dir_view", lv)
            m.setShaderInput("time", ft)

        # Velocidade inversamente proporcional ao tamanho
        _base_speed = Cfg.WALK_SPEED / (self.growth_scale ** Cfg.SPEED_SCALE_EXPONENT)
        speed = _base_speed * (
            Cfg.CROUCH_SPEED_MULT if self.state == PlayerState.CROUCH else 1.0
        )

        # ── Camera-relative WASD: input axes mapped onto camera yaw. ──
        ix = (1.0 if self.key_map["right"] else 0.0) - (1.0 if self.key_map["left"] else 0.0)
        iy = (1.0 if self.key_map["forward"] else 0.0) - (1.0 if self.key_map["backward"] else 0.0)
        mag = math.hypot(ix, iy)
        if mag > 1e-4:
            ix /= mag
            iy /= mag
            yaw_rad = math.radians(self.cam_yaw)
            cos_y = math.cos(yaw_rad)
            sin_y = math.sin(yaw_rad)
            # Camera-forward = -n (toward pivot) = (sin, cos) in world XY.
            # Camera-right = perpendicular CW from forward = (cos, -sin).
            fwd_x,   fwd_y   =  sin_y,  cos_y
            right_x, right_y =  cos_y, -sin_y
            move_x = ix * right_x + iy * fwd_x
            move_y = ix * right_y + iy * fwd_y
            self._move_world_xy(move_x * speed * dt, move_y * speed * dt)

            # Player smoothly rotates to face movement direction.
            target_h = math.degrees(math.atan2(-move_x, move_y))
            current_h = self.player_node.getH()
            diff = ((target_h - current_h + 540.0) % 360.0) - 180.0
            step = max(-Cfg.PLAYER_TURN_LERP * dt,
                       min(Cfg.PLAYER_TURN_LERP * dt, diff))
            self.player_node.setH(current_h + step)

        # ── Física vertical (gravidade + pulo) ───────────────────────
        gz = self._ground_z
        if not self.is_grounded:
            self.vel_z -= Cfg.GRAVITY * dt
            self.player_node.setZ(self.player_node.getZ() + self.vel_z * dt)
            if self.player_node.getZ() <= gz:
                if self.vel_z < -3.0:
                    self.land_squash_timer = 0.18
                self.player_node.setZ(gz)
                self.vel_z       = 0.0
                self.is_grounded = True
                self._sync_environment_interactions()
                # Sincroniza o ciclo do walk com o pouso: o próximo
                # passo nasce no instante zero do bounce, evitando
                # entrar no walk no meio de um pico aleatório.
                self.anim_time   = 0.0

        # ── Câmera: rotação manual via mouse + dolly por obstáculos ───
        if not getattr(self.base, "free_cam_active", False):
            self._handle_mouse()
            self._update_camera_ralph(dt)

        return task.cont

    # ── Máquina de estados ───────────────────────────────────────────────
    def _update_state(self, dt):
        # Avança o relógio dos osciladores procedurais (idle/walk/crouch).
        # Como _update_state só roda quando o jogo NÃO está pausado
        # (control_task faz o early-return), não precisa de gate adicional.
        self.anim_time += dt

        # Tick do grab — avança fases da animação
        if self.grab_phase != 0:
            self.grab_phase_timer -= dt
            if self.grab_phase_timer <= 0:
                _phase_durations = {
                    1: Cfg.GRAB_T1_TIME,
                    2: Cfg.GRAB_T2_TIME,
                    3: Cfg.GRAB_HOLD_TIME,
                    4: Cfg.GRAB_T2_TIME,
                    5: Cfg.GRAB_T1_TIME,
                }
                next_phase = self.grab_phase + 1
                if next_phase > 5:
                    self.grab_phase       = 0
                    self.grab_phase_timer = 0.0
                else:
                    self.grab_phase       = next_phase
                    self.grab_phase_timer = _phase_durations[next_phase]
                    # Coleta item no pico da animação de grab
                    if next_phase == 3:
                        self._try_grab_item()

        is_moving = self.key_map["forward"] or self.key_map["backward"]
        is_crouching = self.key_map["crouch"]
        if hasattr(self.base, "item_manager") and self.base.item_manager.is_mirror_held():
            is_crouching = False

        if self.grab_phase != 0:
            new_state = PlayerState.GRAB
        elif is_crouching:
            new_state = PlayerState.CROUCH
        elif is_moving:
            new_state = PlayerState.WALK
        else:
            new_state = PlayerState.IDLE

        was_crouch = (self.state == PlayerState.CROUCH)
        now_crouch = (new_state == PlayerState.CROUCH)
        if was_crouch != now_crouch:
            self.crouch_transition_timer = Cfg.CROUCH_TRANSITION_TIME
        elif self.crouch_transition_timer > 0:
            self.crouch_transition_timer = max(0.0, self.crouch_transition_timer - dt)

        self.state = new_state
        self._update_active_model()

        target_adj = Cfg.CAM_PITCH_CROUCH if is_crouching else 0.0
        diff = target_adj - self.cam_pitch_adj
        step = Cfg.CAM_PITCH_SPEED * dt
        if abs(diff) <= step:
            self.cam_pitch_adj = target_adj
        else:
            self.cam_pitch_adj += math.copysign(step, diff)

        self._apply_squish(dt)

        if self.land_squash_timer > 0:
            self.land_squash_timer = max(0.0, self.land_squash_timer - dt)

        if self.is_camouflaged:
            self.camo_active_timer -= dt
            if self.camo_active_timer <= 0.0:
                self._deactivate_camouflage()
        elif self.camo_cooldown_timer > 0.0:
            self.camo_cooldown_timer -= dt

    # ── Camuflagem ───────────────────────────────────────────────────────
    def toggle_camouflage(self):
        if getattr(self.base, "game_paused", True):
            return
        if self.is_camouflaged or self.camo_cooldown_timer > 0.0:
            return

        self.is_camouflaged    = True
        self.camo_active_timer = Cfg.CAMO_DURATION
        self.model.setTransparency(TransparencyAttrib.M_alpha)
        self.model.setColorScale(0.4, 0.9, 1.0, Cfg.CAMO_ALPHA)

    def _deactivate_camouflage(self):
        self.is_camouflaged      = False
        self.camo_active_timer   = 0.0
        self.camo_cooldown_timer = Cfg.CAMO_COOLDOWN
        self.model.clearColorScale()
        self.model.clearTransparency()

    # ── Rotação manual da câmera (mouse) ─────────────────────────────────
    def _handle_mouse(self):
        win = self.base.win
        if not win or not win.getProperties().getForeground():
            self._mouse_primed = False
            return

        cx = win.getXSize() // 2
        cy = win.getYSize() // 2

        # First frame after pause/focus: just recenter, ignore stale delta.
        if not getattr(self, "_mouse_primed", False):
            win.movePointer(0, cx, cy)
            self._mouse_primed = True
            return

        md = win.getPointer(0)
        dx = md.getX() - cx
        dy = md.getY() - cy
        if dx == 0 and dy == 0:
            return

        # Reject implausible jumps (window resize, cursor warp glitches).
        max_jump = max(win.getXSize(), win.getYSize()) * 0.4
        if abs(dx) > max_jump or abs(dy) > max_jump:
            win.movePointer(0, cx, cy)
            return

        win.movePointer(0, cx, cy)
        if self.base.game_paused:
            return
        self._orbit_camera(-dx * Cfg.MOUSE_SENS)
        self._pitch_camera(dy * Cfg.MOUSE_SENS)

    def _pitch_camera(self, delta_deg):
        self.cam_pitch = max(Cfg.CAM_PITCH_MIN,
                             min(Cfg.CAM_PITCH_MAX, self.cam_pitch + delta_deg))

    def _orbit_camera(self, angle_deg):
        # Pure yaw accumulation. Position recomputed in _update_camera_ralph.
        self.cam_yaw = (self.cam_yaw + angle_deg) % 360.0

    def _query_cam_dist(self, pivot, ideal_cam_pos):
        """Spring-arm: ray from pivot (player head) to ideal camera pos."""
        self.cam_seg_solid.setPointA(pivot)
        self.cam_seg_solid.setPointB(ideal_cam_pos)

        self.cam_queue.clearEntries()
        self.cam_trav.traverse(self.base.render)

        if self.cam_queue.getNumEntries() == 0:
            return Cfg.CAM_DIST_MAX

        self.cam_queue.sortEntries()
        hit_pos = self.cam_queue.getEntry(0).getSurfacePoint(self.base.render)
        dist    = (hit_pos - pivot).length()
        return max(Cfg.CAM_DIST_MIN, dist - 0.4)

    def _update_camera_ralph(self, dt):
        player_pos = self.player_node.getPos()

        # Optional yaw-follow (off by default; mouse drives yaw).
        if Cfg.CAM_FOLLOW_FACTOR > 0.0 and any((
            self.key_map["forward"], self.key_map["backward"],
            self.key_map["left"],    self.key_map["right"],
        )):
            target_yaw = self.player_node.getH() % 360.0
            diff = ((target_yaw - self.cam_yaw + 540.0) % 360.0) - 180.0
            self.cam_yaw = (self.cam_yaw + diff * Cfg.CAM_FOLLOW_FACTOR * dt) % 360.0

        # Pivot at player head height — orbit center for a true 3rd-person rig.
        pivot = Point3(
            player_pos.x,
            player_pos.y,
            player_pos.z + Cfg.CAM_PIVOT_Z * self.growth_scale,
        )

        yaw_rad = math.radians(self.cam_yaw)
        nx = -math.sin(yaw_rad)
        ny = -math.cos(yaw_rad)

        total_pitch = max(Cfg.CAM_PITCH_MIN,
                          min(Cfg.CAM_PITCH_MAX, self.cam_pitch + self.cam_pitch_adj))
        pitch_rad = math.radians(total_pitch)
        cos_p = math.cos(pitch_rad)
        sin_p = math.sin(pitch_rad)

        ideal_pos = Point3(
            pivot.x + nx * Cfg.CAM_DIST_MAX * cos_p,
            pivot.y + ny * Cfg.CAM_DIST_MAX * cos_p,
            pivot.z + Cfg.CAM_DIST_MAX * sin_p,
        )

        safe_dist = self._query_cam_dist(pivot, ideal_pos)

        # Snap inward instantly, ease outward slowly to avoid pop-in.
        if safe_dist < self.cam_dist_current:
            self.cam_dist_current = safe_dist
        else:
            self.cam_dist_current = min(
                self.cam_dist_current + Cfg.CAM_ZOOM_SPEED * dt,
                safe_dist,
            )

        self.base.camera.setPos(
            pivot.x + nx * self.cam_dist_current * cos_p,
            pivot.y + ny * self.cam_dist_current * cos_p,
            pivot.z + self.cam_dist_current * sin_p,
        )

        # Aim slightly forward of pivot so the player is framed lower-center.
        self.floater.setPos(pivot)
        self.base.camera.lookAt(self.floater)

    # ── Interface para o sistema de guardas ───────────────────────────────

    def get_position(self) -> Point3:
        return Point3(self.player_node.getPos())

    def get_size_factor(self) -> float:
        return self.growth_scale

    def get_is_sprinting(self) -> bool:
        return False  # sprint não implementado ainda

    def get_is_crouching(self) -> bool:
        return self.state == PlayerState.CROUCH

    def get_node_path(self):
        return self.player_node

    def is_visible(self) -> bool:
        return not self.is_camouflaged
