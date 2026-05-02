import math
from enum import Enum, auto
from panda3d.core import (
    CollisionSphere, CollisionNode,
    CollisionSegment, CollisionHandlerQueue, CollisionTraverser,
    BitMask32, Point3, TransparencyAttrib,
)


class PlayerState(Enum):
    IDLE   = auto()
    WALK   = auto()
    CROUCH = auto()


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
    CAM_DIST_MAX     = 20.0   # distância máxima antes de puxar a câmera
    CAM_DIST_MIN     = 5.0    # distância mínima antes de empurrar a câmera
    CAM_HEIGHT       = 3.0    # altura da câmera relativa ao player
    FLOATER_Z_OFFSET = 2.0    # alvo da câmera (acima da cabeça do player)

    # ── Movimento ────────────────────────────────────────────────────────
    TURN_SPEED       = 200.0  # graus/seg ao virar (A/D)
    WALK_SPEED       = 12.0   # unidades/seg ao andar (W/S)

    # ── Rotação manual da câmera via mouse ───────────────────────────────
    MOUSE_SENS       = 0.25   # graus de órbita por pixel de mouse

    # ── Câmera – dolly por obstáculos ────────────────────────────────────
    CAM_ZOOM_SPEED   = 10.0   # unidades/seg ao recuar após obstáculo sair

    # ── Estados ───────────────────────────────────────────────────────────
    CROUCH_SPEED_MULT = 0.45  # fator de velocidade ao agachar
    CAM_CROUCH_HEIGHT = 1.2   # altura da câmera ao agachar
    CAM_HEIGHT_SPEED  = 6.0   # unidades/seg de transição de altura da câmera

    # ── Camuflagem ────────────────────────────────────────────────────────
    CAMO_ALPHA        = 0.22  # opacidade do modelo ao camuflado
    CAMO_DURATION     = 1.0   # segundos de duração da camuflagem
    CAMO_COOLDOWN     = 8.0   # segundos de cooldown após uso

    def __init__(self, base):
        self.base = base

        # ── Personagem ──────────────────────────────────────────────────
        self.player_node = self.base.render.attachNewNode("player_node")
        self.player_node.setPos(0, 0, 1)

        self.model = self.base.loader.loadModel("smiley")
        self.model.reparentTo(self.player_node)
        # O smiley vem do Panda3D com a face apontando -Y. Como o player_node
        # considera +Y como frente, giramos o modelo 180° para alinhar a face
        # à direção de movimento (e deixar a câmera atrás vendo a nuca).
        self.model.setH(180)

        # ── Floater: alvo da câmera, sempre acima da cabeça do player ──
        self.floater = self.base.render.attachNewNode("floater")

        # ── Câmera começa atrás do personagem ───────────────────────────
        self.base.camera.setPos(
            self.player_node.getX(),
            self.player_node.getY() - self.CAM_DIST_MAX,
            self.player_node.getZ() + self.CAM_HEIGHT,
        )
        self.base.camera.lookAt(self.player_node)

        self.setup_collision()
        self.setup_cam_collision()

        self.cam_dist_current   = self.CAM_DIST_MAX
        self.cam_height_current = float(self.CAM_HEIGHT)
        self.state              = PlayerState.IDLE
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
            ("w",           "forward"),  ("control-w",   "forward"),
            ("arrow_up",    "forward"),
            ("s",           "backward"), ("control-s",   "backward"),
            ("arrow_down",  "backward"),
            ("a",           "left"),     ("control-a",   "left"),
            ("arrow_left",  "left"),
            ("d",           "right"),    ("control-d",   "right"),
            ("arrow_right", "right"),
            ("lcontrol",    "crouch"),
        ]
        for key, action in bindings:
            self.base.accept(key,          self.update_key_map, [action, True])
            self.base.accept(key + "-up",  self.update_key_map, [action, False])

        self.base.accept("e", self.toggle_camouflage)

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

    def attach_camera(self, camera):
        """Reposiciona a câmera atrás do personagem (saída do free-cam)."""
        camera.setPos(
            self.player_node.getX(),
            self.player_node.getY() - self.CAM_DIST_MAX,
            self.player_node.getZ() + self.CAM_HEIGHT,
        )
        camera.lookAt(self.player_node)

    def update_key_map(self, key, state):
        self.key_map[key] = state

    # ── Loop de atualização ──────────────────────────────────────────────
    def control_task(self, task):
        if getattr(self.base, 'game_paused', True):
            return task.cont

        dt = self.base.clock.getDt()

        self._update_state(dt)

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

        # ── Câmera: rotação manual via mouse + dolly por obstáculos ───
        if not getattr(self.base, 'free_cam_active', False):
            self._handle_mouse()
            self._update_camera_ralph(dt)

        return task.cont

    # ── Máquina de estados ───────────────────────────────────────────────
    def _update_state(self, dt):
        is_moving    = self.key_map["forward"] or self.key_map["backward"]
        is_crouching = self.key_map["crouch"]

        if is_crouching:
            new_state = PlayerState.CROUCH
        elif is_moving:
            new_state = PlayerState.WALK
        else:
            new_state = PlayerState.IDLE

        self.state = new_state

        # Transição linear da altura da câmera
        target_h = self.CAM_CROUCH_HEIGHT if is_crouching else self.CAM_HEIGHT
        diff = target_h - self.cam_height_current
        step = self.CAM_HEIGHT_SPEED * dt
        if abs(diff) <= step:
            self.cam_height_current = target_h
        else:
            self.cam_height_current += math.copysign(step, diff)

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

        # Posição ideal (sem obstáculos) na distância máxima
        ideal_pos = Point3(
            player_pos.x + nx * self.CAM_DIST_MAX,
            player_pos.y + ny * self.CAM_DIST_MAX,
            player_pos.z + self.cam_height_current,
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
            player_pos.x + nx * self.cam_dist_current,
            player_pos.y + ny * self.cam_dist_current,
            player_pos.z + self.cam_height_current,
        )

        # Floater: ponto de foco acima da cabeça
        self.floater.setPos(player_pos)
        self.floater.setZ(player_pos.z + self.FLOATER_Z_OFFSET)
        self.base.camera.lookAt(self.floater)
