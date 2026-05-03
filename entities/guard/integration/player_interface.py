# entities/guard/integration/player_interface.py
"""
PlayerInterface — Phase 4
--------------------------
Thin adapter that wraps the real Player object (entities/player.py)
and exposes exactly the interface the guard module expects.

Why a wrapper and not a direct reference?
-----------------------------------------
The guard module was developed against a stub.  The real Player has a
richer API (animation states, shader inputs, jump physics, etc.) that
the guards should never depend on.  This wrapper is the only file that
knows about both sides — changing Player internals never touches guard
code, and vice versa.

Fallback behaviour
------------------
If the real player module cannot be imported (e.g. a teammate's file is
missing or broken), PlayerInterface falls back to _StubPlayer so the
guard module keeps running.  A clear warning is printed to the console.

Usage (in main.py)
------------------
    from entities.guard.integration.player_interface import PlayerInterface
    player_iface = PlayerInterface(base.player)
    guard = Guard(base, waypoints, player=player_iface, env=env_iface)
"""

from __future__ import annotations
from panda3d.core import Point3, NodePath


# ── fallback stub (mirrors _StubPlayer from the test scene) ──────────────────

class _StubPlayer:
    """Used when the real Player is unavailable."""

    def __init__(self) -> None:
        self._pos = Point3(0, 0, 0)

    def get_position(self)     -> Point3:   return Point3(self._pos)
    def get_size_factor(self)  -> float:    return 1.0
    def get_is_sprinting(self) -> bool:     return False
    def get_is_crouching(self) -> bool:     return False
    def get_node_path(self)    -> NodePath: return NodePath("stub_player_fallback")
    def is_visible(self)       -> bool:     return True


# ── real adapter ──────────────────────────────────────────────────────────────

class PlayerInterface:
    """
    Wraps entities.player.Player and exposes the guard interface contract.

    Parameters
    ----------
    player : a Player instance from entities/player.py.
             Pass None to force fallback mode (useful in unit tests).
    """

    def __init__(self, player=None) -> None:
        if player is None:
            print(
                "[PlayerInterface] WARNING: No player object supplied. "
                "Running in fallback stub mode."
            )
            self._impl = _StubPlayer()
            self._is_stub = True
        else:
            try:
                # Validate that the required interface methods exist.
                required = [
                    "get_position", "get_size_factor", "get_is_sprinting",
                    "get_is_crouching", "get_node_path", "is_visible",
                ]
                missing = [m for m in required if not hasattr(player, m)]
                if missing:
                    raise AttributeError(
                        f"Player object is missing required methods: {missing}\n"
                        f"Add them to entities/player.py (see Phase 2 additions)."
                    )
                self._impl    = player
                self._is_stub = False
                print("[PlayerInterface] Real Player connected successfully.")
            except Exception as exc:
                print(
                    f"[PlayerInterface] WARNING: Failed to connect real Player "
                    f"({exc}). Running in fallback stub mode."
                )
                self._impl    = _StubPlayer()
                self._is_stub = True

    # ── interface contract (identical signatures to the stub) ─────────────────

    def get_position(self) -> Point3:
        return self._impl.get_position()

    def get_size_factor(self) -> float:
        return self._impl.get_size_factor()

    def get_is_sprinting(self) -> bool:
        return self._impl.get_is_sprinting()

    def get_is_crouching(self) -> bool:
        return self._impl.get_is_crouching()

    def get_node_path(self) -> NodePath:
        return self._impl.get_node_path()

    def is_visible(self) -> bool:
        return self._impl.is_visible()

    # ── diagnostics ───────────────────────────────────────────────────────────

    @property
    def is_stub(self) -> bool:
        """True if running on the fallback stub rather than the real player."""
        return self._is_stub

    def __repr__(self) -> str:
        mode = "STUB" if self._is_stub else "REAL"
        return f"<PlayerInterface [{mode}]>"