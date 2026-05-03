# entities/guard/fov_component.py
"""
FOVComponent — Phase 3 (const-ray fix)
---------------------------------------
Raycast-based vision cone for a single Guard.

Panda3D constraint (why we rebuild solids each frame)
------------------------------------------------------
CollisionNode.getSolid(i) returns a CONST reference.  Calling any mutating
method on it (setDirection, setOrigin) raises:
    TypeError: Cannot call CollisionRay.set_direction() on a const object.

Fix: store the CollisionNode references and call clearSolids() + addSolid()
each frame with a freshly constructed CollisionRay at the new direction.
This is cheap — CollisionRay is a small value object.

Detection pipeline (unchanged from Phase 2)
-------------------------------------------
1. Distance check  — player within effective_range?
2. Angle check     — player inside cone half-angle?
3. Light check     — env.is_position_lit(player_pos)?
4. Raycast         — at least one ray reaches player unobstructed?
5. Confidence      — ray_ratio × range_factor × angle_factor
6. Camo modifier   — multiply by CAMO_CONFIDENCE_MULT if not visible.

Size scaling:
    effective_range = BASE_RANGE * (0.7 + 0.3 * size_factor)
    effective_angle = BASE_ANGLE * (0.8 + 0.2 * size_factor)

Thresholds (imported by guard.py and the test HUD):
    CURIOUS_THRESHOLD    = 0.15
    SUSPICIOUS_THRESHOLD = 0.55
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
BASE_RANGE: float = 14.0
BASE_ANGLE: float = 60.0
NUM_RAYS:   int   = 9
RAY_HEIGHT_OFFSET: float = 0.9

CROUCH_ANGLE_FACTOR:  float = 0.55
CAMO_CONFIDENCE_MULT: float = 0.15

CURIOUS_THRESHOLD:    float = 0.15
SUSPICIOUS_THRESHOLD: float = 0.55

WALL_BITMASK: BitMask32 = BitMask32.bit(1)
# ─────────────────────────────────────────────────────────────────────────────


class FOVComponent:
    """
    Attached to one Guard.  Call check(player, env) every frame.

    Parameters
    ----------
    base         : running ShowBase.
    guard_np     : the guard's NodePath (position + heading source).
    debug_visible: show ray nodes in the scene for debugging.
    """

    def __init__(
        self,
        base:      ShowBase,
        guard_np:  NodePath,
        *,
        debug_visible: bool = False,
    ) -> None:
        self._base     = base
        self._guard_np = guard_np

        self.last_confidence: float = 0.0
        self.last_ray_hits:   int   = 0

        self._traverser = CollisionTraverser(f"fov_trav_{id(self)}")
        self._handler   = CollisionHandlerQueue()

        # We store CollisionNode wrappers (not the solids).
        # Solids are rebuilt each frame — see _cast_rays.
        self._ray_nodes: list[CollisionNode] = []
        self._ray_nps:   list[NodePath]      = []

        for i in range(NUM_RAYS):
            cn = CollisionNode(f"fov_ray_{id(self)}_{i}")
            # Add a placeholder solid so the node is valid from the start.
            cn.addSolid(CollisionRay(0, 0, RAY_HEIGHT_OFFSET, 0, 1, 0))
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
        Run the vision cone for this frame.

        Parameters
        ----------
        player : satisfies player interface (get_position, get_size_factor,
                 get_is_crouching, is_visible).
        env    : satisfies env interface (is_position_lit).

        Returns
        -------
        float in [0.0, 1.0].
        """
        player_pos:   Point3 = player.get_position()
        size_factor:  float  = player.get_size_factor()
        is_crouching: bool   = player.get_is_crouching()
        is_visible:   bool   = player.is_visible()

        # ── 1. effective range / angle ────────────────────────────────────
        effective_range:      float = BASE_RANGE * (0.7 + 0.3 * size_factor)
        effective_half_angle: float = BASE_ANGLE * (0.8 + 0.2 * size_factor) / 2.0
        if is_crouching:
            effective_half_angle *= CROUCH_ANGLE_FACTOR

        # ── 2. distance ───────────────────────────────────────────────────
        guard_pos = self._guard_np.getPos()
        eye_pos   = Point3(guard_pos.x, guard_pos.y, guard_pos.z + RAY_HEIGHT_OFFSET)
        to_player = player_pos - eye_pos
        flat_dist = math.sqrt(to_player.x ** 2 + to_player.y ** 2)

        if flat_dist > effective_range:
            return self._cache(0.0, 0)

        # ── 3. angle ──────────────────────────────────────────────────────
        heading_rad   = math.radians(self._guard_np.getH())
        guard_forward = Vec3(-math.sin(heading_rad), math.cos(heading_rad), 0.0)
        to_player_flat = Vec3(to_player.x, to_player.y, 0.0)

        if to_player_flat.length() < 1e-6:
            return self._cache(1.0, NUM_RAYS)

        dot             = max(-1.0, min(1.0, guard_forward.dot(to_player_flat.normalized())))
        angle_to_player = math.degrees(math.acos(dot))

        if angle_to_player > effective_half_angle:
            return self._cache(0.0, 0)

        # ── 4. light ──────────────────────────────────────────────────────
        if not env.is_position_lit(player_pos):
            return self._cache(0.0, 0)

        # ── 5. raycast ────────────────────────────────────────────────────
        hits = self._cast_rays(eye_pos, player_pos, effective_half_angle)

        # ── 6. confidence ─────────────────────────────────────────────────
        confidence = self._compute_confidence(
            hits, flat_dist, effective_range,
            angle_to_player, effective_half_angle,
        )

        # ── 7. camo modifier ──────────────────────────────────────────────
        if not is_visible:
            confidence *= CAMO_CONFIDENCE_MULT

        return self._cache(max(0.0, min(1.0, confidence)), hits)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _cast_rays(
        self,
        eye_pos:    Point3,
        player_pos: Point3,
        half_angle: float,
    ) -> int:
        """
        Rebuild each CollisionNode's solid with the correct direction,
        then run a single traversal pass.

        Why rebuild instead of mutate
        ------------------------------
        getSolid() returns a const pointer in Panda3D's C++ layer.
        Python exposes this as a read-only object — any setter raises
        TypeError.  clearSolids() + addSolid() on the *node* (not the
        solid) is always permitted and has negligible overhead for 9 rays.
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

        # Rebuild each ray solid with the new direction.
        for i, bearing_deg in enumerate(angles):
            rad = math.radians(bearing_deg)
            dx  = -math.sin(rad)
            dy  =  math.cos(rad)

            # ── THE FIX ───────────────────────────────────────────────────
            # Do NOT call getSolid(0).setDirection() — that object is const.
            # Instead: clear the node's solid list and add a fresh ray.
            cn = self._ray_nodes[i]
            cn.clearSolids()
            cn.addSolid(CollisionRay(0, 0, RAY_HEIGHT_OFFSET, dx, dy, 0.0))
            # ─────────────────────────────────────────────────────────────

        self._handler.clearEntries()
        self._traverser.traverse(self._base.render)

        # Determine which rays were blocked by a wall closer than the player.
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
        if unobstructed == 0:
            return 0.0
        ray_ratio    = unobstructed / NUM_RAYS
        range_factor = max(0.0, 1.0 - distance / max_range)
        angle_factor = max(0.0, 1.0 - angle_offset / half_angle) if half_angle > 0 else 1.0
        return ray_ratio * range_factor * angle_factor

    def _cache(self, confidence: float, hits: int) -> float:
        self.last_confidence = confidence
        self.last_ray_hits   = hits
        return confidence

    def destroy(self) -> None:
        for ray_np in self._ray_nps:
            if not ray_np.isEmpty():
                self._traverser.removeCollider(ray_np)
                ray_np.removeNode()