# main.py
"""
Shadow Heist — main entry point.
Phase 4: GuardManager and guards integrated into the live game.
"""

from direct.showbase.ShowBase import ShowBase
from direct.gui.DirectGui import DirectButton, DirectFrame
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    WindowProperties, CollisionTraverser, CollisionHandlerPusher,
    Point3, loadPrcFileData,
)

from core.level_manager import LevelManager
from entities.player import Player
from entities.guard.guard import Guard
from entities.guard.guard_manager import GuardManager
from entities.guard.waypoint import Waypoint
from entities.guard.integration.player_interface import PlayerInterface
from entities.guard.integration.env_interface import EnvInterface

loadPrcFileData("", "mouse-mode absolute")
loadPrcFileData("", "win-unfocused-input 1")
loadPrcFileData("", "want-directtools 0")
loadPrcFileData("", "want-tk 0")

# ── patrol routes ─────────────────────────────────────────────────────────────
#   Adjust these positions to match your actual mansion layout.
GUARD_A_WAYPOINTS = [
    Waypoint(Point3( 10,  10, 0), wait_time=2.0),
    Waypoint(Point3( 10, -10, 0), wait_time=1.5),
    Waypoint(Point3(-10, -10, 0), wait_time=2.0),
    Waypoint(Point3(-10,  10, 0), wait_time=1.5),
]
GUARD_B_WAYPOINTS = [
    Waypoint(Point3(0,  15, 0), wait_time=3.0),
    Waypoint(Point3(0,  -5, 0), wait_time=1.0),
]
# ─────────────────────────────────────────────────────────────────────────────


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

        self.game_paused     = True
        self.game_started    = False
        self.free_cam_active = False

        # ── game objects ──────────────────────────────────────────────────
        self.level_manager = LevelManager(self)
        self.player        = Player(self)

        # ── guard AI ──────────────────────────────────────────────────────
        self._setup_guards()

        # ── menu ──────────────────────────────────────────────────────────
        self._build_menu()
        self._show_menu()

        # ── keybinds ──────────────────────────────────────────────────────
        self.accept("escape", self.toggle_pause)
        self.accept("f1",     self.toggle_free_cam)   # moved from "c" — c is crouch

    # ── guard setup ───────────────────────────────────────────────────────────

    def _setup_guards(self) -> None:
        """
        Wire integration adapters, create guards, hand them to GuardManager.
        Called once during __init__, after level_manager and player exist.
        """
        player_iface = PlayerInterface(self.player)
        env_iface    = EnvInterface(self.level_manager)

        self.guard_manager = GuardManager(self)

        guard_a = Guard(
            base=self,
            waypoints=GUARD_A_WAYPOINTS,
            player=player_iface,
            env=env_iface,
            name="GuardA",
        )
        guard_b = Guard(
            base=self,
            waypoints=GUARD_B_WAYPOINTS,
            player=player_iface,
            env=env_iface,
            name="GuardB",
        )

        self.guard_manager.add_guard(guard_a)
        self.guard_manager.add_guard(guard_b)
        self.guard_manager.start()

        print(
            f"[ShadowHeist] Guard AI ready. "
            f"Player: {player_iface}  Env: {env_iface}"
        )

    # ── mouse lock ────────────────────────────────────────────────────────────

    def lock_mouse(self):
        self.win.setActive(True)
        props = WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)
        cx = self.win.getXSize() // 2
        cy = self.win.getYSize() // 2
        self.win.movePointer(0, cx, cy)

    def unlock_mouse(self):
        props = WindowProperties()
        props.setCursorHidden(False)
        props.setMouseMode(WindowProperties.M_absolute)
        self.win.requestProperties(props)

    # ── menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        self.menu_root = DirectFrame(
            frameColor=(0, 0, 0, 0.78),
            frameSize=(-3, 3, -3, 3),
            parent=self.aspect2d,
        )
        OnscreenText(
            text="SHADOW HEIST",
            pos=(0, 0.28), scale=0.13,
            fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1),
            parent=self.menu_root,
        )
        self._btn_play = DirectButton(
            text="JOGAR",
            scale=0.09, pos=(0, 0, 0.05),
            relief=None,
            text_fg=(1, 1, 1, 1), text_shadow=(0, 0, 0, 1),
            command=self._resume_game,
            parent=self.menu_root,
        )
        DirectButton(
            text="SAIR",
            scale=0.09, pos=(0, 0, -0.13),
            relief=None,
            text_fg=(0.85, 0.3, 0.3, 1), text_shadow=(0, 0, 0, 1),
            command=self.userExit,
            parent=self.menu_root,
        )
        self.menu_root.hide()

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

    def toggle_pause(self):
        if self.free_cam_active:
            return
        if self.game_paused:
            self._resume_game()
        else:
            self._show_menu()

    # ── dev free cam ──────────────────────────────────────────────────────────

    def toggle_free_cam(self):
        if self.game_paused:
            return
        self.free_cam_active = not self.free_cam_active

        if self.free_cam_active:
            self.camera.reparentTo(self.render)
            self.unlock_mouse()
            self.enableMouse()
            print("Dev: Free Camera ON  (F1 to return)")
        else:
            self.disableMouse()
            self.lock_mouse()
            self.player.attach_camera(self.camera)
            print("Dev: Third-Person Camera ON")


if __name__ == "__main__":
    app = ShadowHeist()
    app.run()