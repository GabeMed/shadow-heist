#!/usr/bin/env python3
"""
Convert an OBJ torch model into a Panda3D EGG and generate a simple texture.

Usage:
    python tools/convert_obj_to_egg.py <input.obj> <output.egg> <texture.ppm>
"""

from __future__ import annotations

import math
import sys
from pathlib import Path


def make_texture(texture_path: Path, style: str) -> None:
    width, height = 512, 1024
    data = bytearray()
    data.extend(f"P6\n{width} {height}\n255\n".encode("ascii"))

    for y in range(height):
        v = y / max(height - 1, 1)
        for x in range(width):
            u = x / max(width - 1, 1)

            if style == "mirror":
                frame = 0.0
                if u < 0.14 or u > 0.86 or v < 0.10 or v > 0.92:
                    frame = 1.0
                elif u < 0.20 or u > 0.80 or v < 0.16 or v > 0.86:
                    frame = 0.45

                if frame > 0:
                    r = min(1.0, 0.72 + 0.18 * frame)
                    g = min(1.0, 0.58 + 0.14 * frame)
                    b = min(1.0, 0.18 + 0.05 * frame)
                else:
                    shine = 0.55 + 0.25 * (1.0 - abs(u - 0.5) * 2.0)
                    shine += 0.10 * math.sin(v * math.tau * 1.5)
                    r = min(1.0, shine * 0.95)
                    g = min(1.0, shine * 0.98)
                    b = min(1.0, shine)
            elif style == "beholder":
                moss = 0.18 + 0.18 * (1.0 - v)
                stone = 0.16 + 0.08 * (1.0 - abs(u - 0.5) * 2.0)
                eye = max(0.0, 1.0 - abs(u - 0.5) * 2.4) * max(0.0, 1.0 - abs(v - 0.42) * 3.5)
                vein = 0.05 * math.sin((u * 11.0 + v * 9.0) * math.tau)

                r = min(1.0, stone + 0.20 * eye + moss * 0.35 + vein)
                g = min(1.0, stone * 0.95 + moss * 0.80 + 0.30 * eye)
                b = min(1.0, stone * 1.10 + moss * 0.25 + 0.45 * eye)

                if eye > 0.0:
                    r = min(1.0, r + 0.45 * eye)
                    g = min(1.0, g + 0.18 * eye)
                    b = min(1.0, b + 0.08 * eye)
            else:
                wood = 0.22 + 0.10 * (1.0 - v)
                band = 0.06 if 0.42 < v < 0.55 else 0.0
                ember = max(0.0, 1.0 - abs(u - 0.5) * 2.0) * max(0.0, 1.0 - abs(v - 0.82) * 4.0)

                r = min(1.0, wood + 0.42 * ember + band)
                g = min(1.0, wood * 0.62 + 0.18 * ember + band * 0.7)
                b = min(1.0, wood * 0.28 + 0.05 * ember)

                if v > 0.80:
                    flame = max(0.0, 1.0 - abs(u - 0.5) * 2.2) * max(0.0, 1.0 - (v - 0.80) / 0.20)
                    r = min(1.0, 0.95 * flame + r * (1.0 - flame))
                    g = min(1.0, 0.55 * flame + g * (1.0 - flame))
                    b = min(1.0, 0.15 * flame + b * (1.0 - flame))

                if 0.15 < v < 0.18 or 0.63 < v < 0.66:
                    r *= 0.55
                    g *= 0.55
                    b *= 0.55

            data.extend(bytes((int(r * 255), int(g * 255), int(b * 255))))

    texture_path.parent.mkdir(parents=True, exist_ok=True)
    texture_path.write_bytes(bytes(data))


def parse_obj(obj_path: Path):
    verts = []
    uvs = []
    normals = []
    faces = []

    with obj_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if line.startswith("v "):
                _, x, y, z, *rest = line.split()
                verts.append((float(x), float(y), float(z)))
            elif line.startswith("vt "):
                parts = line.split()
                u = float(parts[1])
                v = float(parts[2]) if len(parts) > 2 else 0.0
                uvs.append((u, v))
            elif line.startswith("vn "):
                _, x, y, z = line.split()[:4]
                normals.append((float(x), float(y), float(z)))
            elif line.startswith("f "):
                tokens = line.split()[1:]
                if len(tokens) < 3:
                    continue
                refs = []
                for token in tokens:
                    parts = token.split("/")
                    v_idx = int(parts[0]) if parts[0] else 0
                    vt_idx = int(parts[1]) if len(parts) > 1 and parts[1] else 0
                    vn_idx = int(parts[2]) if len(parts) > 2 and parts[2] else 0
                    refs.append((v_idx, vt_idx, vn_idx))
                for i in range(1, len(refs) - 1):
                    faces.append((refs[0], refs[i], refs[i + 1]))

    return verts, uvs, normals, faces


def obj_to_egg(obj_path: Path, egg_path: Path, texture_ref: str, asset_name: str) -> None:
    verts, uvs, normals, faces = parse_obj(obj_path)

    transformed_verts = []
    min_y = None
    min_z = None
    for x, y, z in verts:
        px, py, pz = (x, -z, y)
        transformed_verts.append((px, py, pz))
        min_y = py if min_y is None else min(min_y, py)
        min_z = pz if min_z is None else min(min_z, pz)

    vertex_map = {}
    egg_vertices = []
    egg_faces = []

    for tri in faces:
        tri_indices = []
        for ref in tri:
            if ref not in vertex_map:
                v_idx, vt_idx, vn_idx = ref
                pos = transformed_verts[v_idx - 1]
                pos = (pos[0], pos[1] - min_y, pos[2] - min_z)
                uv = uvs[vt_idx - 1] if vt_idx > 0 and vt_idx <= len(uvs) else None
                nrm = normals[vn_idx - 1] if vn_idx > 0 and vn_idx <= len(normals) else None
                vertex_map[ref] = len(egg_vertices)
                egg_vertices.append((pos, uv, nrm))
            tri_indices.append(vertex_map[ref])
        egg_faces.append(tuple(tri_indices))

    with egg_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("<CoordinateSystem> { Z-Up }\n\n")
        fh.write(f"<Texture> {asset_name}_tex {{\n")
        fh.write(f'  "{texture_ref}"\n')
        fh.write("  <Scalar> format { rgb }\n")
        fh.write("  <Scalar> wrapu { clamp }\n")
        fh.write("  <Scalar> wrapv { clamp }\n")
        fh.write("}\n\n")
        fh.write(f"<Group> {asset_name} {{\n")
        fh.write(f"  <VertexPool> {asset_name}_vpool {{\n")

        for index, (pos, uv, nrm) in enumerate(egg_vertices):
            x, y, z = pos
            fh.write(f"    <Vertex> {index} {{\n")
            fh.write(f"      {x:.6f} {y:.6f} {z:.6f}\n")
            if nrm is not None:
                nx, ny, nz = nrm
                length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                fh.write(f"      <Normal> {{ {nx / length:.6f} {ny / length:.6f} {nz / length:.6f} }}\n")
            if uv is not None:
                u, v = uv
                fh.write(f"      <UV> {{ {u:.6f} {v:.6f} }}\n")
            fh.write("    }\n")

        fh.write("  }\n")
        for a, b, c in egg_faces:
            fh.write("  <Polygon> {\n")
            fh.write(f"    <TRef> {{ {asset_name}_tex }}\n")
            fh.write(f"    <VertexRef> {{ {a} {b} {c} <Ref> {{ {asset_name}_vpool }} }}\n")
            fh.write("  }\n")
        fh.write("}\n")


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("Usage: convert_obj_to_egg.py <input.obj> <output.egg> <texture.ppm>", file=sys.stderr)
        return 2

    input_obj = Path(argv[1]).resolve()
    output_egg = Path(argv[2]).resolve()
    texture_path = Path(argv[3]).resolve()

    asset_name = output_egg.stem
    lower_name = asset_name.lower()
    if "mirror" in lower_name:
        texture_style = "mirror"
    elif "sentinel" in lower_name or "urchin" in lower_name or "beholder" in lower_name:
        texture_style = "beholder"
    else:
        texture_style = "torch"

    make_texture(texture_path, texture_style)
    texture_ref = texture_path.relative_to(Path.cwd()).as_posix()
    obj_to_egg(input_obj, output_egg, texture_ref, asset_name)
    print(str(output_egg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
