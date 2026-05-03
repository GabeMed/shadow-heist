# src/guard/fov_component.py
"""
FOVComponent — Phase 2
-----------------------
Raycast-based vision cone for a single Guard.

How detection works
-------------------
Every frame `check()` fires NUM_RAYS collision rays spread evenly across
the guard's horizontal field of view.  A ray counts as unobstructed when
it reaches the player without hitting a wall collider first.

A non-zero confidence is returned only when ALL of the following hold:

  1. Player's world position is within effective_range of the guard's eye.
  2. Player's position is within the effective cone half-angle.
  3. env.is_position_lit(player_pos) returns True.
  4. At least one ray reaches the player unobstructed.

Camouflage modifier
-------------------
If player.is_visible() returns False, the raw confidence is multiplied by
CAMO_CONFIDENCE_MULT (default 0.15).  A guard that literally walks into
the player can still barely notice them — feels more game-like than a
hard zero.

Crouching modifier
------------------
If player.get_is_crouching() is True, the effective half-angle is
multiplied by CROUCH_ANGLE_FACTOR, making edge-of-cone detection harder.

Size scaling (from design doc)
------------------------------
  effective_range = BASE_RANGE * (0.7 + 0.3 * size_factor)
  effective_angle = BASE_ANGLE * (0.8 + 0.2 * size_factor)

Confidence formula
------------------
  ray_ratio    = unobstructed_rays / NUM_RAYS
  range_factor = 1.0 − (distance / effective_range)
  angle_factor = 1.0 − (angle_offset / effective_half_angle)
  confidence   = ray_ratio × range_factor × angle_factor
                 × (CAMO_CONFIDENCE_MULT if camouflaged else 1.0)

Return value: float in [0.0, 1.0] consumed by the state machine (Phase 3).

Thresholds (used by Guard state machine in Phase 3):
  confidence < CURIOUS_THRESHOLD      → no reaction
  confidence < SUSPICIOUS_THRESHOLD   → transition to CURIOUS
  confidence >= SUSPICIOUS_THRESHOLD  → transition to SUSPICIOUS

Wall occlusion
--------------
Any CollisionNode tagged into WALL_BITMASK (BitMask32.bit(1)) blocks rays.
The LevelManager's CollisionBox obstacles already use the default into-mask,
so we set wall geometry to bit(1) explicitly.

Ask Teammate B (when real env arrives) to ensure all solid wall
CollisionNodes include:
    wall_coll_node.setIntoCollideMask(BitMask32.bit(1))
"""

from __future__ import annotations
import math

from panda3d.core import (
    CollisionTraverser,
    CollisionNode,
    CollisionRay,
    CollisionHandlerQueue,
    Point3,
    Vec3,
    NodePath,
    BitMask32,
)
from direct.showbase.ShowBase import ShowBase

# ── tuneable constants ────────────────────────────────────────────────────────
BASE_RANGE: float  = 14.0   # units — unmodified sight distance
BASE_ANGLE: float  = 60.0   # degrees — full cone width (±30° each side)
NUM_RAYS:   int    = 9      # odd keeps one ray perfectly centred
RAY_HEIGHT_OFFSET: float = 0.9  # units above guard origin — approximate eye level

CROUCH_ANGLE_FACTOR:    float = 0.55   # cone shrinks to 55 % when player crouches
CAMO_CONFIDENCE_MULT:   float = 0.15   # camouflage reduces confidence to 15 %

# State-machine thresholds — imported by guard.py and the test HUD.
CURIOUS_THRESHOLD:    float = 0.15
SUSPICIOUS_THRESHOLD: float = 0.55

# Collision bitmask for wall geometry.
# Must match what LevelManager / Teammate B sets on wall CollisionNodes.
WALL_BITMASK: BitMask32 = BitMask32.bit(1)
# ─────────────────────────────────────────────────────────────────────────────


class FOVComponent:
    """
    Attached to one Guard.  Call check(player, env) every frame.

    Parameters
    ----------
    base         : running ShowBase — needed for CollisionTraverser.
    guard_np     : the guard's NodePath (position + heading source).
    debug_visible: if True, ray collision nodes are shown in the scene.
    """

    def __init__(
        self,
        base: ShowBase,
        guard_np: NodePath,
        *,
        debug_visible: bool = False,
    ) -> None:
        self._base       = base
        self._guard_np   = guard_np
        self._debug      = debug_visible

        # Cached results readable by the HUD / state machine.
        self.last_confidence: float = 0.0
        self.last_ray_hits:   int   = 0

        # ── collision setup ───────────────────────────────────────────────
        self._traverser = CollisionTraverser(f"fov_trav_{id(self)}")
        self._handler   = CollisionHandlerQueue()

        self._ray_nodes: list[CollisionNode] = []
        self._ray_nps:   list[NodePath]      = []

        for i in range(NUM_RAYS):
            ray = CollisionRay()
            ray.setOrigin(0, 0, RAY_HEIGHT_OFFSET)
            ray.setDirection(0, 1, 0)          # updated every frame

            cn = CollisionNode(f"fov_ray_{id(self)}_{i}")
            cn.addSolid(ray)
            cn.setFromCollideMask(WALL_BITMASK)
            cn.setIntoCollideMask(BitMask32.allOff())

            ray_np = guard_np.attachNewNode(cn)
            if not debug_visible:
                ray_np.hide()

            self._traverser.addCollider(ray_np, self._handler)
            self._ray_nodes.append(cn)
            self._ray_nps.append(ray_np)

    # ── public API ────────────────────────────────────────────────────────────

    def check(self, player, env) -> float:
        """
        Run vision cone for this frame.

        Parameters
        ----------
        player : any object satisfying the player interface contract.
                 Required methods: get_position, get_size_factor,
                 get_is_crouching, is_visible.
        env    : any object satisfying the env interface contract.
                 Required methods: is_position_lit.

        Returns
        -------
        float in [0.0, 1.0] — detection confidence this frame.
        """
        player_pos:  Point3 = player.get_position()
        size_factor: float  = player.get_size_factor()
        is_crouching: bool  = player.get_is_crouching()
        is_visible:   bool  = player.is_visible()

        # ── 1. effective range and angle (scale with size_factor) ─────────
        effective_range:      float = BASE_RANGE * (0.7 + 0.3 * size_factor)
        effective_half_angle: float = BASE_ANGLE * (0.8 + 0.2 * size_factor) / 2.0

        if is_crouching:
            effective_half_angle *= CROUCH_ANGLE_FACTOR

        # ── 2. distance check ─────────────────────────────────────────────
        guard_pos: Point3 = self._guard_np.getPos()
        eye_pos = Point3(
            guard_pos.x,
            guard_pos.y,
            guard_pos.z + RAY_HEIGHT_OFFSET,
        )
        to_player = player_pos - eye_pos
        flat_dist = math.sqrt(to_player.x ** 2 + to_player.y ** 2)

        if flat_dist > effective_range:
            self._cache(0.0, 0)
            return 0.0

        # ── 3. angle check ────────────────────────────────────────────────
        guard_heading_rad = math.radians(self._guard_np.getH())
        guard_forward = Vec3(
            -math.sin(guard_heading_rad),
             math.cos(guard_heading_rad),
             0.0,
        )
        to_player_flat = Vec3(to_player.x, to_player.y, 0.0)

        if to_player_flat.length() < 1e-6:
            # Guard is standing on the player — maximum confidence.
            self._cache(1.0, NUM_RAYS)
            return 1.0

        dot = guard_forward.dot(to_player_flat.normalized())
        dot = max(-1.0, min(1.0, dot))
        angle_to_player = math.degrees(math.acos(dot))

        if angle_to_player > effective_half_angle:
            self._cache(0.0, 0)
            return 0.0

        # ── 4. light check ────────────────────────────────────────────────
        if not env.is_position_lit(player_pos):
            self._cache(0.0, 0)
            return 0.0

        # ── 5. raycast occlusion ──────────────────────────────────────────
        hits = self._cast_rays(eye_pos, player_pos, effective_half_angle)

        # ── 6. confidence ─────────────────────────────────────────────────
        confidence = self._compute_confidence(
            hits, flat_dist, effective_range,
            angle_to_player, effective_half_angle,
        )

        # ── 7. camouflage modifier ────────────────────────────────────────
        if not is_visible:
            confidence *= CAMO_CONFIDENCE_MULT

        confidence = max(0.0, min(1.0, confidence))
        self._cache(confidence, hits)
        return confidence

    # ── internal helpers ──────────────────────────────────────────────────────

    def _cast_rays(
        self,
        eye_pos:    Point3,
        player_pos: Point3,
        half_angle: float,
    ) -> int:
        """
        Spread NUM_RAYS across the cone centred on the direction to the player.
        Returns the number of rays that reach the player without hitting a wall.
        """
        to_player_flat = Vec3(
            player_pos.x - eye_pos.x,
            player_pos.y - eye_pos.y,
            0.0,
        )
        centre_bearing = math.degrees(
            math.atan2(-to_player_flat.x, to_player_flat.y)
        )

        if NUM_RAYS == 1:
            angles = [centre_bearing]
        else:
            angles = [
                centre_bearing - half_angle
                + (2.0 * half_angle * i / (NUM_RAYS - 1))
                for i in range(NUM_RAYS)
            ]

        dist_to_player = (player_pos - eye_pos).length()

        # Update each ray's direction before the single traversal pass.
        for i, bearing_deg in enumerate(angles):
            rad = math.radians(bearing_deg)
            direction = Vec3(-math.sin(rad), math.cos(rad), 0.0)
            ray: CollisionRay = self._ray_nodes[i].getSolid(0)
            ray.setDirection(direction)
            ray.setOrigin(Point3(0, 0, RAY_HEIGHT_OFFSET))

        self._handler.clearEntries()
        self._traverser.traverse(self._base.render)

        # Mark which ray indices are blocked by a wall closer than the player.
        blocked: set[int] = set()
        for entry in self._handler.entries:
            hit_np = entry.getFromNodePath()
            try:
                idx = self._ray_nps.index(hit_np)
            except ValueError:
                continue
            hit_pos  = entry.getSurfacePoint(self._base.render)
            hit_dist = (hit_pos - eye_pos).length()
            if hit_dist < dist_to_player - 0.3:
                blocked.add(idx)

        return max(0, NUM_RAYS - len(blocked))

    def _compute_confidence(
        self,
        unobstructed: int,
        distance:     float,
        max_range:    float,
        angle_offset: float,
        half_angle:   float,
    ) -> float:
        """
        Combine ray coverage, distance falloff, and angular falloff into
        a single value in [0.0, 1.0].
        """
        if unobstructed == 0:
            return 0.0

        ray_ratio    = unobstructed / NUM_RAYS
        range_factor = max(0.0, 1.0 - distance / max_range)
        angle_factor = max(0.0, 1.0 - angle_offset / half_angle) if half_angle > 0 else 1.0

        return ray_ratio * range_factor * angle_factor

    def _cache(self, confidence: float, hits: int) -> None:
        self.last_confidence = confidence
        self.last_ray_hits   = hits

    # ── cleanup ───────────────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Remove all ray collision nodes from the scene graph."""
        for ray_np in self._ray_nps:
            if not ray_np.isEmpty():
                self._traverser.removeCollider(ray_np)
                ray_np.removeNode()