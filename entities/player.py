import math
from enum import Enum, auto
from panda3d.core import (
    CollisionSphere, CollisionNode, NodePath,
    CollisionSegment, CollisionHandlerQueue, CollisionTraverser,
    BitMask32, Point3, TransparencyAttrib, Shader, Vec3, Vec4, PointLight,
)


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

    # ── Câmera ────────────────────────────────────────────────────────────
    CAM_DIST_MAX       = 20.0  # distância máxima antes de puxar a câmera
    CAM_DIST_MIN       = 5.0   # distância mínima antes de empurrar a câmera
    FLOATER_Z_OFFSET   = 2.0   # alvo da câmera (acima da cabeça do player)
    CAM_PITCH_DEFAULT  = 20.0  # ângulo de elevação padrão (graus acima do horizonte)
    CAM_PITCH_MIN      = 5.0   # limite inferior (quase rente ao chão)
    CAM_PITCH_MAX      = 75.0  # limite superior (quase sobre a cabeça)
    CAM_PITCH_CROUCH   = -8.0  # delta de pitch ao agachar
    CAM_PITCH_SPEED    = 60.0  # graus/seg de transição suave do pitch do crouch

    # ── Movimento ────────────────────────────────────────────────────────
    TURN_SPEED       = 200.0  # graus/seg ao virar (A/D)
    WALK_SPEED       = 12.0   # unidades/seg ao andar (W/S)

    # ── Rotação manual da câmera via mouse ───────────────────────────────
    MOUSE_SENS       = 0.25   # graus de órbita por pixel de mouse

    # ── Câmera – dolly por obstáculos ────────────────────────────────────
    CAM_ZOOM_SPEED   = 10.0   # unidades/seg ao recuar após obstáculo sair

    # ── Squish ────────────────────────────────────────────────────────────
    SQUISH_SPEED      = 9.0   # unidades/seg de transição de escala

    # ── Estados ───────────────────────────────────────────────────────────
    CROUCH_SPEED_MULT      = 0.45  # fator de velocidade ao agachar
    CROUCH_TRANSITION_TIME = 0.08  # segundos exibindo o modelo de transição

    # ── Grab ──────────────────────────────────────────────────────────────
    GRAB_T1_TIME   = 0.07  # segundos por frame de transição (t1 entrada/saída)
    GRAB_T2_TIME   = 0.07  # segundos por frame de transição (t2 entrada/saída)
    GRAB_HOLD_TIME = 0.10  # segundos no pico do grab

    # ── Pulo ──────────────────────────────────────────────────────────────
    JUMP_SPEED   = 10.0  # velocidade vertical inicial do pulo (u/s)
    GRAVITY      = 28.0  # aceleração gravitacional (u/s²)
    GROUND_LEVEL = 1.1   # Z mínimo do player_node (raio da CollisionSphere)

    # ── Camuflagem ────────────────────────────────────────────────────────
    CAMO_ALPHA        = 0.22  # opacidade do modelo ao camuflado
    CAMO_DURATION     = 1.0   # segundos de duração da camuflagem
    CAMO_COOLDOWN     = 8.0   # segundos de cooldown após uso

    def __init__(self, base):
        self.base = base

        # ── Personagem ──────────────────────────────────────────────────
        self.player_node = self.base.render.attachNewNode("player_node")
        self.player_node.setPos(0, 0, 1)

        self._build_slime()

        # ── Floater: alvo da câmera, sempre acima da cabeça do player ──
        self.floater = self.base.render.attachNewNode("floater")

        # ── Câmera começa atrás do personagem ───────────────────────────
        _init_pitch = math.radians(self.CAM_PITCH_DEFAULT)
        self.base.camera.setPos(
            self.player_node.getX(),
            self.player_node.getY() - self.CAM_DIST_MAX * math.cos(_init_pitch),
            self.player_node.getZ() + self.CAM_DIST_MAX * math.sin(_init_pitch),
        )
        self.base.camera.lookAt(self.player_node)

        self.setup_collision()
        self.setup_cam_collision()

        self.body_scale      = Vec3(1.3, 1.3, 1.3)
        self.cam_dist_current = self.CAM_DIST_MAX
        self.cam_pitch             = self.CAM_PITCH_DEFAULT
        self.cam_pitch_adj         = 0.0
        self.state                 = PlayerState.IDLE
        self.crouch_transition_timer = 0.0
        self.vel_z            = 0.0   # velocidade vertical atual
        self.is_grounded      = True  # False enquanto estiver no ar
        self.land_squash_timer = 0.0  # segundos de squash de aterrissagem restantes
        # 0=inativo; 1=t1_in 2=t2_in 3=hold 4=t2_out 5=t1_out
        self.grab_phase       = 0
        self.grab_phase_timer = 0.0
        self.is_camouflaged      = False
        self.camo_active_timer   = 0.0  # tempo restante de camuflagem ativa
        self.camo_cooldown_timer = 0.0  # tempo restante de cooldown

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
            self.base.accept(key,          self.update_key_map, [action, True])
            self.base.accept(key + "-up",  self.update_key_map, [action, False])

        self.base.accept("e",      self.toggle_camouflage)
        self.base.accept("space",  self.do_jump)
        self.base.accept("mouse1", self.do_grab)

        self.base.taskMgr.add(self.control_task, "control_task")

    # ── Configuração de colisão ──────────────────────────────────────────
    def setup_collision(self):
        coll_node = CollisionNode("player_coll")
        coll_node.addSolid(CollisionSphere(0, 0, 0, 1.1))
        # into_mask = 0: a esfera do player nunca é alvo de colisão INTO
        # (evita que o raio da câmera bata nela)
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
        seg_node.setFromCollideMask(BitMask32.bit(1))  # bit exclusivo da câmera
        seg_node.setIntoCollideMask(BitMask32.allOff())

        self.cam_seg_np = self.base.render.attachNewNode(seg_node)
        self.cam_trav.addCollider(self.cam_seg_np, self.cam_queue)

    def _build_slime(self):
        """Load both character models and apply the GLSL shader to each."""
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
            # Wrapper node — setScale() on this scales around the geometry centre
            wrap = self.player_node.attachNewNode(name)
            m = self.base.loader.loadModel(path)
            m.reparentTo(wrap)
            # The OBJ is exported with Y-up: height is along egg-Y.
            # P=90 maps egg-Y → Panda3D-Z (up), H=180 faces the model forward.
            m.setP(90)
            m.setH(180)
            # Bounds are now in player_node space (after rotation).
            mn, mx = m.getTightBounds()
            cx = (mn.x + mx.x) * 0.5
            cy = (mn.y + mx.y) * 0.5
            # Place the model bottom at local Z = -sphere_radius so the feet
            # land at world Z = 0 (player_node sits at the sphere centre, ~1.1 up).
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

        # PointLight at eye level
        eye_light = PointLight("eye_light")
        eye_light.setColor((0.9, 0.70, 0.10, 1))
        eye_light.setAttenuation((1, 0, 0.05))
        self.eye_light_np = self.player_node.attachNewNode(eye_light)
        self.eye_light_np.setPos(0, 0.8, 0.5)
        self.base.render.setLight(self.eye_light_np)

    def _update_active_model(self):
        """Swap the visible model wrapper when the state changes; transfer camo."""
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
            self.model.setColorScale(0.4, 0.9, 1.0, self.CAMO_ALPHA)
        self.model.setScale(self.body_scale)

    def _apply_squish(self, dt):
        """Lerp linear da escala do corpo com base no estado atual e física de pulo."""
        if self.land_squash_timer > 0:
            target = Vec3(1.55, 1.55, 0.80)   # aterrissou: largo e achatado
        elif not self.is_grounded and self.vel_z > 0:
            target = Vec3(0.90, 0.90, 1.55)   # subindo: estica verticalmente
        elif not self.is_grounded:
            target = Vec3(0.95, 0.95, 1.30)   # caindo: estica suave
        else:
            targets = {
                PlayerState.IDLE:   Vec3(1.30, 1.30, 1.30),
                PlayerState.WALK:   Vec3(1.35, 1.35, 1.25),
                PlayerState.CROUCH: Vec3(1.30, 1.30, 1.30),
                PlayerState.GRAB:   Vec3(1.30, 1.30, 1.30),
            }
            target = targets[self.state]
        step = self.SQUISH_SPEED * dt
        for i in range(3):
            diff = target[i] - self.body_scale[i]
            if abs(diff) <= step:
                self.body_scale[i] = target[i]
            else:
                self.body_scale[i] += math.copysign(step, diff)
        self.model.setScale(self.body_scale)

    def attach_camera(self, camera):
        """Reposiciona a câmera atrás do personagem (saída do free-cam)."""
        pitch_rad = math.radians(self.cam_pitch)
        camera.setPos(
            self.player_node.getX(),
            self.player_node.getY() - self.CAM_DIST_MAX * math.cos(pitch_rad),
            self.player_node.getZ() + self.CAM_DIST_MAX * math.sin(pitch_rad),
        )
        camera.lookAt(self.player_node)

    def update_key_map(self, key, state):
        self.key_map[key] = state

    def do_grab(self):
        if getattr(self.base, 'game_paused', True):
            return
        if self.grab_phase != 0:
            return  # animação já em andamento
        self.grab_phase       = 1
        self.grab_phase_timer = self.GRAB_T1_TIME

    def do_jump(self):
        if getattr(self.base, 'game_paused', True):
            return
        if self.is_grounded and self.state != PlayerState.CROUCH and self.grab_phase == 0:
            self.vel_z       = self.JUMP_SPEED
            self.is_grounded = False

    # ── Guard AI interface ────────────────────────────────────
    def get_position(self) -> Point3:
        """Returns the player's current world position."""
        return self.player_node.getPos()

    def get_size_factor(self) -> float:
        """
        Normalised growth scale for guard detection.
        Baseline body_scale is 1.3 on all axes; returns a float in [1.0, ~3.0].
        Uses the largest axis so squish/stretch during animation doesn't
        accidentally shrink the detection window.
        """
        raw = max(self.body_scale.x, self.body_scale.y, self.body_scale.z)
        return max(1.0, raw / 1.3)

    def get_is_sprinting(self) -> bool:
        """Stub — sprint mechanic not implemented yet. Always False."""
        return False

    def get_is_crouching(self) -> bool:
        """True while the player is in CROUCH state."""
        return self.state == PlayerState.CROUCH

    def get_node_path(self) -> NodePath:
        """Returns the player's root NodePath for scene-graph queries."""
        return self.player_node

    def is_visible(self) -> bool:
        """False while camouflage is active — guards detect with reduced confidence."""
        return not self.is_camouflaged

    # ── Loop de atualização ──────────────────────────────────────────────
    def control_task(self, task):
        if getattr(self.base, 'game_paused', True):
            return task.cont

        dt = self.base.clock.getDt()

        self._update_state(dt)

        # Atualiza inputs do shader: wobble time + direção da luz em view space
        ld = Vec3(0.5, -0.5, 1.0).normalized()
        lv = self.base.render.getRelativeVector(self.base.camera, ld)
        ft = self.base.clock.getFrameTime()
        for m in (self.model_normal, self.model_crunch_t1, self.model_crunch,
                  self.model_grab_t1, self.model_grab_t2, self.model_grab):
            m.setShaderInput("light_dir_view", lv)
            m.setShaderInput("time", ft)

        speed = self.WALK_SPEED * (
            self.CROUCH_SPEED_MULT if self.state == PlayerState.CROUCH else 1.0
        )

        # ── Rotação (A/D giram em torno de Z) ─────────────────────────
        if self.key_map["left"]:
            self.player_node.setH(self.player_node.getH() + self.TURN_SPEED * dt)
        if self.key_map["right"]:
            self.player_node.setH(self.player_node.getH() - self.TURN_SPEED * dt)

        # ── Movimento (W/S deslocam no eixo Y local do personagem) ────
        if self.key_map["forward"]:
            self.player_node.setY(self.player_node,  speed * dt)
        if self.key_map["backward"]:
            self.player_node.setY(self.player_node, -speed * dt)

        # ── Física vertical (gravidade + pulo) ───────────────────────
        if not self.is_grounded:
            self.vel_z -= self.GRAVITY * dt
            self.player_node.setZ(self.player_node.getZ() + self.vel_z * dt)
            if self.player_node.getZ() <= self.GROUND_LEVEL:
                if self.vel_z < -3.0:
                    self.land_squash_timer = 0.18
                self.player_node.setZ(self.GROUND_LEVEL)
                self.vel_z       = 0.0
                self.is_grounded = True

        # ── Câmera: rotação manual via mouse + dolly por obstáculos ───
        if not getattr(self.base, 'free_cam_active', False):
            self._handle_mouse()
            self._update_camera_ralph(dt)

        return task.cont

    # ── Máquina de estados ───────────────────────────────────────────────
    def _update_state(self, dt):
        # Tick do grab — avança fases da animação
        if self.grab_phase != 0:
            self.grab_phase_timer -= dt
            if self.grab_phase_timer <= 0:
                _phase_durations = {
                    1: self.GRAB_T1_TIME,
                    2: self.GRAB_T2_TIME,
                    3: self.GRAB_HOLD_TIME,
                    4: self.GRAB_T2_TIME,
                    5: self.GRAB_T1_TIME,
                }
                next_phase = self.grab_phase + 1
                if next_phase > 5:
                    self.grab_phase       = 0
                    self.grab_phase_timer = 0.0
                else:
                    self.grab_phase       = next_phase
                    self.grab_phase_timer = _phase_durations[next_phase]

        is_moving    = self.key_map["forward"] or self.key_map["backward"]
        is_crouching = self.key_map["crouch"]

        if self.grab_phase != 0:
            new_state = PlayerState.GRAB
        elif is_crouching:
            new_state = PlayerState.CROUCH
        elif is_moving:
            new_state = PlayerState.WALK
        else:
            new_state = PlayerState.IDLE

        # Detecta mudança entre agachado e em pé — inicia janela de transição
        was_crouch = (self.state == PlayerState.CROUCH)
        now_crouch = (new_state == PlayerState.CROUCH)
        if was_crouch != now_crouch:
            self.crouch_transition_timer = self.CROUCH_TRANSITION_TIME
        elif self.crouch_transition_timer > 0:
            self.crouch_transition_timer = max(0.0, self.crouch_transition_timer - dt)

        self.state = new_state
        self._update_active_model()

        # Ajuste suave do pitch ao agachar (lerp independente do controle manual)
        target_adj = self.CAM_PITCH_CROUCH if is_crouching else 0.0
        diff = target_adj - self.cam_pitch_adj
        step = self.CAM_PITCH_SPEED * dt
        if abs(diff) <= step:
            self.cam_pitch_adj = target_adj
        else:
            self.cam_pitch_adj += math.copysign(step, diff)

        self._apply_squish(dt)

        # Tick do timer de squash de aterrissagem
        if self.land_squash_timer > 0:
            self.land_squash_timer = max(0.0, self.land_squash_timer - dt)

        # Tick dos timers de camuflagem
        if self.is_camouflaged:
            self.camo_active_timer -= dt
            if self.camo_active_timer <= 0.0:
                self._deactivate_camouflage()
        elif self.camo_cooldown_timer > 0.0:
            self.camo_cooldown_timer -= dt

    # ── Camuflagem ───────────────────────────────────────────────────────
    def toggle_camouflage(self):
        if getattr(self.base, 'game_paused', True):
            return
        if self.is_camouflaged or self.camo_cooldown_timer > 0.0:
            return

        self.is_camouflaged    = True
        self.camo_active_timer = self.CAMO_DURATION
        self.model.setTransparency(TransparencyAttrib.M_alpha)
        self.model.setColorScale(0.4, 0.9, 1.0, self.CAMO_ALPHA)

    def _deactivate_camouflage(self):
        self.is_camouflaged      = False
        self.camo_active_timer   = 0.0
        self.camo_cooldown_timer = self.CAMO_COOLDOWN
        self.model.clearColorScale()
        self.model.clearTransparency()

    # ── Rotação manual da câmera (mouse) ─────────────────────────────────
    def _handle_mouse(self):
        win = self.base.win
        # Pega a posição absoluta na tela se necessário
        md = win.getPointer(0)
        x, y = md.getX(), md.getY()
        
        cx = win.getXSize() // 2
        cy = win.getYSize() // 2

        dx = x - cx
        dy = y - cy

        # Se o mouse saiu do lugar (mesmo que seja pra fora da janela)
        if dx != 0 or dy != 0:
            # Força o retorno para o centro antes de qualquer cálculo
            win.movePointer(0, cx, cy)
            
            # Só rotaciona se o jogo não estiver pausado e o movimento for razoável
            if not self.base.game_paused:
                # Se dx for muito alto (ex: 500), o mouse fugiu. 
                # Ignoramos esse frame para não dar um giro de 360 graus louco.
                if abs(dx) < win.getXSize() / 2:
                    self._orbit_camera(-dx * self.MOUSE_SENS)
                self._pitch_camera(dy * self.MOUSE_SENS)

    def _pitch_camera(self, delta_deg):
        """Ajusta o ângulo de elevação da câmera, com clamp."""
        self.cam_pitch = max(self.CAM_PITCH_MIN,
                             min(self.CAM_PITCH_MAX, self.cam_pitch + delta_deg))

    def _orbit_camera(self, angle_deg):
        """Rotaciona a posição da câmera ao redor do eixo Z do player."""
        rad   = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)

        cam_pos    = self.base.camera.getPos()
        player_pos = self.player_node.getPos()

        # Vetor (câmera - player) no plano XY
        vx = cam_pos.getX() - player_pos.getX()
        vy = cam_pos.getY() - player_pos.getY()

        # Rotação 2D em torno de Z
        new_vx = vx * cos_a - vy * sin_a
        new_vy = vx * sin_a + vy * cos_a

        self.base.camera.setX(player_pos.getX() + new_vx)
        self.base.camera.setY(player_pos.getY() + new_vy)

    def _query_cam_dist(self, ideal_cam_pos):
        """
        Lança CollisionSegment do player até ideal_cam_pos.
        Retorna a distância segura (até o primeiro obstáculo, com buffer),
        ou CAM_DIST_MAX se o caminho estiver livre.
        """
        player_pos = self.player_node.getPos()
        self.cam_seg_solid.setPointA(player_pos)
        self.cam_seg_solid.setPointB(ideal_cam_pos)

        self.cam_queue.clearEntries()
        self.cam_trav.traverse(self.base.render)

        if self.cam_queue.getNumEntries() == 0:
            return self.CAM_DIST_MAX

        self.cam_queue.sortEntries()
        hit_pos = self.cam_queue.getEntry(0).getSurfacePoint(self.base.render)
        dist    = (hit_pos - player_pos).length()
        return max(self.CAM_DIST_MIN, dist - 0.4)

    def _update_camera_ralph(self, dt):
        """
        Câmera com dolly por obstáculo:
          – Direção XY mantida pelo _orbit_camera (mouse).
          – Distância = min(cam_dist_current, distância até o obstáculo).
          – Snap imediato ao aproximar; recuo suave ao afastar.
        """
        player_pos = self.player_node.getPos()
        cam_pos    = self.base.camera.getPos()

        # Direção normalizada câmera→player no plano XY
        dx = cam_pos.x - player_pos.x
        dy = cam_pos.y - player_pos.y
        dist_xy = math.sqrt(dx * dx + dy * dy)

        if dist_xy < 0.001:
            dx, dy, dist_xy = 0.0, -self.CAM_DIST_MAX, self.CAM_DIST_MAX

        nx = dx / dist_xy
        ny = dy / dist_xy

        # Pitch total: controle do mouse + ajuste suave do crouch
        total_pitch = max(self.CAM_PITCH_MIN,
                          min(self.CAM_PITCH_MAX, self.cam_pitch + self.cam_pitch_adj))
        pitch_rad = math.radians(total_pitch)
        cos_p = math.cos(pitch_rad)
        sin_p = math.sin(pitch_rad)

        # Posição ideal (sem obstáculos) em coordenadas esféricas
        ideal_pos = Point3(
            player_pos.x + nx * self.CAM_DIST_MAX * cos_p,
            player_pos.y + ny * self.CAM_DIST_MAX * cos_p,
            player_pos.z + self.CAM_DIST_MAX * sin_p,
        )

        safe_dist = self._query_cam_dist(ideal_pos)

        # Aproxima imediatamente; recua de forma suave
        if safe_dist < self.cam_dist_current:
            self.cam_dist_current = safe_dist
        else:
            self.cam_dist_current = min(
                self.cam_dist_current + self.CAM_ZOOM_SPEED * dt,
                self.CAM_DIST_MAX,
            )
        self.cam_dist_current = min(self.cam_dist_current, safe_dist)

        # Aplica posição final da câmera
        self.base.camera.setPos(
            player_pos.x + nx * self.cam_dist_current * cos_p,
            player_pos.y + ny * self.cam_dist_current * cos_p,
            player_pos.z + self.cam_dist_current * sin_p,
        )

        # Floater: ponto de foco acima da cabeça
        self.floater.setPos(player_pos)
        self.floater.setZ(player_pos.z + self.FLOATER_Z_OFFSET)
        self.base.camera.lookAt(self.floater)
