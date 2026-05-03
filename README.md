# Shadow Heist

**Engine:** Panda3D 1.10+ / Python 3.10+  
**Status:** Phase 3 complete — Guard AI with full alert state machine.

---

## Quick start

```bash
py -3.11 -m venv venv
.\venv\Scripts\activate
pip install panda3d
```

---

## Running the game

```bash
python main.py
```

## Running the guard AI test scene (standalone, no game needed)

```bash
python main_test.py
```

---

---

## Guard AI test controls

| Key | Action |
|-----|--------|
| `WASD` | Move mock player |
| `Q / E` | Decrease / increase size factor (1.0 – 3.0) |
| `C` | Toggle crouching |
| `V` | Toggle camouflage |
| `L` | Toggle global lighting |
| `F` | Fire sound event at player position (radius 10) |
| `B` | Place / remove a body node at (3, 3, 0) |
| `Escape` | Quit |

---

## Guard card colours (test scene)

| Colour | State |
|--------|-------|
| 🟢 Green | IDLE — patrolling |
| 🟡 Yellow | CURIOUS — investigating stimulus |
| 🟠 Orange | SUSPICIOUS — chasing, alert meter filling |
| 🔴 Red | HUNTING — fast chase |
| 🟣 Magenta | GENERAL ALARM — all guards converge |

---

## Guard AI module API

```python
# Instantiate
from entities.guard.guard import Guard
from entities.guard.guard_manager import GuardManager
from entities.guard.waypoint import Waypoint

manager = GuardManager(base)
guard   = Guard(base, waypoints, player=player, env=level_manager)
manager.add_guard(guard)
manager.start()

# From anywhere in the game
manager.register_sound_event(pos=Point3(x,y,z), radius=8.0, intensity=1.0)
manager.get_alert_level()   # → int 0–3
manager.get_all_guards()    # → list[Guard]
```

### Player interface required by guards

```python
player.get_position()     # → Point3
player.get_size_factor()  # → float 1.0–3.0
player.get_is_crouching() # → bool
player.get_is_sprinting() # → bool
player.get_node_path()    # → NodePath
player.is_visible()       # → bool  (False when camouflaged)
```

### Environment interface required by guards

```python
env.is_position_lit(pos)      # → bool
env.get_active_light_nodes()  # → list[NodePath]
env.get_nav_mesh()            # → NodePath
```

### Wall collision tagging (Teammate B)

For guard raycasts to be occluded by your walls, add this to every
solid wall `CollisionNode`:

```python
from panda3d.core import BitMask32
wall_coll_node.setIntoCollideMask(BitMask32.bit(1))
```

---

## What works (Phase 3)

- Guard walks a closed waypoint loop with configurable wait times.
- Raycast vision cone scales with player size and crouching.
- Detection blocked in unlit areas and by wall geometry.
- Camouflage reduces detection confidence to 15 % (not a hard zero).
- Full alert FSM: IDLE → CURIOUS → SUSPICIOUS → HUNTING → GENERAL ALARM.
- Sound events broadcast from anywhere; guards within radius react.
- Body node detection: guard within 6 units of a tagged body → SUSPICIOUS.
- `GuardManager` tracks global alert level (0–3) for HUD / environment.

## Coming in Phase 4

- Swap stubs for real `Player` and `LevelManager` via integration wrappers.
- Unit tests: `tests/test_fov.py`, `tests/test_alert_fsm.py`.
