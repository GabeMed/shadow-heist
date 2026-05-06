import math


def movement_blocked_by_hit(hit_distance, move_distance, body_radius, skin=0.05):
    return hit_distance <= move_distance + body_radius + skin


def choose_unblocked_direction(direction, is_blocked):
    for candidate in _steering_candidates(direction):
        if not is_blocked(candidate):
            return candidate
    return None


def _steering_candidates(direction):
    x, y = direction
    for angle in (0.0, 35.0, -35.0, 70.0, -70.0, 100.0, -100.0):
        radians = math.radians(angle)
        c = math.cos(radians)
        s = math.sin(radians)
        yield (
            round(x * c - y * s, 6),
            round(x * s + y * c, 6),
        )
