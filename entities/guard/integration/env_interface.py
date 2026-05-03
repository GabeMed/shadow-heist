# entities/guard/integration/env_interface.py
"""
EnvInterface — Phase 4
-----------------------
Thin adapter that wraps the real LevelManager object (core/level_manager.py)
and exposes exactly the interface the guard module expects.

Same pattern as PlayerInterface:
  - Validates required methods on construction.
  - Falls back to a safe stub if something is missing or broken.
  - Guard code is never aware of which side is active.

Usage (in main.py)
------------------
    from entities.guard.integration.env_interface import EnvInterface
    env_iface = EnvInterface(base.level_manager)
    guard = Guard(base, waypoints, player=player_iface, env=env_iface)
"""

from __future__ import annotations
from panda3d.core import Point3, NodePath


# ── fallback stub ─────────────────────────────────────────────────────────────

class _StubEnv:
    """Used when the real LevelManager is unavailable."""

    def is_position_lit(self, pos: Point3) -> bool: return True
    def get_active_light_nodes(self)        -> list: return []
    def get_nav_mesh(self)        -> NodePath:       return NodePath("stub_nav_fallback")


# ── real adapter ──────────────────────────────────────────────────────────────

class EnvInterface:
    """
    Wraps core.level_manager.LevelManager and exposes the guard interface.

    Parameters
    ----------
    level_manager : a LevelManager instance from core/level_manager.py.
                    Pass None to force fallback mode.
    """

    def __init__(self, level_manager=None) -> None:
        if level_manager is None:
            print(
                "[EnvInterface] WARNING: No LevelManager supplied. "
                "Running in fallback stub mode."
            )
            self._impl    = _StubEnv()
            self._is_stub = True
        else:
            try:
                required = [
                    "is_position_lit",
                    "get_active_light_nodes",
                    "get_nav_mesh",
                ]
                missing = [m for m in required if not hasattr(level_manager, m)]
                if missing:
                    raise AttributeError(
                        f"LevelManager is missing required methods: {missing}\n"
                        f"Add them to core/level_manager.py (see Phase 2 additions)."
                    )
                self._impl    = level_manager
                self._is_stub = False
                print("[EnvInterface] Real LevelManager connected successfully.")
            except Exception as exc:
                print(
                    f"[EnvInterface] WARNING: Failed to connect LevelManager "
                    f"({exc}). Running in fallback stub mode."
                )
                self._impl    = _StubEnv()
                self._is_stub = True

    # ── interface contract ────────────────────────────────────────────────────

    def is_position_lit(self, pos: Point3) -> bool:
        return self._impl.is_position_lit(pos)

    def get_active_light_nodes(self) -> list:
        return self._impl.get_active_light_nodes()

    def get_nav_mesh(self) -> NodePath:
        return self._impl.get_nav_mesh()

    # ── diagnostics ───────────────────────────────────────────────────────────

    @property
    def is_stub(self) -> bool:
        """True if running on the fallback stub rather than the real LevelManager."""
        return self._is_stub

    def __repr__(self) -> str:
        mode = "STUB" if self._is_stub else "REAL"
        return f"<EnvInterface [{mode}]>"