import unittest

from core.beholder_movement import choose_unblocked_direction, movement_blocked_by_hit


class BeholderMovementTest(unittest.TestCase):
    def test_movement_probe_blocks_before_body_reaches_wall(self):
        self.assertTrue(
            movement_blocked_by_hit(
                hit_distance=1.2,
                move_distance=0.35,
                body_radius=1.0,
                skin=0.05,
            )
        )

    def test_movement_probe_allows_clear_step(self):
        self.assertFalse(
            movement_blocked_by_hit(
                hit_distance=2.0,
                move_distance=0.35,
                body_radius=1.0,
                skin=0.05,
            )
        )

    def test_choose_unblocked_direction_sidesteps_blocked_forward(self):
        chosen = choose_unblocked_direction(
            (1.0, 0.0),
            is_blocked=lambda direction: direction == (1.0, 0.0),
        )

        self.assertNotEqual(chosen, (1.0, 0.0))
        self.assertIsNotNone(chosen)

    def test_choose_unblocked_direction_returns_none_when_surrounded(self):
        chosen = choose_unblocked_direction(
            (1.0, 0.0),
            is_blocked=lambda direction: True,
        )

        self.assertIsNone(chosen)


if __name__ == "__main__":
    unittest.main()
