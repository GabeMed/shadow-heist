def select_patrol_rooms(rooms, count, excluded_names, rng):
    candidates = [room for room in rooms if room.name not in excluded_names]
    rng.shuffle(candidates)
    return candidates[:max(0, min(count, len(candidates)))]


def room_patrol_waypoints(room, margin_ratio=0.14):
    width = room.x2 - room.x1
    depth = room.y2 - room.y1
    margin_x = width * margin_ratio
    margin_y = depth * margin_ratio

    left = room.x1 + margin_x
    right = room.x2 - margin_x
    bottom = room.y1 + margin_y
    top = room.y2 - margin_y

    return [
        (left, bottom, 0.0),
        (right, bottom, 0.0),
        (right, top, 0.0),
        (left, top, 0.0),
    ]
