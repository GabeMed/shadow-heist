# Changelog

## Step 2 — Multi-light scene shader
- New `shaders/scene.{vert,frag}` (GLSL 330 core): world-space Blinn-Phong
  lighting with ambient + directional moonlight + up to 16 attenuated
  point lights, supporting `p3d_ColorScale` for camo/highlight effects.
- `core/level_manager.py`: night-mansion mood (cool dim ambient + cool
  moonlight), 5 warm candle PointLights with quadratic attenuation, and a
  per-frame task that scans every `PointLight` under `render` and pushes
  positions/colors/attenuations + camera world position into the scene
  shader uniforms.
- Player slime shader untouched — it still overrides on its own subtree.

## Step 1 — Cleanup & shader baseline
- Removed unused guard AI subsystem (`entities/guard/`, `src/guard/`).
- Removed obsolete entry points `main_test.py`, `main_ai_test.py`.
- Single canonical entry point: `main.py`.
- Bumped slime shader pair to `#version 330 core` (rubric requires ≥330).
- Added `requirements.txt` with pinned `panda3d>=1.10.13`.
- Added `CHANGELOG.md` (this file).
- Forced `gl-version 3 2` PRC flag in `main.py` so the GL Core context supports GLSL 330 (macOS otherwise stays on GL 2.1).
