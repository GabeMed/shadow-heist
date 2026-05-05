# Shadow Heist

Stealth-heist game built in Panda3D for Computer Graphics class.

## Run

```bash
python -m venv .venv
source .venv/bin/activate          # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
python main.py
```

## Controls

| Key | Action |
|-----|--------|
| `WASD` / arrows | Move |
| Mouse | Camera orbit |
| `Lshift` | Crouch |
| `Space` | Jump |
| `Mouse1` | Grab nearest item |
| `E` | Camouflage (1s, 8s cooldown) |
| `Escape` | Pause / menu |
| `C` | Dev free-cam toggle (game must be unpaused) |

## Layout

```
main.py            entry point
config.py          tunable constants
core/              level / scene management
entities/          player + grabbable items
shaders/           GLSL 330 shaders
assets/            models
```

See `CHANGELOG.md` for change log and `docs/techniques.md` (TBD) for the graphics-rubric breakdown.
