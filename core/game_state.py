from enum import Enum, auto

from direct.gui.DirectGui import DirectFrame, DirectButton, DirectWaitBar
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import TextNode, Vec3

import config as Cfg


class HeistOutcome(Enum):
    PLAYING = auto()
    WON     = auto()
    LOST    = auto()


class GameState:
    """
    Heist objective + win/lose handling + HUD.

    Loop:
      1. Player must reach the mirror (highlighted) and pick it up (mouse1).
      2. Carrying the mirror, reach the south exit zone to escape.
      3. If a beholder enters ALERT and touches the player → caught (lose).

    HUD:
      - Detection bar (max across all beholders).
      - Objective hint text.
      - Win / lose overlay with retry button.
    """

    def __init__(self, base):
        self.base = base
        self.outcome = HeistOutcome.PLAYING
        self.mirror_picked_up = False
        self._was_alert = False
        self._spotted_timer = 0.0
        self._build_hud()
        self._build_vignette()
        self._build_overlay()
        self.base.taskMgr.add(self._update_task, "game_state_task")

    # ------------------------------------------------------------------
    # HUD
    # ------------------------------------------------------------------

    def _build_hud(self):
        self._objective_text = OnscreenText(
            text="Find the relic shards (0/3)",
            pos=(0.0, 0.92),
            scale=0.055,
            fg=(1, 0.95, 0.65, 1),
            shadow=(0, 0, 0, 1),
            mayChange=True,
            parent=self.base.aspect2d,
            align=TextNode.ACenter,
        )

        self._story_text = OnscreenText(
            text="Lab specimen #07. The keep above hides three shards.",
            pos=(0.0, 0.85),
            scale=0.038,
            fg=(0.85, 0.78, 0.95, 0.85),
            shadow=(0, 0, 0, 1),
            mayChange=True,
            parent=self.base.aspect2d,
            align=TextNode.ACenter,
        )
        self._story_timer = 6.0

        self._detect_bar = DirectWaitBar(
            text="",
            value=0.0,
            range=1.0,
            pos=(0, 0, -0.92),
            scale=0.45,
            barColor=(0.95, 0.85, 0.15, 0.95),
            frameColor=(0, 0, 0, 0.55),
            parent=self.base.aspect2d,
        )

        self._detect_label = OnscreenText(
            text="DETECCAO",
            pos=(0.0, -0.86),
            scale=0.04,
            fg=(1, 1, 1, 0.85),
            shadow=(0, 0, 0, 1),
            parent=self.base.aspect2d,
            align=TextNode.ACenter,
            mayChange=True,
        )

    def _build_vignette(self):
        """Four red edge strips on render2d that tint stronger with detection."""
        thick = 0.18
        edges = [
            (-1.0,  1.0,  1.0 - thick,  1.0),  # top: l, r, b, t
            (-1.0,  1.0, -1.0,  -1.0 + thick), # bottom
            (-1.0, -1.0 + thick, -1.0,  1.0),  # left
            ( 1.0 - thick,  1.0, -1.0,  1.0),  # right
        ]
        self._vignette_frames = []
        for (l, r, b, t) in edges:
            f = DirectFrame(
                frameColor=(1.0, 0.05, 0.05, 0.0),
                frameSize=(l, r, b, t),
                parent=self.base.render2d,
                state="normal",
            )
            f.setBin("fixed", 100)
            f.setDepthWrite(False)
            f.setDepthTest(False)
            self._vignette_frames.append(f)

        # Spotted flash: full-screen white briefly on first ALERT.
        self._spotted_flash = DirectFrame(
            frameColor=(1.0, 1.0, 1.0, 0.0),
            frameSize=(-1, 1, -1, 1),
            parent=self.base.render2d,
        )
        self._spotted_flash.setBin("fixed", 110)
        self._spotted_flash.setDepthWrite(False)
        self._spotted_flash.setDepthTest(False)

        self._spotted_text = OnscreenText(
            text="!",
            pos=(0.0, 0.10),
            scale=0.32,
            fg=(1.0, 0.15, 0.15, 0.0),
            shadow=(0, 0, 0, 0.0),
            mayChange=True,
            parent=self.base.aspect2d,
            align=TextNode.ACenter,
        )

    def _build_overlay(self):
        self._overlay = DirectFrame(
            frameColor=(0, 0, 0, 0.78),
            frameSize=(-3, 3, -3, 3),
            parent=self.base.aspect2d,
        )
        self._overlay_title = OnscreenText(
            text="",
            pos=(0, 0.18),
            scale=0.16,
            fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 1),
            parent=self._overlay,
            mayChange=True,
        )
        self._overlay_sub = OnscreenText(
            text="",
            pos=(0, 0.04),
            scale=0.06,
            fg=(0.95, 0.95, 0.95, 1),
            shadow=(0, 0, 0, 1),
            parent=self._overlay,
            mayChange=True,
        )
        DirectButton(
            text="TENTAR DE NOVO",
            scale=0.08,
            pos=(0, 0, -0.12),
            relief=None,
            text_fg=(1, 1, 1, 1),
            text_shadow=(0, 0, 0, 1),
            command=self._restart,
            parent=self._overlay,
        )
        DirectButton(
            text="MENU",
            scale=0.07,
            pos=(0, 0, -0.28),
            relief=None,
            text_fg=(0.85, 0.3, 0.3, 1),
            text_shadow=(0, 0, 0, 1),
            command=self._return_to_menu,
            parent=self._overlay,
        )
        self._overlay.hide()

    # ------------------------------------------------------------------
    # Per-frame
    # ------------------------------------------------------------------

    def _update_task(self, task):
        if self.outcome != HeistOutcome.PLAYING:
            return task.cont
        if getattr(self.base, "game_paused", True):
            return task.cont

        # Mirror state.
        item_mgr = getattr(self.base, "item_manager", None)
        if item_mgr is not None and item_mgr.is_mirror_held():
            self.mirror_picked_up = True

        # Detection HUD.
        bm = getattr(self.base, "beholder_manager", None)
        det = bm.max_detection() if bm is not None else 0.0
        self._detect_bar["value"] = det

        # Vignette intensity tied to detection (smoothed via gamma).
        vig_alpha = min(1.0, det ** 1.4) * 0.65
        for f in self._vignette_frames:
            f["frameColor"] = (1.0, 0.05, 0.05, vig_alpha)

        # Spotted flash trigger: rising edge into ALERT.
        is_alert_now = bm is not None and bm.any_alert()
        if is_alert_now and not self._was_alert:
            self._spotted_timer = 0.5
        self._was_alert = is_alert_now

        dt = globalClock.getDt()
        if self._spotted_timer > 0.0:
            self._spotted_timer = max(0.0, self._spotted_timer - dt)
            t = self._spotted_timer / 0.5
            self._spotted_flash["frameColor"] = (1.0, 1.0, 1.0, 0.55 * t)
            self._spotted_text["fg"] = (1.0, 0.15, 0.15, t)
            self._spotted_text["scale"] = 0.18 + 0.18 * t
        else:
            self._spotted_flash["frameColor"] = (1.0, 1.0, 1.0, 0.0)
            self._spotted_text["fg"] = (1.0, 0.15, 0.15, 0.0)

        if bm is not None and bm.any_alert():
            self._detect_bar["barColor"] = (1.0, 0.15, 0.15, 1.0)
            self._detect_label.setText("ALERTA!")
            self._detect_label.setFg((1, 0.4, 0.4, 1))
        elif bm is not None and bm.any_suspicious():
            self._detect_bar["barColor"] = (1.0, 0.85, 0.15, 1.0)
            self._detect_label.setText("DESCONFIADO")
            self._detect_label.setFg((1, 0.95, 0.5, 1))
        else:
            self._detect_bar["barColor"] = (0.4, 0.85, 0.4, 1.0)
            self._detect_label.setText("ESCONDIDO")
            self._detect_label.setFg((0.7, 1, 0.7, 0.9))

        # Story intro fade-out.
        if self._story_timer > 0.0:
            self._story_timer = max(0.0, self._story_timer - dt)
            alpha = min(1.0, self._story_timer / 1.5)
            self._story_text["fg"] = (0.85, 0.78, 0.95, 0.85 * alpha)

        # Shard objective + exit gate.
        sm = getattr(self.base, "shard_manager", None)
        collected = sm.collected_count if sm is not None else 0
        total     = len(sm.shards) if sm is not None else Cfg.SHARD_COUNT

        if sm is None or not sm.all_collected():
            self._objective_text.setText(
                f"Find the relic shards  ({collected}/{total})"
            )
        else:
            self._objective_text.setText("All shards bound. ESCAPE south to the crypt portal.")
            player = getattr(self.base, "player", None)
            if player is not None:
                p = player.player_node.getPos()
                ex, ey = Cfg.HEIST_EXIT_POS
                d = ((p.x - ex) ** 2 + (p.y - ey) ** 2) ** 0.5
                if d <= Cfg.HEIST_EXIT_RADIUS:
                    self._win()
        return task.cont

    # ------------------------------------------------------------------
    # Outcomes
    # ------------------------------------------------------------------

    def caught_by_beholder(self):
        if self.outcome != HeistOutcome.PLAYING:
            return
        self.outcome = HeistOutcome.LOST
        self._show_overlay("CAPTURADO", "Um beholder te viu! Tente furtividade.")

    def _win(self):
        if self.outcome != HeistOutcome.PLAYING:
            return
        self.outcome = HeistOutcome.WON
        self._show_overlay(
            "RELICS BOUND",
            "The crypt portal opens. You step through and the keep is silent.",
        )

    def _show_overlay(self, title, sub):
        self._overlay_title.setText(title)
        self._overlay_sub.setText(sub)
        self._overlay.show()
        self.base.game_paused = True
        if hasattr(self.base, "unlock_mouse"):
            self.base.unlock_mouse()

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def _restart(self):
        self._overlay.hide()
        self._reset_world()
        self.outcome = HeistOutcome.PLAYING
        if hasattr(self.base, "_resume_game"):
            self.base._resume_game()

    def _return_to_menu(self):
        self._overlay.hide()
        self._reset_world()
        self.outcome = HeistOutcome.PLAYING
        if hasattr(self.base, "_show_menu"):
            self.base._show_menu()

    def _reset_world(self):
        self.mirror_picked_up = False
        self._story_timer = 6.0
        sm = getattr(self.base, "shard_manager", None)
        if sm is not None:
            sm.reset()

        # Reset player.
        player = getattr(self.base, "player", None)
        if player is not None:
            spawn = self.base.level_manager.get_player_spawn()
            spawn.setZ(Cfg.GROUND_LEVEL)
            player.player_node.setPos(spawn)
            player.vel_z = 0.0
            player.is_grounded = True

        # Reset mirror.
        item_mgr = getattr(self.base, "item_manager", None)
        if item_mgr is not None and item_mgr.mirror is not None:
            mirror = item_mgr.mirror
            if mirror.is_held and player is not None:
                mirror.drop(player.player_node.getPos())
            spawn = self.base.level_manager.house.get_mirror_spawn_point()
            mirror.node.setPos(spawn.x, spawn.y, 0.0) if hasattr(mirror, "node") else None

        # Reset beholders.
        bm = getattr(self.base, "beholder_manager", None)
        if bm is not None:
            from entities.beholder import BeholderState
            for b in bm.beholders:
                b.detection = 0.0
                b.state = BeholderState.PATROL
                b.last_seen_pos = None
                b.search_timer = 0.0
                if b.waypoints:
                    wp = b.waypoints[0]
                    b.root.setPos(wp.x, wp.y, b.hover_z)
                    b.wp_index = 0
            bm.reset_caught()
