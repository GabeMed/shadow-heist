import math
import random
from enum import Enum, auto

from panda3d.core import (
    NodePath, Vec3, Vec4, Point3, PointLight, CollisionSphere,
    CollisionNode, CollisionSegment, CollisionHandlerQueue, BitMask32,
    LineSegs,
)

import config as Cfg
from core.beholder_movement import choose_unblocked_direction, movement_blocked_by_hit
from core.shadow_pass import SHADOW_CASTER_BIT


class BeholderState(Enum):
    PATROL     = auto()
    SUSPICIOUS = auto()
    ALERT      = auto()


MODEL_HEADING_OFFSET_DEG = 180.0
MODEL_COLOR_SCALE = (0.72, 0.86, 1.25, 1.0)


class Beholder:
    """
    Floating eye enemy. Patrols between waypoints; detects player via
    forward cone + line-of-sight raycast. Camouflage shrinks vision range.

    Detection meter (0..1) integrates over time; reaching 1 triggers ALERT
    and the beholder homes on last-seen position. Touching the player while
    ALERT calls the on_caught callback.
    """

    def __init__(self, base, model_template, waypoints, on_caught,
                 los_traverser=None, los_mask=None):
        self.base          = base
        self.waypoints     = [Point3(*wp) if not isinstance(wp, Point3) else Point3(wp)
                              for wp in waypoints]
        self.on_caught     = on_caught
        self.los_traverser = los_traverser
        self.los_mask      = los_mask

        self.root = base.render.attachNewNode("beholder_root")
        self.model = model_template.copyTo(self.root)
        self.model.setName("beholder_model")
        # The imported mesh faces backward relative to Panda's +Y forward axis.
        self.model.setH(MODEL_HEADING_OFFSET_DEG)
        self.model.setColorScale(*MODEL_COLOR_SCALE)
        self._movement_traverser = getattr(base, "cTrav", None)
        self._movement_pusher = getattr(base, "pusher", None)
        self._coll_np = None
        self._setup_collision()

        self.hover_z   = Cfg.BEHOLDER_HOVER_Z
        self.bob_phase = random.uniform(0.0, math.tau)

        if self.waypoints:
            self.root.setPos(self.waypoints[0].x, self.waypoints[0].y, self.hover_z)
        self.wp_index = 0

        self.state          = BeholderState.PATROL
        self.detection      = 0.0
        self.last_seen_pos  = None
        self.search_timer   = 0.0
        self.scan_phase     = random.uniform(0.0, math.tau)

        # Glow under model — turns red on alert.
        glow = PointLight("beholder_glow")
        glow.setColor(Vec4(0.6, 0.55, 0.10, 1))
        glow.setAttenuation((1.0, 0.18, 0.30))
        self._glow_light = glow
        self._glow_np = self.root.attachNewNode(glow)
        self._glow_np.setPos(0, 0, 0.4)
        self.base.render.setLight(self._glow_np)

        # LOS raycaster (segment cast each frame against wall mask).
        if self.los_traverser is not None:
            self._los_seg = CollisionSegment(0, 0, 0, 0, 1, 0)
            seg_node = CollisionNode("beholder_los")
            seg_node.addSolid(self._los_seg)
            seg_node.setFromCollideMask(self.los_mask if self.los_mask is not None
                                        else BitMask32.bit(1))
            seg_node.setIntoCollideMask(BitMask32.allOff())
            self._los_np = self.root.attachNewNode(seg_node)
            self._los_queue = CollisionHandlerQueue()
            self.los_traverser.addCollider(self._los_np, self._los_queue)
        else:
            self._los_seg = None
            self._los_np = None
            self._los_queue = None

        if self.los_traverser is not None:
            self._move_probe_seg = CollisionSegment(0, 0, 0, 0, 1, 0)
            probe_node = CollisionNode("beholder_move_probe")
            probe_node.addSolid(self._move_probe_seg)
            probe_node.setFromCollideMask(self.los_mask if self.los_mask is not None
                                          else BitMask32.bit(1))
            probe_node.setIntoCollideMask(BitMask32.allOff())
            self._move_probe_np = self.root.attachNewNode(probe_node)
            self._move_probe_queue = CollisionHandlerQueue()
            self.los_traverser.addCollider(self._move_probe_np, self._move_probe_queue)
        else:
            self._move_probe_seg = None
            self._move_probe_np = None
            self._move_probe_queue = None

        # Vision cone debug viz.
        self._cone_np = None
        self._cone_visible = False
        self._rebuild_cone()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def update(self, dt, player_pos, player_camo):
        self._hover_and_bob(dt)

        seen = self._can_see(player_pos, player_camo)

        if seen:
            self.last_seen_pos = Point3(player_pos)
            gain = Cfg.BEHOLDER_DETECT_GAIN * (
                Cfg.BEHOLDER_CAMO_DETECT_MULT if player_camo else 1.0
            )
            self.detection = min(1.0, self.detection + gain * dt)
        else:
            self.detection = max(0.0, self.detection - Cfg.BEHOLDER_DETECT_DECAY * dt)

        # State transitions.
        if self.detection >= 1.0:
            self.state = BeholderState.ALERT
            self.search_timer = Cfg.BEHOLDER_SEARCH_TIME
        elif self.detection >= Cfg.BEHOLDER_SUSPICIOUS_THRESHOLD:
            if self.state != BeholderState.ALERT:
                self.state = BeholderState.SUSPICIOUS
        elif self.state == BeholderState.ALERT:
            self.search_timer -= dt
            if self.search_timer <= 0.0:
                self.state = BeholderState.PATROL
                self.last_seen_pos = None
        elif self.detection <= 0.05:
            self.state = BeholderState.PATROL

        # Behavior.
        if self.state == BeholderState.ALERT:
            self._chase(dt, self.last_seen_pos or player_pos)
            if (player_pos - self.root.getPos()).length() <= Cfg.BEHOLDER_CATCH_RADIUS:
                self.on_caught()
        elif self.state == BeholderState.SUSPICIOUS:
            self._scan(dt, player_pos)
        else:
            self._patrol(dt)

        self._update_glow()
        if self._cone_np is not None and self._cone_visible:
            self._update_cone_color()

    def remove(self):
        if self._glow_np is not None:
            self.base.render.clearLight(self._glow_np)
            self._glow_np.removeNode()
        if self.los_traverser is not None and self._los_np is not None:
            self.los_traverser.removeCollider(self._los_np)
        if self.los_traverser is not None and self._move_probe_np is not None:
            self.los_traverser.removeCollider(self._move_probe_np)
        if self._movement_traverser is not None and self._coll_np is not None:
            self._movement_traverser.removeCollider(self._coll_np)
        if (self._movement_pusher is not None and self._coll_np is not None
                and hasattr(self._movement_pusher, "removeCollider")):
            self._movement_pusher.removeCollider(self._coll_np)
        if self._cone_np is not None:
            self._cone_np.removeNode()
        self.root.removeNode()

    def set_cone_visible(self, visible):
        self._cone_visible = visible
        if self._cone_np is not None:
            if visible:
                self._cone_np.show()
            else:
                self._cone_np.hide()

    def get_pos(self):
        return self.root.getPos()

    # ------------------------------------------------------------------
    # Behaviors
    # ------------------------------------------------------------------

    def _setup_collision(self):
        if self._movement_traverser is None or self._movement_pusher is None:
            return

        coll_node = CollisionNode("beholder_body")
        coll_node.addSolid(CollisionSphere(0, 0, 0, Cfg.BEHOLDER_COLLISION_RADIUS))
        coll_node.setFromCollideMask(self.los_mask if self.los_mask is not None
                                     else BitMask32.bit(1))
        coll_node.setIntoCollideMask(BitMask32.allOff())

        self._coll_np = self.root.attachNewNode(coll_node)
        self._movement_pusher.addCollider(self._coll_np, self.root)
        self._movement_traverser.addCollider(self._coll_np, self._movement_pusher)

    def _patrol(self, dt):
        if not self.waypoints:
            return
        target = self.waypoints[self.wp_index]
        reached = self._move_toward(target, Cfg.BEHOLDER_PATROL_SPEED, dt)

        # Slow scanning rotation around heading even while moving.
        self.scan_phase += dt * Cfg.BEHOLDER_SCAN_FREQ
        scan_offset = math.degrees(math.sin(self.scan_phase) * Cfg.BEHOLDER_SCAN_AMPL_RAD)
        self.root.setH(self.root, scan_offset * dt * 4.0)

        if reached:
            self.wp_index = (self.wp_index + 1) % len(self.waypoints)

    def _scan(self, dt, player_pos):
        # Stop and rotate to look around — biased toward last seen pos.
        if self.last_seen_pos is not None:
            self._face_toward(self.last_seen_pos, dt,
                              speed=Cfg.BEHOLDER_TURN_SPEED * 0.6)
        else:
            self.scan_phase += dt * Cfg.BEHOLDER_SCAN_FREQ * 2.0
            self.root.setH(self.root,
                           math.degrees(math.sin(self.scan_phase)) * dt * 6.0)

    def _chase(self, dt, target_pos):
        self._move_toward(Point3(target_pos.x, target_pos.y, self.hover_z),
                          Cfg.BEHOLDER_CHASE_SPEED, dt)

    def _move_toward(self, target, speed, dt):
        pos = self.root.getPos()
        flat_target = Vec3(target.x, target.y, self.hover_z)
        delta = flat_target - Vec3(pos.x, pos.y, self.hover_z)
        dist = delta.length()
        if dist < 0.05:
            return True
        delta.normalize()
        step = min(speed * dt, dist)
        # Face movement direction.
        target_h = math.degrees(math.atan2(-delta.x, delta.y))
        self._set_heading_smooth(target_h, dt, Cfg.BEHOLDER_TURN_SPEED)
        self._move_flat(delta, step)

        new_pos = self.root.getPos()
        remaining = flat_target - Vec3(new_pos.x, new_pos.y, self.hover_z)
        return remaining.length() < 0.25

    def _move_flat(self, direction, distance):
        if distance <= 1e-6:
            return

        steps = max(1, int(math.ceil(distance / Cfg.BEHOLDER_MOVE_MAX_STEP)))
        step = distance / steps
        for _ in range(steps):
            move_direction = self._choose_move_direction(direction, step)
            if move_direction is None:
                return
            pos = self.root.getPos()
            self.root.setPos(
                pos.x + move_direction.x * step,
                pos.y + move_direction.y * step,
                pos.z,
            )
            if self._movement_traverser is not None:
                self._movement_traverser.traverse(self.base.render)

    def _choose_move_direction(self, direction, step):
        chosen = choose_unblocked_direction(
            (direction.x, direction.y),
            lambda candidate: self._movement_blocked(
                Vec3(candidate[0], candidate[1], 0.0),
                step,
            ),
        )
        if chosen is None:
            return None
        return Vec3(chosen[0], chosen[1], 0.0)

    def _movement_blocked(self, direction, step):
        if self._move_probe_seg is None or self.los_traverser is None:
            return False

        pos = self.root.getPos()
        probe_distance = step + Cfg.BEHOLDER_COLLISION_RADIUS + 0.05
        end = Point3(
            pos.x + direction.x * probe_distance,
            pos.y + direction.y * probe_distance,
            pos.z,
        )
        local_end = self.root.getRelativePoint(self.base.render, end)

        self._move_probe_seg.setPointA(0, 0, 0)
        self._move_probe_seg.setPointB(local_end.x, local_end.y, 0)
        self._move_probe_queue.clearEntries()
        self.los_traverser.traverse(self.base.render)
        if self._move_probe_queue.getNumEntries() == 0:
            return False

        self._move_probe_queue.sortEntries()
        hit = self._move_probe_queue.getEntry(0)
        hit_pos = hit.getSurfacePoint(self.base.render)
        hit_distance = (Vec3(hit_pos.x - pos.x, hit_pos.y - pos.y, 0.0)).length()
        return movement_blocked_by_hit(
            hit_distance,
            step,
            Cfg.BEHOLDER_COLLISION_RADIUS,
        )

    def _face_toward(self, target, dt, speed):
        pos = self.root.getPos()
        dx = target.x - pos.x
        dy = target.y - pos.y
        if abs(dx) < 1e-4 and abs(dy) < 1e-4:
            return
        target_h = math.degrees(math.atan2(-dx, dy))
        self._set_heading_smooth(target_h, dt, speed)

    def _set_heading_smooth(self, target_h, dt, speed):
        cur = self.root.getH()
        diff = ((target_h - cur + 540.0) % 360.0) - 180.0
        step = speed * dt
        if abs(diff) <= step:
            self.root.setH(target_h)
        else:
            self.root.setH(cur + math.copysign(step, diff))

    def _hover_and_bob(self, dt):
        self.bob_phase += dt * Cfg.BEHOLDER_BOB_FREQ
        z = self.hover_z + math.sin(self.bob_phase) * Cfg.BEHOLDER_BOB_AMPL
        p = self.root.getPos()
        self.root.setPos(p.x, p.y, z)

    # ------------------------------------------------------------------
    # Vision
    # ------------------------------------------------------------------

    def _can_see(self, player_pos, player_camo):
        pos = self.root.getPos()
        delta = Vec3(player_pos.x - pos.x, player_pos.y - pos.y, 0.0)
        dist = delta.length()

        max_range = Cfg.BEHOLDER_SIGHT_RANGE
        if player_camo:
            max_range *= Cfg.BEHOLDER_CAMO_RANGE_MULT
        if dist > max_range:
            return False
        if dist < 0.01:
            return True

        # Cone check.
        h_rad = math.radians(self.root.getH())
        forward = Vec3(-math.sin(h_rad), math.cos(h_rad), 0.0)
        delta_n = Vec3(delta)
        delta_n.normalize()
        cos_angle = forward.dot(delta_n)
        cos_fov = math.cos(math.radians(Cfg.BEHOLDER_SIGHT_FOV_DEG * 0.5))
        if cos_angle < cos_fov:
            return False

        # LOS raycast (optional).
        if self._los_seg is not None and self.los_traverser is not None:
            # Segment local to root: from a bit above pivot to player offset.
            local_target = self.root.getRelativePoint(self.base.render, player_pos)
            self._los_seg.setPointA(0, 0, 0.4)
            self._los_seg.setPointB(local_target.x, local_target.y, local_target.z + 0.5)
            self._los_queue.clearEntries()
            self.los_traverser.traverse(self.base.render)
            if self._los_queue.getNumEntries() > 0:
                self._los_queue.sortEntries()
                hit = self._los_queue.getEntry(0)
                hit_world = hit.getSurfacePoint(self.base.render)
                hit_dist = (Vec3(hit_world.x - pos.x,
                                 hit_world.y - pos.y, 0.0)).length()
                if hit_dist + 0.2 < dist:
                    return False
        return True

    # ------------------------------------------------------------------
    # Visuals
    # ------------------------------------------------------------------

    def _update_glow(self):
        if self.state == BeholderState.ALERT:
            self._glow_light.setColor(Vec4(1.6, 0.15, 0.10, 1))
        elif self.state == BeholderState.SUSPICIOUS:
            self._glow_light.setColor(Vec4(1.4, 0.95, 0.10, 1))
        else:
            self._glow_light.setColor(Vec4(0.55, 0.50, 0.10, 1))

    def _rebuild_cone(self):
        if self._cone_np is not None:
            self._cone_np.removeNode()

        ls = LineSegs("beholder_cone")
        ls.setThickness(2.0)
        ls.setColor(1.0, 0.85, 0.2, 0.9)

        rng = Cfg.BEHOLDER_SIGHT_RANGE
        half_fov = math.radians(Cfg.BEHOLDER_SIGHT_FOV_DEG * 0.5)
        steps = 14
        # Apex.
        ls.moveTo(0, 0, 0)
        ls.drawTo(0, rng, 0)
        ls.moveTo(0, 0, 0)
        # Arc.
        prev = None
        for i in range(steps + 1):
            t = -half_fov + (2 * half_fov) * i / steps
            x = math.sin(t) * rng
            y = math.cos(t) * rng
            if prev is None:
                ls.moveTo(0, 0, 0)
                ls.drawTo(x, y, 0)
            else:
                ls.drawTo(x, y, 0)
            prev = (x, y)
        # Close back to apex on last edge.
        ls.drawTo(0, 0, 0)

        node = ls.create()
        self._cone_np = self.root.attachNewNode(node)
        self._cone_np.setZ(0.05)
        self._cone_np.setLightOff()
        self._cone_np.setShaderOff()
        self._cone_np.setTransparency(True)
        self._cone_np.hide(BitMask32.bit(SHADOW_CASTER_BIT))
        if not self._cone_visible:
            self._cone_np.hide()

    def _update_cone_color(self):
        if self._cone_np is None:
            return
        if self.state == BeholderState.ALERT:
            r, g, b = 1.0, 0.15, 0.15
        elif self.state == BeholderState.SUSPICIOUS:
            r, g, b = 1.0, 0.85, 0.15
        else:
            r, g, b = 0.4, 0.85, 0.4
        a = 0.35 + 0.45 * self.detection
        self._cone_np.setColorScale(r, g, b, a)
