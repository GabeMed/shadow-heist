#!/usr/bin/env python3
"""
Inject vertex colors from an OBJ file (v x y z r g b) into a Panda3D EGG file.

obj2egg discards the optional r g b fields on 'v' lines. This script reads
them and inserts <RGBA> blocks into the matching EGG vertices.

Usage:
    python tools/patch_egg_colors.py <input.obj> <input.egg> <output.egg>
"""
import re
import sys


def _key(x, y, z):
    return (round(float(x), 4), round(float(y), 4), round(float(z), 4))


def build_color_map(obj_path):
    color_map = {}
    with open(obj_path, encoding="utf-8") as fh:
        for line in fh:
            if not line.startswith("v "):
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            key = _key(parts[1], parts[2], parts[3])
            r, g, b = float(parts[4]), float(parts[5]), float(parts[6])
            color_map[key] = (r, g, b)
    return color_map


def patch_egg(egg_path, color_map, out_path):
    VERTEX_START = re.compile(r"^\s*<Vertex>\s+\d+\s*\{")
    CLOSE = re.compile(r"^\s*\}\s*$")
    COORD = re.compile(r"^\s*(-?\d[\d.eE+\-]*)\s+(-?\d[\d.eE+\-]*)\s+(-?\d[\d.eE+\-]*)\s*$")
    RGBA_TAG = re.compile(r"<RGBA>")

    lines = open(egg_path, encoding="utf-8").readlines()
    result = []
    i = 0
    total = len(lines)

    while i < total:
        line = lines[i]
        if VERTEX_START.match(line):
            # Collect the vertex block lines until the matching closing brace
            block = [line]
            i += 1
            depth = 1
            while i < total and depth > 0:
                l = lines[i]
                block.append(l)
                # Count braces to track depth (handles inline {})
                depth += l.count("{") - l.count("}")
                i += 1

            # Find the coordinate line (first bare "x y z" line in block)
            color = None
            for bl in block:
                m = COORD.match(bl)
                if m:
                    k = _key(m.group(1), m.group(2), m.group(3))
                    color = color_map.get(k)
                    break

            if color and not any(RGBA_TAG.search(bl) for bl in block):
                r, g, b = color
                rgba = f"    <RGBA> {{ {r:.6f} {g:.6f} {b:.6f} 1.000000 }}\n"
                # Insert before the last closing brace
                block.insert(-1, rgba)

            result.extend(block)
        else:
            result.append(line)
            i += 1

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.writelines(result)

    matched = sum(1 for l in result if "<RGBA>" in l)
    total_verts = sum(1 for l in result if "<Vertex>" in l and "{" in l)
    print(f"  {matched}/{total_verts} vertices colored")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("Usage: patch_egg_colors.py <input.obj> <input.egg> <output.egg>")
    obj_path, egg_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    print(f"Building color map from {obj_path} ...")
    cmap = build_color_map(obj_path)
    print(f"  {len(cmap)} unique vertex colors found")
    print(f"Patching {egg_path} -> {out_path} ...")
    patch_egg(egg_path, cmap, out_path)
    print("Done.")
