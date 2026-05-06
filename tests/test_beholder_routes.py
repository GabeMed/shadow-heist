import random
import unittest
from dataclasses import dataclass

from core.beholder_routes import room_patrol_waypoints, select_patrol_rooms


@dataclass(frozen=True)
class FakeRoom:
    name: str
    x1: float
    x2: float
    y1: float
    y2: float


class BeholderRoutesTest(unittest.TestCase):
    def test_room_patrol_waypoints_stay_inside_room_with_margin(self):
        room = FakeRoom("library", -10.0, 10.0, 20.0, 40.0)

        waypoints = room_patrol_waypoints(room, margin_ratio=0.25)

        self.assertEqual(
            waypoints,
            [
                (-5.0, 25.0, 0.0),
                (5.0, 25.0, 0.0),
                (5.0, 35.0, 0.0),
                (-5.0, 35.0, 0.0),
            ],
        )

    def test_select_patrol_rooms_excludes_safe_rooms_and_caps_count(self):
        rooms = [
            FakeRoom("portaria", -2.0, 2.0, -2.0, 2.0),
            FakeRoom("cozinha", 0.0, 4.0, 0.0, 4.0),
            FakeRoom("tesouro", 5.0, 9.0, 0.0, 4.0),
            FakeRoom("biblioteca", 10.0, 14.0, 0.0, 4.0),
        ]

        selected = select_patrol_rooms(
            rooms,
            count=10,
            excluded_names={"portaria", "tesouro"},
            rng=random.Random(7),
        )

        self.assertEqual(len(selected), 2)
        self.assertEqual({room.name for room in selected}, {"cozinha", "biblioteca"})


if __name__ == "__main__":
    unittest.main()
