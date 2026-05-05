from direct.showbase.ShowBase import ShowBase
from direct.gui.DirectGui import DirectButton, DirectFrame
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import WindowProperties, CollisionTraverser, CollisionHandlerPusher, TextNode
from panda3d.core import loadPrcFileData

from core.level_manager import LevelManager
from entities.player import Player
from entities.item_manager import ItemManager
from core.beholder_manager import BeholderManager
from core.game_state import GameState
from core.shard_manager import ShardManager
from core.minimap import Minimap
from core.torch_fire import TorchFireManager

# Força o mouse a ficar preso dentro da janela (Modo Grab)
loadPrcFileData("", "mouse-mode absolute") 
# Tenta impedir que o sistema operacional redimensione as coordenadas (Problema de DPI)
loadPrcFileData("", "win-unfocused-input 1")

loadPrcFileData("", "want-directtools 0")
loadPrcFileData("", "want-tk 0")
# Force OpenGL 3.2 Core profile so GLSL 330 shaders compile (macOS caps at 4.1 Core).
loadPrcFileData("", "gl-version 3 2")


class ShadowHeist(ShowBase):
    def __init__(self):
        super().__init__()
        self.mouseWatcherNode.set_enter_pattern('mouse-enter')
        self.mouseWatcherNode.set_leave_pattern('mouse-leave')

        props = WindowProperties()
        props.setTitle("Shadow Heist - Dev Version")
        props.setSize(1280, 720)
        self.win.requestProperties(props)

        self.disableMouse()

        self.cTrav  = CollisionTraverser()
        self.pusher = CollisionHandlerPusher()

        self.game_paused    = True
        self.game_started   = False
        self.free_cam_active = False

        self.level_manager     = LevelManager(self)
        self.player            = Player(self)
        self.item_manager      = ItemManager(self)
        self.beholder_manager  = BeholderManager(self, on_caught=self._on_caught)
        self.torch_fires       = TorchFireManager(self, tip_offset=(0.0, 0.0, 1.0))
        self.shard_manager     = ShardManager(self)
        self.game_state        = GameState(self)
        self.minimap           = Minimap(self)
        self._build_debug_overlay()

        self._build_menu()
        self._show_menu()

        self.accept("escape", self.toggle_pause)
        self.accept("c",      self.toggle_free_cam)
        self.taskMgr.add(self._update_debug_overlay, "debug_overlay_task")

    # ------------------------------------------------------------------
    # Mouse lock
    # ------------------------------------------------------------------

    def lock_mouse(self):
        # 1. Garante que a janela tenha o foco total do sistema
        self.win.setActive(True)
        
        props = WindowProperties()
        props.setCursorHidden(True)
        # M_confined keeps the cursor pinned inside the window while still
        # reporting absolute coords — manual recenter then yields a clean
        # delta cross-platform (M_relative behaves inconsistently on macOS).
        props.setMouseMode(WindowProperties.M_confined)
        self.win.requestProperties(props)
        
        # 2. Centraliza imediatamente
        cx = self.win.getXSize() // 2
        cy = self.win.getYSize() // 2
        self.win.movePointer(0, cx, cy)

    def unlock_mouse(self):
        props = WindowProperties()
        props.setCursorHidden(False)
        props.setMouseMode(WindowProperties.M_absolute)
        self.win.requestProperties(props)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self):
        self.menu_root = DirectFrame(
            frameColor=(0, 0, 0, 0.78),
            frameSize=(-3, 3, -3, 3),
            parent=self.aspect2d,
        )

        OnscreenText(
            text="SHADOW HEIST",
            pos=(0, 0.28),
            scale=0.13,
            fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 1),
            parent=self.menu_root,
        )

        self._btn_play = DirectButton(
            text="JOGAR",
            scale=0.09,
            pos=(0, 0, 0.05),
            relief=None,
            text_fg=(1, 1, 1, 1),
            text_shadow=(0, 0, 0, 1),
            command=self._resume_game,
            parent=self.menu_root,
        )

        DirectButton(
            text="SAIR",
            scale=0.09,
            pos=(0, 0, -0.13),
            relief=None,
            text_fg=(0.85, 0.3, 0.3, 1),
            text_shadow=(0, 0, 0, 1),
            command=self.userExit,
            parent=self.menu_root,
        )

        self.menu_root.hide()

    def _build_debug_overlay(self):
        self._debug_pos_text = OnscreenText(
            text="X: 0.00  Y: 0.00  Z: 0.00\nBeholder: --",
            pos=(-1.30, 0.93),
            scale=0.05,
            align=TextNode.ALeft,
            fg=(1, 1, 1, 0.92),
            shadow=(0, 0, 0, 1),
            mayChange=True,
            parent=self.aspect2d,
        )

    def _update_debug_overlay(self, task):
        beholder_text = "Beholder: --"
        if hasattr(self, "level_manager") and hasattr(self.level_manager, "house"):
            beholder_pos = self.level_manager.house.get_beholder_position()
            if beholder_pos is not None:
                beholder_text = (
                    f"Beholder: X: {beholder_pos.x:7.2f}  "
                    f"Y: {beholder_pos.y:7.2f}  Z: {beholder_pos.z:6.2f}"
                )
        if hasattr(self, "player") and hasattr(self.player, "player_node"):
            pos = self.player.player_node.getPos()
            self._debug_pos_text.setText(
                f"X: {pos.x:7.2f}  Y: {pos.y:7.2f}  Z: {pos.z:6.2f}\n{beholder_text}"
            )
        return task.cont

    def _show_menu(self):
        self.game_paused = True
        self._btn_play['text'] = "RETOMAR" if self.game_started else "JOGAR"
        self.menu_root.show()
        self.unlock_mouse()

    def _resume_game(self):
        self.game_started = True
        self.game_paused  = False
        self.menu_root.hide()
        self.lock_mouse()

    def _on_caught(self):
        if hasattr(self, "game_state"):
            self.game_state.caught_by_beholder()

    def toggle_pause(self):
        if self.free_cam_active:
            return
        if self.game_paused:
            self._resume_game()
        else:
            self._show_menu()

    # ------------------------------------------------------------------
    # Dev free cam
    # ------------------------------------------------------------------

    def toggle_free_cam(self):
        if self.game_paused:
            return
        self.free_cam_active = not self.free_cam_active

        if self.free_cam_active:
            self.camera.reparentTo(self.render)
            self.unlock_mouse()
            self.enableMouse()
            print("Dev: Câmera Livre Ativada")
        else:
            self.disableMouse()
            self.lock_mouse()
            self.player.attach_camera(self.camera)
            print("Dev: Câmera em Terceira Pessoa Ativada")


if __name__ == "__main__":
    app = ShadowHeist()
    app.run()
