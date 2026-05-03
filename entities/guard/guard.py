"""
Guard — Phase 3
---------------
Full alert state machine with proper guard appearance.
"""

from __future__ import annotations
import math
from typing import Callable

from panda3d.core import (
    NodePath,
    Point3,
    Vec3,
    CardMaker,
    TextNode,
    TransparencyAttrib,
    Shader, Vec4, Vec3, CardMaker

)
from direct.showbase.ShowBase import ShowBase

from entities.guard.waypoint import Waypoint
from entities.guard.fov_component import FOVComponent, CURIOUS_THRESHOLD, SUSPICIOUS_THRESHOLD
from entities.guard.alert_state import AlertState

# ── patrol constants (unchanged) ──────────────────────────────────────────────
MOVE_SPEED:       float = 4.0
HUNT_SPEED:       float = 7.5    # units/sec while HUNTING or GENERAL_ALARM
ARRIVE_THRESHOLD: float = 0.3
TURN_SPEED:       float = 240.0

# ── state machine timers & rates ──────────────────────────────────────────────
INVESTIGATE_TIME:  float = 5.0    # seconds CURIOUS guard walks to stimulus pos
                                   # before giving up and returning to IDLE
ALERT_FILL_RATE:   float = 35.0   # alert meter units/sec while seeing player
ALERT_DRAIN_RATE:  float = 15.0   # alert meter units/sec when player lost
ALERT_MAX:         float = 100.0  # meter value that triggers HUNTING

# ── body detection ────────────────────────────────────────────────────────────
BODY_DETECT_RANGE: float = 6.0    # units — guard must be this close to notice body
BODY_TAG:          str   = "guard_body"   # NodePath tag key used by GuardManager
# ─────────────────────────────────────────────────────────────────────────────


class Guard:
    """One guard agent: waypoint patrol + vision cone + full alert FSM."""

    _next_id: int = 0

    def __init__(
        self,
        base:      ShowBase,
        waypoints: list[Waypoint],
        *,
        player,
        env,
        name:      str | None = None,
        fov_debug: bool = False,
        on_state_change: Callable[["Guard", AlertState, AlertState], None] | None = None,
        on_hunting:      Callable[["Guard"], None] | None = None,
    ) -> None:
        if not waypoints:
            raise ValueError("Guard requires at least one Waypoint.")

        self._base   = base
        self._player = player
        self._env    = env

        self.waypoints: list[Waypoint] = waypoints
        self.alert_state: AlertState   = AlertState.IDLE
        self.confidence:  float        = 0.0

        self._on_state_change = on_state_change
        self._on_hunting      = on_hunting

        self._id:  int = Guard._next_id
        Guard._next_id += 1
        self.name: str = name or f"Guard_{self._id}"

        # ── FSM internal data ─────────────────────────────────────────────
        self._alert_meter:        float        = 0.0
        self._investigate_timer:  float        = 0.0
        self._last_known_pos:     Point3 | None = None
        self._investigating_pos:  Point3 | None = None

        # ── Guard appearance parts (stored for color updates) ─────────────
        self._guard_parts: list[NodePath] = []

        self.node_path: NodePath = base.render.attachNewNode(self.name)
        self._build_guard_model()

        # ── Label above guard ─────────────────────────────────────────────
        tn = TextNode(self.name + "_label")
        tn.setText(self.name)
        tn.setAlign(TextNode.ACenter)
        label_np = self.node_path.attachNewNode(tn)
        label_np.setScale(0.35)
        label_np.setPos(0.0, 0.0, 2.0)
        label_np.setBillboardPointEye()

        self.node_path.setPos(waypoints[0].position)

        # ── patrol state ──────────────────────────────────────────────────
        self._current_wp_index: int   = 0
        self._waiting:          bool  = False
        self._wait_timer:       float = 0.0

        self._task_patrol = f"guard_patrol_{self._id}"
        self._task_fov    = f"guard_fov_{self._id}"
        self._task_fsm    = f"guard_fsm_{self._id}"

        # ── FOV component ─────────────────────────────────────────────────
        self._fov = FOVComponent(
            base=base,
            guard_np=self.node_path,
            debug_visible=fov_debug,
        )


    # ── Guard Model Construction ──────────────────────────────────────────────

    def _build_guard_model(self) -> None:
        """
        Build a blocky 3D guard from true 6-sided cubes.
        Each cube is 6 CardMaker quads assembled around a centre point.
        No external assets needed.
        """
        self._guard_parts = []

        self._add_cube(
            name="body",
            cx=0, cy=0, cz=0.5,
            sx=0.65, sy=0.55, sz=0.9,
            color=(0.10, 0.12, 0.45, 1.0),
        )
        self._add_cube(
            name="head",
            cx=0, cy=0, cz=1.05,
            sx=0.55, sy=0.50, sz=0.55,
            color=(0.95, 0.80, 0.65, 1.0),
        )
        self._add_cube(
            name="hat_top",
            cx=0, cy=0, cz=1.38,
            sx=0.65, sy=0.60, sz=0.22,
            color=(0.05, 0.05, 0.08, 1.0),
        )
        self._add_cube(
            name="hat_brim",
            cx=0, cy=0.22, cz=1.28,
            sx=0.72, sy=0.28, sz=0.10,
            color=(0.05, 0.05, 0.08, 1.0),
        )
        self._add_cube(
            name="hat_band",
            cx=0, cy=0, cz=1.27,
            sx=0.68, sy=0.62, sz=0.08,
            color=(0.85, 0.70, 0.20, 1.0),
        )
        self._add_cube(
            name="leg_left",
            cx=-0.18, cy=0, cz=-0.05,
            sx=0.28, sy=0.50, sz=0.55,
            color=(0.05, 0.06, 0.20, 1.0),
        )
        self._add_cube(
            name="leg_right",
            cx=0.18, cy=0, cz=-0.05,
            sx=0.28, sy=0.50, sz=0.55,
            color=(0.05, 0.06, 0.20, 1.0),
        )
        self._add_cube(
            name="boot_left",
            cx=-0.18, cy=0.04, cz=-0.55,
            sx=0.32, sy=0.54, sz=0.22,
            color=(0.05, 0.05, 0.05, 1.0),
        )
        self._add_cube(
            name="boot_right",
            cx=0.18, cy=0.04, cz=-0.55,
            sx=0.32, sy=0.54, sz=0.22,
            color=(0.05, 0.05, 0.05, 1.0),
        )
        self._add_cube(
            name="arm_left",
            cx=-0.48, cy=0, cz=0.55,
            sx=0.26, sy=0.38, sz=0.62,
            color=(0.10, 0.12, 0.35, 1.0),
        )
        self._add_cube(
            name="arm_right",
            cx=0.48, cy=0, cz=0.55,
            sx=0.26, sy=0.38, sz=0.62,
            color=(0.10, 0.12, 0.35, 1.0),
        )
        self._add_cube(
            name="hand_left",
            cx=-0.52, cy=0, cz=0.20,
            sx=0.20, sy=0.32, sz=0.22,
            color=(0.05, 0.05, 0.05, 1.0),
        )
        self._add_cube(
            name="hand_right",
            cx=0.52, cy=0, cz=0.20,
            sx=0.20, sy=0.32, sz=0.22,
            color=(0.05, 0.05, 0.05, 1.0),
        )
        self._add_cube(
            name="belt",
            cx=0, cy=0, cz=0.15,
            sx=0.68, sy=0.56, sz=0.09,
            color=(0.55, 0.35, 0.15, 1.0),
        )
        self._add_cube(
            name="buckle",
            cx=0, cy=0.29, cz=0.15,
            sx=0.16, sy=0.06, sz=0.10,
            color=(0.75, 0.75, 0.80, 1.0),
        )
        self._add_cube(
            name="badge",
            cx=0, cy=0.28, cz=0.78,
            sx=0.18, sy=0.06, sz=0.10,
            color=(0.85, 0.70, 0.20, 1.0),
        )
        self._add_cube(
            name="radio",
            cx=-0.50, cy=0.18, cz=0.82,
            sx=0.18, sy=0.22, sz=0.28,
            color=(0.08, 0.08, 0.12, 1.0),
        )
        self._add_cube(
            name="antenna",
            cx=-0.50, cy=0.22, cz=1.06,
            sx=0.05, sy=0.05, sz=0.32,
            color=(0.40, 0.40, 0.45, 1.0),
        )
        self._add_cube(
            name="eye_left",
            cx=-0.14, cy=0.26, cz=1.10,
            sx=0.14, sy=0.06, sz=0.14,
            color=(1.0, 1.0, 1.0, 1.0),
        )
        self._add_cube(
            name="eye_right",
            cx=0.14, cy=0.26, cz=1.10,
            sx=0.14, sy=0.06, sz=0.14,
            color=(1.0, 1.0, 1.0, 1.0),
        )
        self._add_cube(
            name="pupil_left",
            cx=-0.14, cy=0.28, cz=1.10,
            sx=0.07, sy=0.04, sz=0.08,
            color=(0.05, 0.05, 0.05, 1.0),
        )
        self._add_cube(
            name="pupil_right",
            cx=0.14, cy=0.28, cz=1.10,
            sx=0.07, sy=0.04, sz=0.08,
            color=(0.05, 0.05, 0.05, 1.0),
        )
        self._add_cube(
            name="mouth",
            cx=0, cy=0.28, cz=0.98,
            sx=0.18, sy=0.05, sz=0.06,
            color=(0.40, 0.25, 0.15, 1.0),
        )

        # Apply shader to every face if available.
        try:
            shader = Shader.load(
                Shader.SL_GLSL,
                vertex="shaders/slime.vert",
                fragment="shaders/slime.frag",
            )
            for part_np in self._guard_parts:
                part_np.setShader(shader)
                part_np.setShaderInput("light_color",    Vec4(0.7, 0.7, 0.7, 1))
                part_np.setShaderInput("ambient_color",  Vec4(0.3, 0.3, 0.3, 1))
                part_np.setShaderInput("rim_color",      Vec4(0.5, 0.2, 0.1, 1))
                part_np.setShaderInput("rim_power",      3.5)
                part_np.setShaderInput("light_dir_view", Vec3(0, 0, 1))
                part_np.setShaderInput("time",           0.0)
        except Exception:
            pass  # Shader not found — flat colour fallback is fine.

    def _add_cube(
        self,
        name:  str,
        cx: float, cy: float, cz: float,
        sx: float, sy: float, sz: float,
        color: tuple,
    ) -> None:
        """
        Build a true 6-faced box centred at (cx, cy, cz).
        sx/sy/sz are FULL extents (not half).

        Normals are written directly into the GeomVertexData of each face
        after CardMaker generates it — this is the correct Panda3D API.
        Each face also gets an AO brightness multiplier so the model reads
        as solid 3D even without a shader.

        AO multipliers:
          top   1.00  front  0.88  sides  0.74  back  0.62  bottom  0.45
        """
        from panda3d.core import (
            GeomVertexRewriter, InternalName, LColor, Vec3 as V3,
        )

        hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
        r, g, b, a = color

        cube_np = self.node_path.attachNewNode(name)
        cube_np.setPos(cx, cy, cz)
        self._guard_parts.append(cube_np)

        # (suffix, ox, oy, oz, h, p, r_rot, hu, hv, normal_xyz, ao)
        face_defs = [
            ("_front", 0,   hy,   0,    0,    0,   0,  hx, hz, V3( 0,  1,  0), 0.88),
            ("_back",  0,  -hy,   0,  180,    0,   0,  hx, hz, V3( 0, -1,  0), 0.62),
            ("_right", hx,  0,    0,   90,    0,   0,  hy, hz, V3( 1,  0,  0), 0.74),
            ("_left", -hx,  0,    0,  -90,    0,   0,  hy, hz, V3(-1,  0,  0), 0.74),
            ("_top",   0,   0,   hz,    0,  -90,   0,  hx, hy, V3( 0,  0,  1), 1.00),
            ("_bot",   0,   0,  -hz,    0,   90,   0,  hx, hy, V3( 0,  0, -1), 0.45),
        ]

        for suffix, ox, oy, oz, h, p, r_rot, hu, hv, normal, ao in face_defs:
            ao_r, ao_g, ao_b = r * ao, g * ao, b * ao

            cm = CardMaker(name + suffix)
            cm.setFrame(-hu, hu, -hv, hv)
            cm.setHasNormals(True)   # tells CardMaker to include a normal column
            cm.setColor(LColor(ao_r, ao_g, ao_b, a))

            face_np = cube_np.attachNewNode(cm.generate())
            face_np.setPos(ox, oy, oz)
            face_np.setHpr(h, p, r_rot)

            # ── write the correct outward normal into every vertex ─────────
            # CardMaker's setHasNormals generates (0,0,1) for all verts
            # in the card's local space.  After setHpr the geometry is
            # still in local coords, so we must overwrite with the face's
            # actual world-space outward normal.
            node       = face_np.node()
            geom       = node.modifyGeom(0)
            vdata      = geom.modifyVertexData()
            nwriter    = GeomVertexRewriter(vdata, InternalName.getNormal())
            while not nwriter.isAtEnd():
                nwriter.setData3(normal)

    # ── public control ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Register all tasks with taskMgr."""
        self._base.taskMgr.add(self._patrol_task, self._task_patrol)
        self._base.taskMgr.add(self._fov_task,    self._task_fov)
        self._base.taskMgr.add(self._fsm_task,    self._task_fsm)

    def stop(self) -> None:
        """Pause all tasks (position and state preserved)."""
        self._base.taskMgr.remove(self._task_patrol)
        self._base.taskMgr.remove(self._task_fov)
        self._base.taskMgr.remove(self._task_fsm)

    def destroy(self) -> None:
        """Remove guard from scene and cancel all tasks."""
        self.stop()
        self._fov.destroy()
        self.node_path.removeNode()

    def on_sound_event(self, sound_pos: Point3, intensity: float) -> None:
        """Called by GuardManager when a sound event reaches this guard."""
        if self.alert_state in (AlertState.IDLE, AlertState.CURIOUS):
            self._investigating_pos  = Point3(sound_pos)
            self._investigate_timer  = INVESTIGATE_TIME
            self._transition(AlertState.CURIOUS)

    def on_body_spotted(self) -> None:
        """Called by GuardManager when this guard is close to a body node."""
        if self.alert_state in (AlertState.IDLE, AlertState.CURIOUS):
            self._transition(AlertState.SUSPICIOUS)

    # ── tasks ─────────────────────────────────────────────────────────────────

    def _fov_task(self, task):
        self.confidence = self._fov.check(self._player, self._env)
        return task.cont

    def _fsm_task(self, task):
        dt: float = globalClock.getDt()
        
        # Update shader time for all guard parts (fixes the assertion error)
        frame_time = self._base.clock.getFrameTime()
        for part in self._guard_parts:
            part.setShaderInput("time", frame_time)
        
        self._update_fsm(dt)
        self._update_guard_color()
        return task.cont

    def _patrol_task(self, task):
        dt: float = globalClock.getDt()

        speed = (
            HUNT_SPEED if self.alert_state in
            (AlertState.HUNTING, AlertState.GENERAL_ALARM)
            else MOVE_SPEED
        )

        if self.alert_state == AlertState.IDLE:
            destination = self._get_patrol_destination(dt)
            if destination is None:
                return task.cont
        elif self.alert_state == AlertState.CURIOUS:
            destination = self._investigating_pos or self._get_patrol_destination(dt)
            if destination is None:
                return task.cont
        else:
            destination = self._last_known_pos
            if destination is None:
                return task.cont

        self._move_toward(destination, speed, dt)
        return task.cont

    # ── FSM update ────────────────────────────────────────────────────────────

    def _update_fsm(self, dt: float) -> None:
        conf   = self.confidence
        state  = self.alert_state

        if state == AlertState.IDLE:
            self._fsm_idle(conf)
        elif state == AlertState.CURIOUS:
            self._fsm_curious(conf, dt)
        elif state == AlertState.SUSPICIOUS:
            self._fsm_suspicious(conf, dt)
        elif state == AlertState.HUNTING:
            self._fsm_hunting(conf, dt)

    def _fsm_idle(self, conf: float) -> None:
        if conf >= SUSPICIOUS_THRESHOLD:
            self._last_known_pos = self._player.get_position()
            self._transition(AlertState.SUSPICIOUS)
        elif conf > CURIOUS_THRESHOLD:
            self._investigating_pos = self._player.get_position()
            self._investigate_timer = INVESTIGATE_TIME
            self._transition(AlertState.CURIOUS)

    def _fsm_curious(self, conf: float, dt: float) -> None:
        if conf >= SUSPICIOUS_THRESHOLD:
            self._last_known_pos = self._player.get_position()
            self._transition(AlertState.SUSPICIOUS)
            return

        if conf > CURIOUS_THRESHOLD:
            self._investigating_pos = self._player.get_position()
            self._investigate_timer = INVESTIGATE_TIME

        self._investigate_timer -= dt
        if self._investigate_timer <= 0.0:
            self._investigate_timer = 0.0
            self._transition(AlertState.IDLE)

    def _fsm_suspicious(self, conf: float, dt: float) -> None:
        if conf >= SUSPICIOUS_THRESHOLD:
            self._last_known_pos  = self._player.get_position()
            self._alert_meter    += ALERT_FILL_RATE * dt
        else:
            self._alert_meter -= ALERT_DRAIN_RATE * dt

        self._alert_meter = max(0.0, min(ALERT_MAX, self._alert_meter))

        if self._alert_meter >= ALERT_MAX:
            self._transition(AlertState.HUNTING)
        elif self._alert_meter <= 0.0:
            self._transition(AlertState.CURIOUS)

    def _fsm_hunting(self, conf: float, dt: float) -> None:
        if conf >= SUSPICIOUS_THRESHOLD:
            self._last_known_pos = self._player.get_position()

    # ── transition helper ─────────────────────────────────────────────────────

    def _transition(self, new_state: AlertState) -> None:
        if new_state == self.alert_state:
            return

        old_state = self.alert_state
        self.alert_state = new_state

        if new_state == AlertState.CURIOUS:
            self._alert_meter = 0.0
        if new_state == AlertState.HUNTING:
            self._alert_meter = ALERT_MAX

        if self._on_state_change:
            self._on_state_change(self, old_state, new_state)
        if new_state == AlertState.HUNTING and self._on_hunting:
            self._on_hunting(self)

    # ── patrol helpers ────────────────────────────────────────────────────────

    def _get_patrol_destination(self, dt: float) -> Point3 | None:
        if self._waiting:
            self._wait_timer -= dt
            if self._wait_timer <= 0.0:
                self._waiting = False
                self._advance_waypoint()
            return None
        return self.waypoints[self._current_wp_index].position

    def _advance_waypoint(self) -> None:
        self._current_wp_index = (self._current_wp_index + 1) % len(self.waypoints)

    def _move_toward(self, target: Point3, speed: float, dt: float) -> None:
        current: Point3 = self.node_path.getPos()
        to_target: Vec3 = target - current
        distance: float = to_target.length()

        if distance <= ARRIVE_THRESHOLD:
            self.node_path.setPos(target)
            if (self.alert_state == AlertState.IDLE and
                    target == self.waypoints[self._current_wp_index].position):
                wait = self.waypoints[self._current_wp_index].wait_time
                if wait > 0.0:
                    self._waiting    = True
                    self._wait_timer = wait
                else:
                    self._advance_waypoint()
            return

        direction: Vec3  = to_target.normalized()
        step:      float = min(speed * dt, distance)
        self.node_path.setPos(current + direction * step)

        target_h: float  = math.degrees(math.atan2(-direction.x, direction.y))
        current_h: float = self.node_path.getH()
        delta:     float = (target_h - current_h + 180.0) % 360.0 - 180.0
        max_turn:  float = TURN_SPEED * dt
        self.node_path.setH(current_h + max(-max_turn, min(max_turn, delta)))

    # ── visual feedback ───────────────────────────────────────────────────────

    def _update_guard_color(self) -> None:
        """Recolour uniform parts on alert state change, preserving per-face AO."""
        uniform_colors = {
            AlertState.IDLE:          (0.12, 0.15, 0.45),
            AlertState.CURIOUS:       (0.50, 0.45, 0.10),
            AlertState.SUSPICIOUS:    (0.70, 0.35, 0.05),
            AlertState.HUNTING:       (0.85, 0.15, 0.10),
            AlertState.GENERAL_ALARM: (0.70, 0.10, 0.70),
        }
        uniform_parts   = {"body", "arm_left", "arm_right", "leg_left", "leg_right"}
        ao_by_suffix    = {
            "_front": 0.88, "_back": 0.62,
            "_right": 0.74, "_left": 0.74,
            "_top":   1.00, "_bot":  0.45,
        }

        r, g, b = uniform_colors.get(self.alert_state, (0.12, 0.15, 0.45))

        for cube_np in self._guard_parts:
            cube_name = cube_np.getName()

            if any(cube_name == u for u in uniform_parts):
                # Recolour each child face with its AO factor.
                for face_np in cube_np.getChildren():
                    face_name = face_np.getName()
                    ao = next(
                        (v for k, v in ao_by_suffix.items() if face_name.endswith(k)),
                        0.80,
                    )
                    from panda3d.core import LColor
                    face_np.setColor(LColor(r * ao, g * ao, b * ao, 1.0))

            elif "belt" in cube_name and "buckle" not in cube_name:
                intensity = 0.55 + (0.3 if self.alert_state != AlertState.IDLE else 0.0)
                for face_np in cube_np.getChildren():
                    face_name = face_np.getName()
                    ao = next(
                        (v for k, v in ao_by_suffix.items() if face_name.endswith(k)),
                        0.80,
                    )
                    from panda3d.core import LColor
                    face_np.setColor(LColor(
                        intensity * 0.9 * ao,
                        intensity * 0.6 * ao,
                        intensity * 0.3 * ao,
                        1.0,
                    ))

    # ── helpers ───────────────────────────────────────────────────────────────

    def get_position(self) -> Point3:
        return self.node_path.getPos()

    @property
    def alert_meter(self) -> float:
        return self._alert_meter

    def __repr__(self) -> str:
        pos = self.get_position()
        return (
            f"<Guard '{self.name}' {self.alert_state} "
            f"conf={self.confidence:.2f} meter={self._alert_meter:.0f} "
            f"pos=({pos.x:.1f},{pos.y:.1f},{pos.z:.1f})>"
        )