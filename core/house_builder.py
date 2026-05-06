import math
import random
from pathlib import Path
from dataclasses import dataclass

from panda3d.core import (
    BitMask32,
    CardMaker,
    CollisionBox,
    CollisionNode,
    Geom,
    GeomNode,
    GeomTriangles,
    Filename,
    GeomVertexData,
    GeomVertexFormat,
    GeomVertexWriter,
    PointLight,
    Point3,
    Texture,
    TextureStage,
    TransparencyAttrib,
    Vec3,
    Vec4,
)

import config as Cfg


@dataclass(frozen=True)
class Opening:
    kind: str
    center: float
    width: float
    bottom: float = 0.0
    top: float = 0.0


@dataclass(frozen=True)
class Room:
    name: str
    x1: float
    x2: float
    y1: float
    y2: float
    row: int
    col: int

    @property
    def center(self):
        return Point3((self.x1 + self.x2) * 0.5, (self.y1 + self.y2) * 0.5, 0.0)

    @property
    def width(self):
        return self.x2 - self.x1

    @property
    def depth(self):
        return self.y2 - self.y1


class Door:
    # Far-away coords used to "remove" the blocker's AABB from the raytrace
    # scene when the door is open (cheaper than resizing the PTA array).
    _AABB_OPEN_SENTINEL = (1.0e6, 1.0e6, 1.0e6)

    def __init__(self, name, leaf_np, blocker_np, action_point,
                 closed_h, open_h, blocker_aabb_index=None,
                 blocker_aabb=None, base=None):
        self.name = name
        self.leaf_np = leaf_np
        self.blocker_np = blocker_np
        self.action_point = action_point
        self.closed_h = closed_h
        self.open_h = open_h
        self.is_open = False
        self.closed_mask = BitMask32.bit(1)
        self.open_mask = BitMask32.allOff()
        # Raytraced-shadow bookkeeping.
        self.blocker_aabb_index = blocker_aabb_index
        self.blocker_aabb_closed = blocker_aabb
        self.base = base
        self.set_open(False)

    def set_open(self, is_open):
        self.is_open = is_open
        self.leaf_np.setH(self.open_h if is_open else self.closed_h)
        self.blocker_np.node().setIntoCollideMask(
            self.open_mask if is_open else self.closed_mask
        )
        self._sync_raytrace_aabb()

    def _sync_raytrace_aabb(self):
        # base.level_manager isn't bound until ShadowHeist.__init__ finishes;
        # the initial set_open(False) during construction therefore short-
        # circuits here. By the time the player toggles the door, both base
        # and level_manager exist and we live-update the PTA entry so the
        # shader sees the open hole.
        if self.blocker_aabb_index is None or self.base is None:
            return
        lm = getattr(self.base, "level_manager", None)
        if lm is None or not hasattr(lm, "update_aabb"):
            return
        if self.is_open:
            far = self._AABB_OPEN_SENTINEL
            lm.update_aabb(self.blocker_aabb_index, far, far)
        elif self.blocker_aabb_closed is not None:
            mn, mx = self.blocker_aabb_closed
            lm.update_aabb(self.blocker_aabb_index, mn, mx)

    def toggle(self):
        self.set_open(not self.is_open)

    def distance_to(self, pos):
        dx = self.action_point.x - pos.x
        dy = self.action_point.y - pos.y
        return math.hypot(dx, dy)


class JumpWindowBarrier:
    def __init__(self, collision_np):
        self.collision_np = collision_np
        self.enabled_mask = BitMask32.bit(1)
        self.disabled_mask = BitMask32.allOff()
        self.set_active(True)

    def set_active(self, is_active):
        self.collision_np.node().setIntoCollideMask(
            self.enabled_mask if is_active else self.disabled_mask
        )


class CrouchPassageBarrier:
    def __init__(self, collision_np):
        self.collision_np = collision_np
        self.enabled_mask = BitMask32.bit(1)
        self.disabled_mask = BitMask32.allOff()
        self.set_active(True)

    def set_active(self, is_active):
        self.collision_np.node().setIntoCollideMask(
            self.enabled_mask if is_active else self.disabled_mask
        )


class HouseBuilder:
    def __init__(self, base, parent=None):
        self.base = base
        self.parent = parent or base.render
        self.root = self.parent.attachNewNode("castle_root")

        self.layout_scale = Cfg.HOUSE_LAYOUT_SCALE
        self.wall_height = 8.4
        self.wall_thickness = 0.82
        self.frame_thickness = 0.16
        self.door_height = 3.4
        self.window_sill = 1.45
        self.window_top = 3.25
        self.jump_window_sill = 2.0
        self.jump_window_top = 4.9
        self.crawl_passage_height = 1.55
        self.wall_mask = BitMask32.bit(1)

        self.wall_color = (0.79, 0.78, 0.74, 1.0)
        self.tower_color = (0.70, 0.70, 0.69, 1.0)
        self.frame_color = (0.64, 0.46, 0.30, 1.0)
        self.door_color = (0.50, 0.31, 0.18, 1.0)
        self.column_color = (0.67, 0.66, 0.63, 1.0)
        self.glass_color = (0.56, 0.80, 0.96, 0.42)
        self.jump_trim_color = (0.78, 0.72, 0.62, 1.0)
        self.wall_texture = self._load_wall_texture("parede", "castle_wall_texture")
        self.internal_wall_texture = self._load_wall_texture(
            "parede-interna-2",
            "castle_internal_wall_texture",
        )
        self.floor_textures = [
            self._load_wall_texture("piso-escuro", "castle_floor_dark_texture"),
            self._load_wall_texture("piso-dourado", "castle_floor_gold_texture"),
            self._load_wall_texture("piso-branco", "castle_floor_white_texture"),
        ]
        self.central_carpet_texture = self._load_wall_texture(
            "tapete-central",
            "castle_central_carpet_texture",
        )
        self.door_texture = self._load_image_texture(
            "Planks003_2K-JPG_Color.jpg",
            "castle_door_texture",
        )
        self.torch_model = self._load_torch_model()
        self.beholder_model = self._load_beholder_model()
        for texture in (
            self.wall_texture,
            self.internal_wall_texture,
            *self.floor_textures,
            self.central_carpet_texture,
            self.door_texture,
        ):
            if texture:
                texture.setWrapU(Texture.WM_repeat)
                texture.setWrapV(Texture.WM_repeat)
        self.wall_texture_tile_size = 2.6
        self.floor_texture_tile_size = 2.2
        self.carpet_texture_tile_size = 1.8
        self.floor_colors = [
            (0.53, 0.47, 0.39, 1.0),
            (0.46, 0.48, 0.50, 1.0),
            (0.62, 0.60, 0.52, 1.0),
            (0.44, 0.42, 0.39, 1.0),
            (0.50, 0.44, 0.34, 1.0),
        ]

        self.rooms = []
        self.doors = []
        self.jump_window_barriers = []
        self.crouch_passage_barriers = []
        self.player_spawn = Point3(0, 0, 0)
        self.beholder_np = None
        # Axis-aligned bounding boxes for raytraced shadows. Populated by
        # _create_box when the box is a static, axis-aligned occluder.
        self.aabbs = []

    def build(self):
        self._define_rooms()
        self._create_room_floors()
        self._create_room_ceilings()
        self._create_outer_shell()
        self._create_internal_walls()
        self._create_central_hall_columns()
        self._create_side_towers()
        # Static beholder prop replaced by BeholderManager AI enemies.
        self._create_external_torches()
        self._create_interior_torches()
        self._create_swinging_lantern()
        self._create_castle_battlements()
        self._create_tower_spires()
        self._create_flying_buttresses()
        self._set_player_spawn()
        return self.root

    # ------------------------------------------------------------------
    # Gothic exterior — spires, buttresses.
    # ------------------------------------------------------------------
    def _create_tower_spires(self):
        spire_color = (0.28, 0.30, 0.36, 1.0)
        ridge_color = (0.42, 0.40, 0.36, 1.0)
        # Tower centers from _create_side_towers (footprint half = 4.0).
        towers = [
            (-30.0, -14.0), (-30.0, 6.0), (-30.0, 28.0),
            ( 30.0, -14.0), ( 30.0, 6.0), ( 30.0, 28.0),
        ]
        merlon_top = self.wall_height + 1.1   # match _create_castle_battlements
        for i, (cx, cy) in enumerate(towers):
            base_z = merlon_top + 0.2
            self._create_spire(
                name=f"spire_{i}",
                cx=self._s(cx),
                cy=self._s(cy),
                base_z=base_z,
                base_radius=self._s(3.6),
                height=self._s(5.5),
                sides=8,
                color=spire_color,
            )
            # Small ridge-finial cap on top.
            self._create_box(
                name=f"spire_{i}_finial",
                center=(self._s(cx), self._s(cy), base_z + self._s(5.5) + 0.45),
                size=(0.35, 0.35, 0.9),
                color=ridge_color,
                collide=False,
            )

    def _create_spire(self, name, cx, cy, base_z, base_radius, height, sides, color):
        geom_node = GeomNode(f"{name}_geom")
        fmt = GeomVertexFormat.getV3n3t2()
        vdata = GeomVertexData(f"{name}_vdata", fmt, Geom.UH_static)
        vw = GeomVertexWriter(vdata, "vertex")
        nw = GeomVertexWriter(vdata, "normal")
        tw = GeomVertexWriter(vdata, "texcoord")
        prim = GeomTriangles(Geom.UH_static)

        step = 2.0 * math.pi / sides
        apex_z = base_z + height
        for i in range(sides):
            a0 = step * i
            a1 = step * (i + 1)
            x0, y0 = math.cos(a0) * base_radius, math.sin(a0) * base_radius
            x1, y1 = math.cos(a1) * base_radius, math.sin(a1) * base_radius
            mid_a = (a0 + a1) * 0.5
            # Outward-and-up normal so light catches the slope.
            nx, ny, nz = math.cos(mid_a), math.sin(mid_a), 0.55
            inv = 1.0 / math.sqrt(nx * nx + ny * ny + nz * nz)
            nx, ny, nz = nx * inv, ny * inv, nz * inv

            bi = vw.getWriteRow()
            vw.addData3f(x0, y0, base_z); nw.addData3f(nx, ny, nz); tw.addData2f(i / sides, 0.0)
            vw.addData3f(x1, y1, base_z); nw.addData3f(nx, ny, nz); tw.addData2f((i + 1) / sides, 0.0)
            vw.addData3f(0.0, 0.0, apex_z); nw.addData3f(nx, ny, nz); tw.addData2f((i + 0.5) / sides, 1.0)
            prim.addVertices(bi, bi + 1, bi + 2)

        geom = Geom(vdata)
        geom.addPrimitive(prim)
        geom_node.addGeom(geom)
        np = self.root.attachNewNode(geom_node)
        np.setPos(cx, cy, 0.0)
        np.setColor(*color)
        np.setTwoSided(True)
        return np

    def _create_flying_buttresses(self):
        """Inclined stone beams supporting outer walls — gothic silhouette."""
        beam_color = (0.50, 0.50, 0.52, 1.0)
        breadth = 0.7
        depth = 0.55
        wall_z = self.wall_height
        outward = self._s(3.2)

        # (axis, fixed, alongs[]) — wall normal points outward along +/- fixed axis.
        # Generate buttresses at multiple points along each outer wall.
        layouts = [
            ("y", self._s(-26),  [self._s(v) for v in (-12, 0, 14, 28)], -1.0),  # west wall, normal -X
            ("y", self._s( 26),  [self._s(v) for v in (-12, 0, 14, 28)], +1.0),  # east wall
            ("x", self._s(-20),  [self._s(v) for v in (-22, -10, 10, 22)], -1.0),  # south wall
            ("x", self._s( 32),  [self._s(v) for v in (-12, 0, 12)], +1.0),       # north wall
        ]

        idx = 0
        for axis, fixed, positions, normal_sign in layouts:
            for v in positions:
                if axis == "y":
                    p_top = (fixed,                     v, wall_z * 0.85)
                    p_bot = (fixed + normal_sign * outward, v, 0.0)
                else:
                    p_top = (v, fixed,                     wall_z * 0.85)
                    p_bot = (v, fixed + normal_sign * outward, 0.0)
                self._create_inclined_beam(
                    name=f"buttress_{idx}",
                    p_from=p_top,
                    p_to=p_bot,
                    breadth=breadth,
                    depth=depth,
                    color=beam_color,
                )
                idx += 1

    def _create_inclined_beam(self, name, p_from, p_to, breadth, depth, color):
        dx = p_to[0] - p_from[0]
        dy = p_to[1] - p_from[1]
        dz = p_to[2] - p_from[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 0.05:
            return
        midx = (p_from[0] + p_to[0]) * 0.5
        midy = (p_from[1] + p_to[1]) * 0.5
        midz = (p_from[2] + p_to[2]) * 0.5
        # Heading rotates local +Y to align with horizontal projection of (dx,dy).
        h = math.degrees(math.atan2(-dx, dy))
        horiz = math.sqrt(dx * dx + dy * dy)
        # Pitch tilts the local +Y down toward p_to (negative dz → nose-down).
        p = math.degrees(math.atan2(dz, horiz))

        pivot = self.root.attachNewNode(f"{name}_pivot")
        pivot.setPos(midx, midy, midz)
        pivot.setHpr(h, p, 0.0)
        self._create_box(
            name=name,
            center=(0.0, 0.0, 0.0),
            size=(breadth, length, depth),
            color=color,
            collide=False,
            parent=pivot,
        )

    # ------------------------------------------------------------------
    # Castle battlements — crenellated parapet on outer perimeter.
    # ------------------------------------------------------------------
    def _create_castle_battlements(self):
        merlon_h = 1.1
        merlon_w = 0.9
        merlon_gap = 0.9
        depth = self.wall_thickness
        base_z = self.wall_height

        # (axis, fixed, start, end). Mirror the outer-shell wall layout.
        segments = [
            ("x", self._s(-20), self._s(-26), self._s(26)),    # south_main
            ("x", self._s(32),  self._s(-18), self._s(18)),    # north_main
            ("y", self._s(-26), self._s(-20), self._s(32)),    # west_main
            ("y", self._s(26),  self._s(-20), self._s(32)),    # east_main
            ("x", self._s(24),  self._s(-26), self._s(-18)),   # north_low_west
            ("x", self._s(24),  self._s(18),  self._s(26)),    # north_low_east
        ]
        # Tower outer walls (west cluster x=-30, east cluster x=+30).
        for cx, cy in [(-30.0, -14.0), (-30.0, 6.0), (-30.0, 28.0)]:
            segments.append(("y", self._s(cx - 4.0), self._s(cy - 4.0), self._s(cy + 4.0)))
        for cx, cy in [(30.0, -14.0), (30.0, 6.0), (30.0, 28.0)]:
            segments.append(("y", self._s(cx + 4.0), self._s(cy - 4.0), self._s(cy + 4.0)))

        for axis, fixed, start, end in segments:
            self._create_merlon_run(axis, fixed, start, end, base_z,
                                    merlon_w, merlon_gap, merlon_h, depth)

    def _create_merlon_run(self, axis, fixed, start, end, base_z,
                           merlon_w, gap, merlon_h, depth):
        span = end - start
        period = merlon_w + gap
        if span < merlon_w or period <= 0:
            return
        count = max(1, int(span // period))
        # Center the merlon pattern within the run.
        used = count * merlon_w + (count - 1) * gap
        offset = (span - used) * 0.5
        for i in range(count):
            local = offset + i * period + merlon_w * 0.5
            center_along = start + local
            if axis == "x":
                box_center = (center_along, fixed, base_z + merlon_h * 0.5)
                box_size = (merlon_w, depth, merlon_h)
            else:
                box_center = (fixed, center_along, base_z + merlon_h * 0.5)
                box_size = (depth, merlon_w, merlon_h)
            self._create_box(
                name=f"merlon_{axis}_{int(fixed*10)}_{i}",
                center=box_center,
                size=box_size,
                color=self.tower_color,
                collide=False,
            )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def _load_wall_texture(self, stem, texture_name):
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        raw_path = assets_dir / f"{stem}.rgb"
        raw_meta_path = assets_dir / f"{stem}.rgb.txt"

        if raw_path.exists() and raw_meta_path.exists():
            width, height = self._read_raw_texture_size(raw_meta_path)
            if width > 0 and height > 0:
                texture = Texture(texture_name)
                texture.setup2dTexture(width, height, Texture.T_unsigned_byte, Texture.F_rgb8)
                texture.setRamImageAs(raw_path.read_bytes(), "RGB")
                return texture

        texture_path = assets_dir / f"{stem}.png"
        if not texture_path.exists():
            return None
        try:
            return self.base.loader.loadTexture(Filename.fromOsSpecific(str(texture_path)))
        except OSError:
            return None

    def _load_image_texture(self, filename, texture_name):
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        path = assets_dir / filename
        if not path.exists():
            return None
        try:
            tex = self.base.loader.loadTexture(Filename.fromOsSpecific(str(path)))
        except OSError:
            return None
        if tex:
            tex.setName(texture_name)
        return tex

    def _load_torch_model(self):
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        model_path = assets_dir / "emberlit_torch.egg"
        texture_path = assets_dir / "emberlit_torch_texture.ppm"

        if not model_path.exists():
            return None

        try:
            torch_model = self.base.loader.loadModel(Filename.fromOsSpecific(str(model_path)))
        except OSError:
            return None

        if torch_model.isEmpty():
            return None

        if texture_path.exists():
            try:
                torch_texture = self.base.loader.loadTexture(
                    Filename.fromOsSpecific(str(texture_path))
                )
            except OSError:
                torch_texture = None
            if torch_texture:
                torch_model.setTexture(torch_texture, 1)

        torch_model.setScale(1.2)
        return torch_model

    def _load_beholder_model(self):
        assets_dir = Path(__file__).resolve().parent.parent / "assets"
        model_path = assets_dir / "thousand_eyed_urchin.egg"
        texture_path = assets_dir / "thousand_eyed_urchin_texture.ppm"

        if not model_path.exists():
            return None

        try:
            model = self.base.loader.loadModel(Filename.fromOsSpecific(str(model_path)))
        except OSError:
            return None

        if model.isEmpty():
            return None

        if texture_path.exists():
            try:
                texture = self.base.loader.loadTexture(Filename.fromOsSpecific(str(texture_path)))
            except OSError:
                texture = None
            if texture:
                model.setTexture(texture, 1)

        model.setScale(2.0)
        return model

    def _texture_for_wall_role(self, wall_role):
        if wall_role == "internal" and self.internal_wall_texture:
            return self.internal_wall_texture
        return self.wall_texture

    def _read_raw_texture_size(self, meta_path):
        try:
            width_text, height_text = meta_path.read_text(encoding="utf-8").strip().split()
            return int(width_text), int(height_text)
        except (OSError, ValueError):
            return 0, 0

    def try_toggle_nearest_door(self, player_pos, max_distance):
        nearest = None
        nearest_distance = max_distance

        for door in self.doors:
            distance = door.distance_to(player_pos)
            if distance <= nearest_distance:
                nearest = door
                nearest_distance = distance

        if nearest is None:
            return False

        nearest.toggle()
        return True

    def set_jump_windows_active(self, is_active):
        for barrier in self.jump_window_barriers:
            barrier.set_active(is_active)

    def set_crouch_passages_active(self, is_active):
        for barrier in self.crouch_passage_barriers:
            barrier.set_active(is_active)

    def get_player_spawn(self):
        return Point3(self.player_spawn)

    def get_mirror_spawn_point(self):
        hall = next((room for room in self.rooms if room.name == "salao_central"), None)
        if hall is None:
            return Point3(0.0, 0.0, 0.0)

        carpet_half_width = self._s(2.1)
        carpet_margin_y = self._s(0.9)
        x = random.uniform(-carpet_half_width * 0.9, carpet_half_width * 0.9)
        y = random.uniform(hall.y1 + carpet_margin_y, hall.y2 - carpet_margin_y)
        return Point3(x, y, 0.0)

    def get_beholder_position(self):
        if self.beholder_np is None:
            return None
        return self.beholder_np.getPos(self.root)

    def get_room_centers(self):
        return [room.center for room in self.rooms]

    def get_item_spawn_points(self, count):
        points = []
        offsets = [
            (-0.9, -0.7),
            (0.8, -0.6),
            (-0.6, 0.7),
            (0.7, 0.6),
            (0.0, 0.0),
        ]

        for index in range(count):
            room = self.rooms[index % len(self.rooms)]
            ox, oy = offsets[index % len(offsets)]
            margin_x = min(room.width * 0.22, self._s(2.0))
            margin_y = min(room.depth * 0.22, self._s(2.0))
            x = room.center.x + ox * margin_x
            y = room.center.y + oy * margin_y
            x = max(room.x1 + margin_x, min(room.x2 - margin_x, x))
            y = max(room.y1 + margin_y, min(room.y2 - margin_y, y))
            points.append((x, y))

        return points

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _define_rooms(self):
        self.rooms = [
            self._room("cozinha", -26, -8, -20, -8, 0, 0),
            self._room("portaria", -8, 8, -20, -10, 0, 1),
            self._room("arsenal", 8, 26, -20, -8, 0, 2),
            self._room("ala_oeste", -26, -10, -8, 6, 1, 0),
            self._room("salao_central", -10, 10, -10, 12, 1, 1),
            self._room("ala_leste", 10, 26, -8, 6, 1, 2),
            self._room("despensa", -26, -12, 6, 14, 2, 0),
            self._room("tesouro", 12, 26, 6, 14, 2, 2),
            self._room("arquivo", -26, -18, 14, 24, 3, 0),
            self._room("biblioteca", -18, -12, 14, 24, 3, 1),
            self._room("capela", 12, 18, 14, 24, 3, 2),
            self._room("sacristia", 18, 26, 14, 24, 3, 3),
            self._room("ante_sala_trono", -12, 12, 12, 20, 4, 1),
            self._room("sala_do_trono", -18, 18, 20, 32, 5, 1),
            self._room("galeria_oeste", -26, -18, 24, 32, 5, 0),
            self._room("galeria_leste", 18, 26, 24, 32, 5, 2),
        ]

    def _room(self, name, x1, x2, y1, y2, row, col):
        return Room(
            name=name,
            x1=self._s(x1),
            x2=self._s(x2),
            y1=self._s(y1),
            y2=self._s(y2),
            row=row,
            col=col,
        )

    def _set_player_spawn(self):
        self.player_spawn = Point3(0.0, self._s(-34.0), 0.0)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _create_room_floors(self):
        for index, room in enumerate(self.rooms):
            self.create_floor(
                room.name,
                room.x1,
                room.x2,
                room.y1,
                room.y2,
                self.floor_colors[index % len(self.floor_colors)],
                texture=self._floor_texture_for_room(index, room),
            )

        self._create_central_hall_carpet()

    def _create_room_ceilings(self):
        ceiling_color = (0.32, 0.30, 0.28, 1.0)
        ceiling_texture = self.internal_wall_texture
        z = self.wall_height - 0.04
        for room in self.rooms:
            self.create_ceiling(
                f"{room.name}_ceiling",
                room.x1,
                room.x2,
                room.y1,
                room.y2,
                ceiling_color,
                texture=ceiling_texture,
                z=z,
            )
        # Cover the sealed inner alleys (no Room entry but inside envelope).
        for alley_name, x1_raw, x2_raw in (
            ("alley_west", -12, -10),
            ("alley_east", 10, 12),
        ):
            self.create_ceiling(
                f"{alley_name}_ceiling",
                self._s(x1_raw),
                self._s(x2_raw),
                self._s(6),
                self._s(12),
                ceiling_color,
                texture=ceiling_texture,
                z=z,
            )
            self.create_floor(
                f"{alley_name}_floor",
                self._s(x1_raw),
                self._s(x2_raw),
                self._s(6),
                self._s(12),
                (0.34, 0.32, 0.30, 1.0),
                texture=self.floor_textures[0] if self.floor_textures else None,
            )

    def _floor_texture_for_room(self, index, room):
        if room.name == "salao_central" and len(self.floor_textures) >= 3:
            return self.floor_textures[2]
        return self.floor_textures[index % len(self.floor_textures)]

    def _create_central_hall_carpet(self):
        central_hall = next((room for room in self.rooms if room.name == "salao_central"), None)
        if central_hall is None or self.central_carpet_texture is None:
            return

        carpet_half_width = self._s(2.1)
        carpet_margin_y = self._s(0.9)
        self.create_floor(
            "salao_central_carpet",
            -carpet_half_width,
            carpet_half_width,
            central_hall.y1 + carpet_margin_y,
            central_hall.y2 - carpet_margin_y,
            (1.0, 1.0, 1.0, 1.0),
            texture=self.central_carpet_texture,
            z=0.045,
            texture_tile_size=self.carpet_texture_tile_size,
        )

    def _create_outer_shell(self):
        self._build_wall_run(
            name="south_main",
            axis="x",
            fixed=self._s(-20),
            start=self._s(-26),
            end=self._s(26),
            openings=[
                Opening("window_glass", self._s(-16), self._s(3.2), self.window_sill, self.window_top),
                Opening("door", self._s(0), self._s(2.8), 0.0, self.door_height),
                Opening("window_glass", self._s(16), self._s(3.2), self.window_sill, self.window_top),
            ],
            wall_role="external",
            exterior_side="south",
        )
        self._build_wall_run(
            name="west_main",
            axis="y",
            fixed=self._s(-26),
            start=self._s(-20),
            end=self._s(32),
            openings=[
                Opening("window_jump", self._s(-2), self._s(3.0), self.jump_window_sill, self.jump_window_top),
                Opening("window_glass", self._s(18), self._s(2.8), self.window_sill, self.window_top),
            ],
            wall_role="external",
            exterior_side="west",
        )
        self._build_wall_run(
            name="east_main",
            axis="y",
            fixed=self._s(26),
            start=self._s(-20),
            end=self._s(32),
            openings=[
                Opening("window_jump", self._s(-2), self._s(3.0), self.jump_window_sill, self.jump_window_top),
                Opening("window_glass", self._s(18), self._s(2.8), self.window_sill, self.window_top),
            ],
            wall_role="external",
            exterior_side="east",
        )
        self._build_wall_run(
            name="north_low_west",
            axis="x",
            fixed=self._s(24),
            start=self._s(-26),
            end=self._s(-18),
            openings=[Opening("window_glass", self._s(-22), self._s(2.6), self.window_sill, self.window_top)],
            wall_role="external",
            exterior_side="north",
        )
        self._build_wall_run(
            name="north_low_east",
            axis="x",
            fixed=self._s(24),
            start=self._s(18),
            end=self._s(26),
            openings=[Opening("window_glass", self._s(22), self._s(2.6), self.window_sill, self.window_top)],
            wall_role="external",
            exterior_side="north",
        )
        self.create_wall(
            "north_shoulder_west",
            "y",
            self._s(-18),
            self._s(24),
            self._s(32),
            wall_role="external",
            exterior_side="west",
        )
        self.create_wall(
            "north_shoulder_east",
            "y",
            self._s(18),
            self._s(24),
            self._s(32),
            wall_role="external",
            exterior_side="east",
        )
        self._build_wall_run(
            name="north_main",
            axis="x",
            fixed=self._s(32),
            start=self._s(-18),
            end=self._s(18),
            openings=[
                Opening("window_glass", self._s(-8), self._s(2.8), self.window_sill, self.window_top),
                Opening("window_glass", self._s(8), self._s(2.8), self.window_sill, self.window_top),
            ],
            wall_role="external",
            exterior_side="north",
        )

    def _create_internal_walls(self):
        self._build_wall_run(
            name="kitchen_to_gate",
            axis="y",
            fixed=self._s(-8),
            start=self._s(-20),
            end=self._s(-10),
            openings=[Opening("door", self._s(-15), self._s(1.9), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="armory_to_gate",
            axis="y",
            fixed=self._s(8),
            start=self._s(-20),
            end=self._s(-10),
            openings=[Opening("door", self._s(-15), self._s(1.9), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="gate_to_hall",
            axis="x",
            fixed=self._s(-10),
            start=self._s(-10),
            end=self._s(10),
            openings=[Opening("door", self._s(0), self._s(2.4), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="kitchen_to_west",
            axis="x",
            fixed=self._s(-8),
            start=self._s(-26),
            end=self._s(-10),
            openings=[Opening("door", self._s(-18), self._s(1.9), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="armory_to_east",
            axis="x",
            fixed=self._s(-8),
            start=self._s(10),
            end=self._s(26),
            openings=[Opening("door", self._s(18), self._s(1.9), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="west_to_hall",
            axis="y",
            fixed=self._s(-10),
            start=self._s(-10),
            end=self._s(12),
            openings=[
                Opening("door", self._s(-1), self._s(2.0), 0.0, self.door_height),
            ],
        )
        self._build_wall_run(
            name="east_to_hall",
            axis="y",
            fixed=self._s(10),
            start=self._s(-10),
            end=self._s(12),
            openings=[
                Opening("door", self._s(-1), self._s(2.0), 0.0, self.door_height),
            ],
        )
        self._build_wall_run(
            name="west_to_pantry",
            axis="x",
            fixed=self._s(6),
            start=self._s(-26),
            end=self._s(-10),
            openings=[Opening("crawl", self._s(-19), self._s(2.0), 0.0, self.crawl_passage_height)],
        )
        self._build_wall_run(
            name="east_to_treasury",
            axis="x",
            fixed=self._s(6),
            start=self._s(10),
            end=self._s(26),
            openings=[Opening("crawl", self._s(19), self._s(2.0), 0.0, self.crawl_passage_height)],
        )
        # Seal the void alleys between salao_central and despensa/tesouro:
        # despensa east face (x=-12, y=6..12) and tesouro west face (x=12, y=6..12).
        self.create_wall(
            "alley_west_seal",
            "y",
            self._s(-12),
            self._s(6),
            self._s(12),
            wall_role="internal",
        )
        self.create_wall(
            "alley_east_seal",
            "y",
            self._s(12),
            self._s(6),
            self._s(12),
            wall_role="internal",
        )
        self._build_wall_run(
            name="pantry_to_ante",
            axis="y",
            fixed=self._s(-12),
            start=self._s(12),
            end=self._s(14),
            openings=[Opening("door", self._s(13), self._s(1.7), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="treasury_to_ante",
            axis="y",
            fixed=self._s(12),
            start=self._s(12),
            end=self._s(14),
            openings=[Opening("door", self._s(13), self._s(1.7), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="hall_to_ante",
            axis="x",
            fixed=self._s(12),
            start=self._s(-12),
            end=self._s(12),
            openings=[Opening("door", self._s(0), self._s(2.4), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="west_upper_left",
            axis="x",
            fixed=self._s(14),
            start=self._s(-26),
            end=self._s(-18),
            openings=[Opening("door", self._s(-22), self._s(1.8), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="west_upper_right",
            axis="x",
            fixed=self._s(14),
            start=self._s(-18),
            end=self._s(-12),
            openings=[Opening("door", self._s(-15), self._s(1.7), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="east_upper_left",
            axis="x",
            fixed=self._s(14),
            start=self._s(12),
            end=self._s(18),
            openings=[Opening("door", self._s(15), self._s(1.7), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="east_upper_right",
            axis="x",
            fixed=self._s(14),
            start=self._s(18),
            end=self._s(26),
            openings=[Opening("door", self._s(22), self._s(1.8), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="archive_to_library",
            axis="y",
            fixed=self._s(-18),
            start=self._s(14),
            end=self._s(24),
            openings=[Opening("crawl", self._s(19), self._s(2.0), 0.0, self.crawl_passage_height)],
        )
        self._build_wall_run(
            name="chapel_to_sacristy",
            axis="y",
            fixed=self._s(18),
            start=self._s(14),
            end=self._s(24),
            openings=[Opening("crawl", self._s(19), self._s(2.0), 0.0, self.crawl_passage_height)],
        )
        self._build_wall_run(
            name="archive_to_gallery",
            axis="x",
            fixed=self._s(24),
            start=self._s(-26),
            end=self._s(-18),
            openings=[Opening("door", self._s(-22), self._s(1.7), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="sacristy_to_gallery",
            axis="x",
            fixed=self._s(24),
            start=self._s(18),
            end=self._s(26),
            openings=[Opening("door", self._s(22), self._s(1.7), 0.0, self.door_height)],
        )
        self._build_wall_run(
            name="ante_to_throne",
            axis="x",
            fixed=self._s(20),
            start=self._s(-12),
            end=self._s(12),
            openings=[Opening("door", self._s(0), self._s(2.6), 0.0, self.door_height)],
        )

    def _create_central_hall_columns(self):
        # Box pillars (instead of the older round geom) so each one registers
        # as an AABB and casts crisp star-pattern shadows under wisp lights.
        column_positions = [
            (-6.0, -4.5), ( 6.0, -4.5),
            (-6.0,  4.5), ( 6.0,  4.5),
            (-6.0,  0.0), ( 6.0,  0.0),
            ( 0.0, -4.5), ( 0.0,  4.5),
        ]
        side = self._s(0.65)
        # Reach all the way from the floor card to just under the ceiling so
        # the pendulum lantern's shadow streaks across the wall, not just the
        # lower half.
        height = self.wall_height - 0.08
        for index, (x, y) in enumerate(column_positions):
            self._create_box(
                name=f"central_pillar_{index}",
                center=(self._s(x), self._s(y), height * 0.5 + 0.04),
                size=(side, side, height),
                color=self.column_color,
                collide=True,
                texture=self.internal_wall_texture,
            )

    def _create_side_towers(self):
        towers = [
            ("tower_w_south", (-30.0, -14.0), (8.0, 8.0), 8.6, "west"),
            ("tower_w_mid", (-30.0, 6.0), (8.0, 8.0), 9.0, "west"),
            ("tower_w_north", (-30.0, 28.0), (8.0, 8.0), 8.6, "west"),
            ("tower_e_south", (30.0, -14.0), (8.0, 8.0), 8.6, "east"),
            ("tower_e_mid", (30.0, 6.0), (8.0, 8.0), 9.0, "east"),
            ("tower_e_north", (30.0, 28.0), (8.0, 8.0), 8.6, "east"),
        ]

        for name, (x, y), (w, d), height, outer_side in towers:
            self._create_tower_shell(name, x, y, w, d, height, outer_side)

    def _create_external_torches(self):
        if self.torch_model is None:
            return

        torch_root = self.root.attachNewNode("castle_torches")
        wall_offset = self._s(0.05)
        placements = [
            ((-18.0, self._s(-20.4) - wall_offset, 2.15), 270.0),
            ((-6.0, self._s(-20.4) - wall_offset, 2.15), 270.0),
            ((6.0, self._s(-20.4) - wall_offset, 2.15), 270.0),
            ((18.0, self._s(-20.4) - wall_offset, 2.15), 270.0),
        ]

        for index, (pos, h) in enumerate(placements):
            torch_np = self.torch_model.copyTo(torch_root)
            torch_np.setName(f"castle_torch_{index}")
            torch_np.setPos(*pos)
            torch_np.setH(h)

    def _create_interior_torches(self):
        """Floating arcane wisps — one per room. Mid-air emissive orb plus a
        co-located warm point light. Bobs and drifts via _wisp_anim_task."""
        if getattr(Cfg, "DAYLIGHT_MODE", False):
            return

        from panda3d.core import Shader
        unlit_shader = Shader.load(
            Shader.SL_GLSL,
            vertex="shaders/unlit.vert",
            fragment="shaders/unlit.frag",
        )

        wisp_root = self.root.attachNewNode("castle_wisps")
        light_color = Vec4(4.20, 2.60, 1.00, 1.0)
        light_atten = Vec3(1.0, 0.05, 0.04)
        base_z = 6.6
        self._wisps = []

        for index, room in enumerate(self.rooms):
            # Skip salao_central; the swinging lantern owns this room so its
            # shadows aren't washed out by a static wisp at the same height.
            if room.name == "salao_central":
                continue
            cx = (room.x1 + room.x2) * 0.5
            cy = (room.y1 + room.y2) * 0.5

            wisp_np = wisp_root.attachNewNode(f"wisp_{index}")
            wisp_np.setPos(cx, cy, base_z)

            core = self.base.loader.loadModel("models/misc/sphere")
            core.reparentTo(wisp_np)
            core.setScale(0.32)
            core.setColorScale(2.40, 1.70, 0.80, 1.0)
            core.setShader(unlit_shader, 100)
            core.setLightOff(1)

            halo = self.base.loader.loadModel("models/misc/sphere")
            halo.reparentTo(wisp_np)
            halo.setScale(0.95)
            halo.setColorScale(1.6, 0.85, 0.35, 0.22)
            halo.setTransparency(TransparencyAttrib.M_alpha)
            halo.setBin("transparent", 5)
            halo.setDepthWrite(False)
            halo.setShader(unlit_shader, 100)
            halo.setLightOff(1)

            plight = PointLight(f"wisp_light_{index}")
            plight.setColor(light_color)
            plight.setAttenuation(light_atten)
            light_np = wisp_np.attachNewNode(plight)
            self.base.render.setLight(light_np)

            phase = index * 0.83
            self._wisps.append((wisp_np, cx, cy, base_z, phase))

        self.base.taskMgr.add(self._wisp_anim_task, "castle_wisp_anim")

    def _create_swinging_lantern(self):
        """Pendulum lantern in salao_central (the pillar room). Hangs from
        the ceiling and swings on a sine curve so its hard shadows sweep
        across the pillars and walls live — direct showcase of dynamic
        raytraced omnidirectional point shadows."""
        if getattr(Cfg, "DAYLIGHT_MODE", False):
            return

        sala = next((r for r in self.rooms if r.name == "salao_central"), None)
        if sala is None:
            return

        from panda3d.core import Shader
        unlit_shader = Shader.load(
            Shader.SL_GLSL,
            vertex="shaders/unlit.vert",
            fragment="shaders/unlit.frag",
        )

        cx = (sala.x1 + sala.x2) * 0.5
        cy = (sala.y1 + sala.y2) * 0.5

        pivot = self.root.attachNewNode("throne_lantern_pivot")
        pivot.setPos(cx, cy, self.wall_height - 0.15)

        bob = pivot.attachNewNode("throne_lantern_bob")
        bob.setPos(0.0, 0.0, -3.2)

        core = self.base.loader.loadModel("models/misc/sphere")
        core.reparentTo(bob)
        core.setScale(0.45)
        core.setColorScale(2.80, 2.00, 0.90, 1.0)
        core.setShader(unlit_shader, 100)
        core.setLightOff(1)

        halo = self.base.loader.loadModel("models/misc/sphere")
        halo.reparentTo(bob)
        halo.setScale(1.15)
        halo.setColorScale(2.00, 1.10, 0.45, 0.25)
        halo.setTransparency(TransparencyAttrib.M_alpha)
        halo.setBin("transparent", 5)
        halo.setDepthWrite(False)
        halo.setShader(unlit_shader, 100)
        halo.setLightOff(1)

        plight = PointLight("throne_lantern_light")
        plight.setColor(Vec4(4.50, 2.80, 1.10, 1.0))
        plight.setAttenuation(Vec3(1.0, 0.04, 0.03))
        light_np = bob.attachNewNode(plight)
        self.base.render.setLight(light_np)

        self._throne_lantern_pivot = pivot
        self.base.taskMgr.add(self._throne_lantern_task, "throne_lantern_anim")

    def _throne_lantern_task(self, task):
        if getattr(self.base, "game_paused", True):
            return task.cont
        t = self.base.clock.getFrameTime()
        swing_deg = 24.0 * math.sin(t * 1.15)
        self._throne_lantern_pivot.setR(swing_deg)
        return task.cont

    def _wisp_anim_task(self, task):
        if getattr(self.base, "game_paused", True):
            return task.cont
        t = self.base.clock.getFrameTime()
        for np, cx, cy, bz, phase in self._wisps:
            z = bz + 0.28 * math.sin(t * 1.6 + phase)
            x = cx + 0.22 * math.sin(t * 0.7 + phase * 1.3)
            y = cy + 0.22 * math.cos(t * 0.6 + phase * 1.7)
            np.setPos(x, y, z)
        return task.cont

    def _create_beholder(self):
        if self.beholder_model is None:
            return

        candidate_rooms = [room for room in self.rooms if room.name != "salao_central"]
        if not candidate_rooms:
            return

        room = random.choice(candidate_rooms)
        margin_x = min(room.width * 0.18, self._s(1.8))
        margin_y = min(room.depth * 0.18, self._s(1.8))
        x = random.uniform(room.x1 + margin_x, room.x2 - margin_x)
        y = random.uniform(room.y1 + margin_y, room.y2 - margin_y)

        beholder_root = self.root.attachNewNode("castle_beholder")
        beholder_np = self.beholder_model.copyTo(beholder_root)
        beholder_np.setName("castle_beholder_prop")
        beholder_np.setPos(x, y, self._s(1.0))
        beholder_np.setH(random.uniform(0.0, 360.0))
        self.beholder_np = beholder_np

    def _create_round_pillar(self, name, center, radius, height, sides=12):
        pillar_root = self.root.attachNewNode(name)
        pillar_root.setPos(*center)

        texture = self.internal_wall_texture
        geom_node = GeomNode(f"{name}_geom")
        format_ = GeomVertexFormat.getV3n3t2()
        vdata = GeomVertexData(f"{name}_vdata", format_, Geom.UH_static)
        vwriter = GeomVertexWriter(vdata, "vertex")
        nwriter = GeomVertexWriter(vdata, "normal")
        twriter = GeomVertexWriter(vdata, "texcoord")
        prim = GeomTriangles(Geom.UH_static)

        step = 2.0 * math.pi / sides
        top_z = height * 0.5
        bottom_z = -height * 0.5

        for index in range(sides):
            a0 = step * index
            a1 = step * (index + 1)
            x0, y0 = math.cos(a0) * radius, math.sin(a0) * radius
            x1, y1 = math.cos(a1) * radius, math.sin(a1) * radius
            u0 = index / sides
            u1 = (index + 1) / sides

            base_index = vwriter.getWriteRow()

            vwriter.addData3f(x0, y0, bottom_z)
            nwriter.addData3f(x0, y0, 0.0)
            twriter.addData2f(u0, 0.0)

            vwriter.addData3f(x0, y0, top_z)
            nwriter.addData3f(x0, y0, 0.0)
            twriter.addData2f(u0, 1.0)

            vwriter.addData3f(x1, y1, top_z)
            nwriter.addData3f(x1, y1, 0.0)
            twriter.addData2f(u1, 1.0)

            vwriter.addData3f(x1, y1, bottom_z)
            nwriter.addData3f(x1, y1, 0.0)
            twriter.addData2f(u1, 0.0)

            prim.addVertices(base_index, base_index + 2, base_index + 1)
            prim.addVertices(base_index, base_index + 3, base_index + 2)

        side_geom = Geom(vdata)
        side_geom.addPrimitive(prim)
        geom_node.addGeom(side_geom)
        side_np = pillar_root.attachNewNode(geom_node)
        side_np.setColor(*self.column_color)
        if texture:
            side_np.setTexture(texture, 1)
            side_np.setTexScale(
                TextureStage.getDefault(),
                max((2.0 * math.pi * radius) / self.wall_texture_tile_size, 1.0),
                max(height / self.wall_texture_tile_size, 1.0),
            )

        coll = CollisionNode(f"{name}_coll")
        coll.addSolid(
            CollisionBox(
                Point3(-radius, -radius, bottom_z),
                Point3(radius, radius, top_z),
            )
        )
        coll.setIntoCollideMask(self.wall_mask)
        pillar_root.attachNewNode(coll)

    def _create_tower_shell(self, name, center_x, center_y, width, depth, height, outer_side):
        x1 = self._s(center_x - width * 0.5)
        x2 = self._s(center_x + width * 0.5)
        y1 = self._s(center_y - depth * 0.5)
        y2 = self._s(center_y + depth * 0.5)

        self.create_floor(
            f"{name}_floor",
            x1 + self.wall_thickness,
            x2 - self.wall_thickness,
            y1 + self.wall_thickness,
            y2 - self.wall_thickness,
            (0.42, 0.42, 0.45, 1.0),
        )

        self.create_ceiling(
            f"{name}_ceiling",
            x1 + self.wall_thickness,
            x2 - self.wall_thickness,
            y1 + self.wall_thickness,
            y2 - self.wall_thickness,
            (0.32, 0.30, 0.28, 1.0),
            texture=self.internal_wall_texture,
            z=self.wall_height - 0.04,
        )

        if outer_side == "west":
            self._build_wall_run(
                name=f"{name}_outer",
                axis="y",
                fixed=x1,
                start=y1,
                end=y2,
                openings=[Opening("door", self._s(center_y), self._s(2.2), 0.0, self.door_height)],
                wall_role="external",
                exterior_side="west",
            )
            self._build_wall_run(
                name=f"{name}_inner",
                axis="y",
                fixed=x2,
                start=y1,
                end=y2,
                openings=[Opening("window_glass", self._s(center_y), self._s(2.2), self.window_sill, self.window_top)],
                wall_role="external",
                exterior_side="east",
            )
        else:
            self._build_wall_run(
                name=f"{name}_inner",
                axis="y",
                fixed=x1,
                start=y1,
                end=y2,
                openings=[Opening("window_glass", self._s(center_y), self._s(2.2), self.window_sill, self.window_top)],
                wall_role="external",
                exterior_side="west",
            )
            self._build_wall_run(
                name=f"{name}_outer",
                axis="y",
                fixed=x2,
                start=y1,
                end=y2,
                openings=[Opening("door", self._s(center_y), self._s(2.2), 0.0, self.door_height)],
                wall_role="external",
                exterior_side="east",
            )

        self._build_wall_run(
            name=f"{name}_south",
            axis="x",
            fixed=y1,
            start=x1,
            end=x2,
            openings=[Opening("window_glass", self._s(center_x), self._s(2.0), self.window_sill, self.window_top)],
            wall_role="external",
            exterior_side="south",
        )
        self._build_wall_run(
            name=f"{name}_north",
            axis="x",
            fixed=y2,
            start=x1,
            end=x2,
            openings=[Opening("window_glass", self._s(center_x), self._s(2.0), self.window_sill, self.window_top)],
            wall_role="external",
            exterior_side="north",
        )

    # ------------------------------------------------------------------
    # Geometry assembly
    # ------------------------------------------------------------------

    def create_floor(self, name, x1, x2, y1, y2, color, texture=None, z=0.02, texture_tile_size=None):
        cm = CardMaker(f"{name}_floor")
        cm.setFrame(x1, x2, y1, y2)
        floor = self.root.attachNewNode(cm.generate())
        floor.setP(-90)
        floor.setZ(z)
        if texture:
            texture_tile_size = self.floor_texture_tile_size if texture_tile_size is None else texture_tile_size
            floor.setColor(1.0, 1.0, 1.0, 1.0)
            floor.setTexture(texture, 1)
            floor.setTexScale(
                TextureStage.getDefault(),
                max((x2 - x1) / texture_tile_size, 1.0),
                max((y2 - y1) / texture_tile_size, 1.0),
            )
        else:
            floor.setColor(*color)
        floor.setTwoSided(True)
        return floor

    def create_ceiling(self, name, x1, x2, y1, y2, color, texture=None, z=None, texture_tile_size=None):
        cm = CardMaker(f"{name}_ceiling")
        cm.setFrame(x1, x2, y1, y2)
        ceiling = self.root.attachNewNode(cm.generate())
        # Same orientation as floor (setP(-90) keeps the X/Y mapping intact);
        # rely on setTwoSided so the underside is visible from inside the room.
        ceiling.setP(-90)
        ceiling_z = self.wall_height if z is None else z
        ceiling.setZ(ceiling_z)
        # Register a thin AABB so the ceiling occludes shadow rays in the
        # raytraced lighting pass (otherwise moonlight bleeds through the
        # roof onto interior floors).
        self.aabbs.append((
            (x1, y1, ceiling_z - 0.04),
            (x2, y2, ceiling_z + 0.04),
        ))
        if texture:
            texture_tile_size = self.floor_texture_tile_size if texture_tile_size is None else texture_tile_size
            ceiling.setColor(0.78, 0.76, 0.72, 1.0)
            ceiling.setTexture(texture, 1)
            ceiling.setTexScale(
                TextureStage.getDefault(),
                max((x2 - x1) / texture_tile_size, 1.0),
                max((y2 - y1) / texture_tile_size, 1.0),
            )
        else:
            ceiling.setColor(*color)
        ceiling.setTwoSided(True)
        return ceiling

    def create_wall(
        self,
        name,
        axis,
        fixed,
        start,
        end,
        z_bottom=0.0,
        z_top=None,
        color=None,
        collide=True,
        h=0.0,
        use_wall_texture=None,
        wall_role="internal",
        exterior_side=None,
    ):
        if end <= start:
            return None

        z_top = self.wall_height if z_top is None else z_top
        color = color or self.wall_color
        if use_wall_texture is None:
            use_wall_texture = color in (self.wall_color, self.tower_color)

        if axis == "x":
            center = ((start + end) * 0.5, fixed, (z_bottom + z_top) * 0.5)
            size = (end - start, self.wall_thickness, z_top - z_bottom)
        else:
            center = (fixed, (start + end) * 0.5, (z_bottom + z_top) * 0.5)
            size = (self.wall_thickness, end - start, z_top - z_bottom)

        return self._create_box(
            name=name,
            center=center,
            size=size,
            color=color,
            collide=collide,
            h=h,
            texture=self._texture_for_wall_role(wall_role) if use_wall_texture else None,
        )

    def create_door(
        self,
        name,
        axis,
        fixed,
        center,
        width,
        height=None,
        wall_role="internal",
        exterior_side=None,
    ):
        height = self.door_height if height is None else height
        start = center - width * 0.5
        end = center + width * 0.5

        self.create_wall(
            f"{name}_left_jamb",
            axis,
            fixed,
            start,
            start + self.frame_thickness,
            z_bottom=0.0,
            z_top=height,
            color=self.frame_color,
        )
        self.create_wall(
            f"{name}_right_jamb",
            axis,
            fixed,
            end - self.frame_thickness,
            end,
            z_bottom=0.0,
            z_top=height,
            color=self.frame_color,
        )
        self.create_wall(
            f"{name}_header",
            axis,
            fixed,
            start,
            end,
            z_bottom=height,
            z_top=self.wall_height,
            color=self.wall_color,
            wall_role=wall_role,
            exterior_side=exterior_side,
        )

        leaf_depth = 0.12
        blocker_depth = self.wall_thickness + 0.14
        leaf_height = max(height - 0.15, 2.2)
        # Hinge sits at the inner edge of the left jamb so the leaf swings
        # like a real door instead of pivoting around its own center.
        inner_w = max(width - 2.0 * self.frame_thickness, 0.05)
        hinge_pos = (
            (start + self.frame_thickness, fixed, 0.0) if axis == "x"
            else (fixed, start + self.frame_thickness, 0.0)
        )
        # closed_h orients the pivot so the leaf lies along the wall axis.
        closed_h = 0.0 if axis == "x" else 90.0
        open_h = closed_h - 96.0

        pivot = self.root.attachNewNode(f"{name}_hinge")
        pivot.setPos(*hinge_pos)
        # In pivot-local space the leaf always extends along +X from hinge.
        door_texture = self.door_texture or (self.floor_textures[0] if self.floor_textures else None)
        leaf = self._create_box(
            name=f"{name}_leaf",
            center=(inner_w * 0.5, 0.0, leaf_height * 0.5),
            size=(inner_w, leaf_depth, leaf_height),
            color=(1.0, 1.0, 1.0, 1.0) if door_texture else self.door_color,
            collide=False,
            h=0.0,
            parent=pivot,
            texture=door_texture,
        )
        # Replace the leaf NodePath with the pivot so Door.set_open rotates
        # the hinge instead of the box around its own center.
        leaf = pivot
        blocker = self._create_box(
            name=f"{name}_blocker",
            center=(center, fixed, leaf_height * 0.5) if axis == "x"
            else (fixed, center, leaf_height * 0.5),
            size=(width + 0.10, blocker_depth, leaf_height) if axis == "x"
            else (blocker_depth, width + 0.10, leaf_height),
            color=(0.0, 0.0, 0.0, 0.0),
            collide=True,
            h=closed_h,
        )
        blocker.setTransparency(TransparencyAttrib.M_alpha)
        blocker.setColorScale(1.0, 1.0, 1.0, 0.0)

        # The blocker just registered itself as the most recent AABB; capture
        # its index + closed bounds so the Door can flip the entry on toggle.
        blocker_aabb_index = len(self.aabbs) - 1 if self.aabbs else None
        blocker_aabb_closed = self.aabbs[-1] if self.aabbs else None

        door = Door(
            name=name,
            leaf_np=leaf,
            blocker_np=blocker.find(f"**/{name}_blocker_coll"),
            action_point=Point3(center, fixed, 0.0) if axis == "x"
            else Point3(fixed, center, 0.0),
            closed_h=closed_h,
            open_h=open_h,
            blocker_aabb_index=blocker_aabb_index,
            blocker_aabb=blocker_aabb_closed,
            base=self.base,
        )
        self.doors.append(door)
        return door

    def create_window(
        self,
        name,
        axis,
        fixed,
        center,
        width,
        bottom=None,
        top=None,
        with_glass=True,
        wall_role="internal",
        exterior_side=None,
    ):
        bottom = self.window_sill if bottom is None else bottom
        top = self.window_top if top is None else top
        start = center - width * 0.5
        end = center + width * 0.5

        if with_glass:
            self.create_wall(
                f"{name}_base",
                axis,
                fixed,
                start,
                end,
                z_bottom=0.0,
                z_top=bottom,
                color=self.wall_color,
                wall_role=wall_role,
                exterior_side=exterior_side,
            )

        self.create_wall(
            f"{name}_header",
            axis,
            fixed,
            start,
            end,
            z_bottom=top,
            z_top=self.wall_height,
            color=self.wall_color,
            wall_role=wall_role,
            exterior_side=exterior_side,
        )
        self.create_wall(
            f"{name}_left_frame",
            axis,
            fixed,
            start,
            start + self.frame_thickness,
            z_bottom=0.0 if not with_glass else bottom,
            z_top=top,
            color=self.frame_color,
        )
        self.create_wall(
            f"{name}_right_frame",
            axis,
            fixed,
            end - self.frame_thickness,
            end,
            z_bottom=0.0 if not with_glass else bottom,
            z_top=top,
            color=self.frame_color,
        )

        opening_width = max(width - self.frame_thickness * 2.0, 0.25)
        opening_height = max(top - bottom - 0.1, 0.2)

        if with_glass:
            glass = self._create_box(
                name=f"{name}_glass",
                center=(center, fixed, (bottom + top) * 0.5) if axis == "x"
                else (fixed, center, (bottom + top) * 0.5),
                size=(opening_width, 0.06, opening_height) if axis == "x"
                else (0.06, opening_width, opening_height),
                color=self.glass_color,
                collide=True,
            )
            glass.setTransparency(TransparencyAttrib.M_alpha)
            return glass

        marker = self._create_box(
            name=f"{name}_jump_marker",
            center=(center, fixed, bottom + 0.05) if axis == "x"
            else (fixed, center, bottom + 0.05),
            size=(opening_width, 0.04, 0.08) if axis == "x"
            else (0.04, opening_width, 0.08),
            color=self.jump_trim_color,
            collide=False,
        )
        barrier = self._create_box(
            name=f"{name}_jump_barrier",
            center=(center, fixed, bottom * 0.5) if axis == "x"
            else (fixed, center, bottom * 0.5),
            size=(opening_width, self.wall_thickness, bottom) if axis == "x"
            else (self.wall_thickness, opening_width, bottom),
            color=(0.0, 0.0, 0.0, 0.0),
            collide=True,
        )
        barrier.setTransparency(TransparencyAttrib.M_alpha)
        barrier.setColorScale(1.0, 1.0, 1.0, 0.0)
        self.jump_window_barriers.append(
            JumpWindowBarrier(barrier.find(f"**/{name}_jump_barrier_coll"))
        )
        return marker

    def create_crouch_passage(self, name, axis, fixed, center, width, height=None):
        height = self.crawl_passage_height if height is None else height
        start = center - width * 0.5
        end = center + width * 0.5

        self.create_wall(
            f"{name}_left_jamb",
            axis,
            fixed,
            start,
            start + self.frame_thickness,
            z_bottom=0.0,
            z_top=height,
            color=self.frame_color,
        )
        self.create_wall(
            f"{name}_right_jamb",
            axis,
            fixed,
            end - self.frame_thickness,
            end,
            z_bottom=0.0,
            z_top=height,
            color=self.frame_color,
        )
        self.create_wall(
            f"{name}_header",
            axis,
            fixed,
            start,
            end,
            z_bottom=height,
            z_top=self.wall_height,
            color=self.wall_color,
            collide=False,
        )

        marker = self._create_box(
            name=f"{name}_marker",
            center=(center, fixed, height + 0.06) if axis == "x"
            else (fixed, center, height + 0.06),
            size=(max(width - self.frame_thickness * 2.0, 0.3), 0.06, 0.12) if axis == "x"
            else (0.06, max(width - self.frame_thickness * 2.0, 0.3), 0.12),
            color=self.jump_trim_color,
            collide=False,
        )
        barrier = self._create_box(
            name=f"{name}_crawl_barrier",
            center=(center, fixed, height * 0.5) if axis == "x"
            else (fixed, center, height * 0.5),
            size=(width, self.wall_thickness, height) if axis == "x"
            else (self.wall_thickness, width, height),
            color=(0.0, 0.0, 0.0, 0.0),
            collide=True,
        )
        barrier.setTransparency(TransparencyAttrib.M_alpha)
        barrier.setColorScale(1.0, 1.0, 1.0, 0.0)
        self.crouch_passage_barriers.append(
            CrouchPassageBarrier(barrier.find(f"**/{name}_crawl_barrier_coll"))
        )
        return marker

    def _build_wall_run(
        self,
        name,
        axis,
        fixed,
        start,
        end,
        openings,
        wall_role="internal",
        exterior_side=None,
    ):
        cursor = start

        for index, opening in enumerate(sorted(openings, key=lambda item: item.center)):
            opening_start = max(start, opening.center - opening.width * 0.5)
            opening_end = min(end, opening.center + opening.width * 0.5)

            if opening_start > cursor:
                self.create_wall(
                    f"{name}_segment_{index}",
                    axis,
                    fixed,
                    cursor,
                    opening_start,
                    wall_role=wall_role,
                    exterior_side=exterior_side,
                )

            if opening.kind == "door":
                self.create_door(
                    name=f"{name}_door_{index}",
                    axis=axis,
                    fixed=fixed,
                    center=opening.center,
                    width=opening.width,
                    height=opening.top,
                    wall_role=wall_role,
                    exterior_side=exterior_side,
                )
            elif opening.kind in ("window", "window_glass"):
                self.create_window(
                    name=f"{name}_window_{index}",
                    axis=axis,
                    fixed=fixed,
                    center=opening.center,
                    width=opening.width,
                    bottom=opening.bottom,
                    top=opening.top,
                    with_glass=True,
                    wall_role=wall_role,
                    exterior_side=exterior_side,
                )
            elif opening.kind == "window_jump":
                self.create_window(
                    name=f"{name}_window_{index}",
                    axis=axis,
                    fixed=fixed,
                    center=opening.center,
                    width=opening.width,
                    bottom=opening.bottom,
                    top=opening.top,
                    with_glass=False,
                    wall_role=wall_role,
                    exterior_side=exterior_side,
                )
            elif opening.kind == "crawl":
                self.create_crouch_passage(
                    name=f"{name}_crawl_{index}",
                    axis=axis,
                    fixed=fixed,
                    center=opening.center,
                    width=opening.width,
                    height=opening.top,
                )

            cursor = opening_end

        if cursor < end:
            self.create_wall(
                f"{name}_segment_final",
                axis,
                fixed,
                cursor,
                end,
                wall_role=wall_role,
                exterior_side=exterior_side,
            )

    def _create_box(
        self,
        name,
        center,
        size,
        color,
        collide=True,
        h=0.0,
        texture=None,
        face_textures=None,
        parent=None,
        cast_shadow=None,
    ):
        # Decide whether this box should occlude shadow rays. Default: occlude
        # when collidable AND axis-aligned to a 90° grid (so its world-space
        # AABB still wraps it tightly). Caller may force True/False.
        if cast_shadow is None:
            cast_shadow = collide and (abs(((h % 180.0) + 180.0) % 180.0) < 0.5
                                       or abs(((h % 180.0) + 180.0) % 180.0 - 90.0) < 0.5)
        if cast_shadow and parent is None:
            cx, cy, cz = center
            sx, sy, sz = size
            angle = ((h % 180.0) + 180.0) % 180.0
            if abs(angle - 90.0) < 0.5:
                sx, sy = sy, sx
            half = (sx * 0.5, sy * 0.5, sz * 0.5)
            self.aabbs.append((
                (cx - half[0], cy - half[1], cz - half[2]),
                (cx + half[0], cy + half[1], cz + half[2]),
            ))
        cm = CardMaker(name)
        cm.setFrame(-0.5, 0.5, -0.5, 0.5)

        node = (parent or self.root).attachNewNode(name)
        node.setPos(*center)
        node.setH(h)

        width, depth, height = size

        front = node.attachNewNode(cm.generate())
        front.setScale(width, 1.0, height)
        front.setPos(0.0, -depth * 0.5, 0.0)
        front.setColor(*color)
        front.setTwoSided(True)
        self._apply_box_texture(
            front,
            self._pick_face_texture(texture, face_textures, "front"),
            width,
            height,
        )

        back = node.attachNewNode(cm.generate())
        back.setScale(width, 1.0, height)
        back.setPos(0.0, depth * 0.5, 0.0)
        back.setH(180.0)
        back.setColor(*color)
        back.setTwoSided(True)
        self._apply_box_texture(
            back,
            self._pick_face_texture(texture, face_textures, "back"),
            width,
            height,
        )

        left = node.attachNewNode(cm.generate())
        left.setScale(depth, 1.0, height)
        left.setPos(-width * 0.5, 0.0, 0.0)
        left.setH(90.0)
        left.setColor(*color)
        left.setTwoSided(True)
        self._apply_box_texture(
            left,
            self._pick_face_texture(texture, face_textures, "left"),
            depth,
            height,
        )

        right = node.attachNewNode(cm.generate())
        right.setScale(depth, 1.0, height)
        right.setPos(width * 0.5, 0.0, 0.0)
        right.setH(-90.0)
        right.setColor(*color)
        right.setTwoSided(True)
        self._apply_box_texture(
            right,
            self._pick_face_texture(texture, face_textures, "right"),
            depth,
            height,
        )

        top = node.attachNewNode(cm.generate())
        top.setScale(width, depth, 1.0)
        top.setPos(0.0, 0.0, height * 0.5)
        top.setP(-90.0)
        top.setColor(color[0] * 0.9, color[1] * 0.9, color[2] * 0.9, color[3])
        top.setTwoSided(True)
        self._apply_box_texture(
            top,
            self._pick_face_texture(texture, face_textures, "top"),
            width,
            depth,
        )

        if collide:
            coll = CollisionNode(f"{name}_coll")
            coll.addSolid(
                CollisionBox(
                    Point3(-width * 0.5, -depth * 0.5, -height * 0.5),
                    Point3(width * 0.5, depth * 0.5, height * 0.5),
                )
            )
            coll.setIntoCollideMask(self.wall_mask)
            node.attachNewNode(coll)

        return node

    def _pick_face_texture(self, fallback_texture, face_textures, face_name):
        if face_textures:
            return face_textures.get(face_name)
        return fallback_texture

    def _apply_box_texture(self, face, texture, u_size, v_size):
        if not texture:
            return
        face.setTexture(texture, 1)
        face.setTexScale(
            TextureStage.getDefault(),
            max(u_size / self.wall_texture_tile_size, 1.0),
            max(v_size / self.wall_texture_tile_size, 1.0),
        )

    def _s(self, value):
        return value * self.layout_scale
