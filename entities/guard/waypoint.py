# entities/guard/waypoint.py
"""
Waypoint dataclass.
A guard's patrol route is a list of Waypoint instances.

Fields:
    position  -- Panda3D Point3, world-space position the guard walks to.
    wait_time -- seconds the guard idles at this waypoint before moving on.
                 Set to 0.0 for a pass-through point with no pause.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from panda3d.core import Point3


@dataclass
class Waypoint:
    position: Point3
    wait_time: float = 2.0          # default: 2-second pause at each stop

    def __repr__(self) -> str:
        p = self.position
        return (
            f"Waypoint(pos=({p.x:.1f}, {p.y:.1f}, {p.z:.1f}), "
            f"wait={self.wait_time}s)"
        )