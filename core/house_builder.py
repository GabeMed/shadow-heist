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
    Point3,
    Texture,
    TextureStage,
    TransparencyAttrib,
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
    def __init__(self, name, leaf_np, blocker_np, action_point, closed_h, open_h):
        self.name = name
        self.leaf_np = leaf_np
        self.blocker_np = blocker_np
        self.action_point = action_point
        self.closed_h = closed_h
        self.open_h = open_h
        self.is_open = False
        self.closed_mask = BitMask32.bit(1)
        self.open_mask = BitMask32.allOff()
        self.set_open(False)

    def set_open(self, is_open):
        self.is_open = is_open
        self.leaf_np.setH(self.open_h if is_open else self.closed_h)
        self.blocker_np.node().setIntoCollideMask(
            self.open_mask if is_open else self.closed_mask
        )

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
        self.wall_height = 6.2
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
        self.torch_model = self._load_torch_model()
        self.beholder_model = self._load_beholder_model()
        for texture in (
            self.wall_texture,
            self.internal_wall_texture,
            *self.floor_textures,
            self.central_carpet_texture,
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

    def build(self):
        self._define_rooms()
        self._create_room_floors()
        self._create_outer_shell()
        self._create_internal_walls()
        self._create_central_hall_columns()
        self._create_side_towers()
        # Static beholder prop replaced by BeholderManager AI enemies.
        self._create_external_torches()
        self._set_player_spawn()
        return self.root

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
                Opening("crawl", self._s(8), self._s(2.2), 0.0, self.crawl_passage_height),
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
                Opening("window_jump", self._s(8), self._s(2.6), self.jump_window_sill, self.jump_window_top),
            ],
        )
        self._build_wall_run(
            name="west_to_pantry",
            axis="x",
            fixed=self._s(6),
            start=self._s(-26),
            end=self._s(-12),
            openings=[Opening("crawl", self._s(-19), self._s(2.0), 0.0, self.crawl_passage_height)],
        )
        self._build_wall_run(
            name="east_to_treasury",
            axis="x",
            fixed=self._s(6),
            start=self._s(12),
            end=self._s(26),
            openings=[Opening("crawl", self._s(19), self._s(2.0), 0.0, self.crawl_passage_height)],
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
        column_positions = [
            (-5.5, -4.0),
            (5.5, -4.0),
            (-5.5, 4.0),
            (5.5, 4.0),
        ]

        for index, (x, y) in enumerate(column_positions):
            self._create_round_pillar(
                name=f"central_column_{index}",
                center=(self._s(x), self._s(y), 2.4),
                radius=self._s(0.72),
                height=4.8,
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
        closed_h = 0.0 if axis == "x" else 90.0
        open_h = closed_h - 96.0

        leaf = self._create_box(
            name=f"{name}_leaf",
            center=(center, fixed, leaf_height * 0.5) if axis == "x"
            else (fixed, center, leaf_height * 0.5),
            size=(width, leaf_depth, leaf_height) if axis == "x"
            else (leaf_depth, width, leaf_height),
            color=self.door_color,
            collide=False,
            h=closed_h,
        )
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

        door = Door(
            name=name,
            leaf_np=leaf,
            blocker_np=blocker.find(f"**/{name}_blocker_coll"),
            action_point=Point3(center, fixed, 0.0) if axis == "x"
            else Point3(fixed, center, 0.0),
            closed_h=closed_h,
            open_h=open_h,
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
    ):
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
