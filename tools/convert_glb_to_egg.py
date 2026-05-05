#!/usr/bin/env python3
"""
Convert a GLB model into OBJ/MTL, extract embedded textures, and build an EGG.

This keeps the pipeline local and avoids depending on an external GLB importer.

Usage:
    python tools/convert_glb_to_egg.py <input.glb> <output_dir> <base_name>

Example:
    python tools/convert_glb_to_egg.py assets/model.glb assets/torch torch
"""

from __future__ import annotations

import base64
import json
import math
import struct
import sys
from dataclasses import dataclass
from pathlib import Path


COMPONENT_TYPES = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}

TYPE_COMPONENTS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


@dataclass(frozen=True)
class AccessorData:
    values: list


def read_glb(path: Path):
    data = path.read_bytes()
    magic, version, total_length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2:
        raise ValueError("Input is not a GLB 2.0 file")
    if total_length != len(data):
        raise ValueError("GLB length mismatch")

    offset = 12
    json_chunk = None
    bin_chunk = None
    while offset < len(data):
        chunk_length, chunk_type = struct.unpack_from("<I4s", data, offset)
        offset += 8
        chunk = data[offset : offset + chunk_length]
        offset += chunk_length
        if chunk_type == b"JSON":
            json_chunk = chunk
        elif chunk_type == b"BIN\x00":
            bin_chunk = chunk

    if json_chunk is None or bin_chunk is None:
        raise ValueError("GLB is missing JSON or BIN chunk")

    return json.loads(json_chunk), bin_chunk


def component_reader(component_type: int):
    if component_type not in COMPONENT_TYPES:
        raise ValueError(f"Unsupported accessor component type: {component_type}")
    fmt, size = COMPONENT_TYPES[component_type]
    return fmt, size


def decode_accessor(gltf: dict, bin_chunk: bytes, accessor_index: int):
    accessor = gltf["accessors"][accessor_index]
    buffer_view = gltf["bufferViews"][accessor["bufferView"]]
    fmt, component_size = component_reader(accessor["componentType"])
    component_count = TYPE_COMPONENTS[accessor["type"]]
    count = accessor["count"]

    view_offset = buffer_view.get("byteOffset", 0)
    accessor_offset = accessor.get("byteOffset", 0)
    stride = buffer_view.get("byteStride", component_size * component_count)
    start = view_offset + accessor_offset
    values = []
    for index in range(count):
        item_offset = start + index * stride
        unpack_fmt = "<" + fmt * component_count
        unpacked = struct.unpack_from(unpack_fmt, bin_chunk, item_offset)
        if component_count == 1:
            values.append(unpacked[0])
        else:
            values.append(unpacked)
    return AccessorData(values)


def transform_point(matrix, point):
    x, y, z = point
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    )


def transform_vector(matrix, vector):
    x, y, z = vector
    return (
        matrix[0] * x + matrix[4] * y + matrix[8] * z,
        matrix[1] * x + matrix[5] * y + matrix[9] * z,
        matrix[2] * x + matrix[6] * y + matrix[10] * z,
    )


def gltf_to_panda_point(point):
    x, y, z = point
    return (x, -z, y)


def gltf_to_panda_vector(vector):
    x, y, z = vector
    return (x, -z, y)


def extract_image(gltf: dict, bin_chunk: bytes, image_index: int, out_dir: Path, base_name: str):
    image = gltf["images"][image_index]
    if "bufferView" in image:
        buffer_view = gltf["bufferViews"][image["bufferView"]]
        start = buffer_view.get("byteOffset", 0)
        end = start + buffer_view["byteLength"]
        image_bytes = bin_chunk[start:end]
        mime = image.get("mimeType", "")
        ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(mime, ".bin")
        out_path = out_dir / f"{base_name}_image_{image_index}{ext}"
        out_path.write_bytes(image_bytes)
        return out_path

    uri = image.get("uri")
    if uri and uri.startswith("data:"):
        header, encoded = uri.split(",", 1)
        mime = header.split(";")[0][5:]
        ext = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
        }.get(mime, ".bin")
        out_path = out_dir / f"{base_name}_image_{image_index}{ext}"
        out_path.write_bytes(base64.b64decode(encoded))
        return out_path

    raise ValueError(f"Unsupported image source for image {image_index}")


def write_obj(gltf: dict, bin_chunk: bytes, out_dir: Path, base_name: str):
    meshes = gltf.get("meshes", [])
    if not meshes:
        raise ValueError("GLB has no meshes")

    nodes = gltf.get("nodes", [])
    node = nodes[0] if nodes else {}
    matrix = node.get("matrix")
    if matrix is None:
        matrix = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]

    mesh = meshes[node.get("mesh", 0)]
    obj_path = out_dir / f"{base_name}.obj"
    mtl_path = out_dir / f"{base_name}.mtl"

    texture_paths = []
    for image_index in range(len(gltf.get("images", []))):
        texture_paths.append(extract_image(gltf, bin_chunk, image_index, out_dir, base_name))

    material = mesh["primitives"][0].get("material", 0) if mesh.get("primitives") else 0
    material_def = gltf.get("materials", [])[material] if gltf.get("materials") else {}
    with mtl_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"newmtl {base_name}\n")
        fh.write("Kd 1.000000 1.000000 1.000000\n")
        fh.write("Ka 0.000000 0.000000 0.000000\n")
        fh.write("Ks 0.000000 0.000000 0.000000\n")
        fh.write("Ns 1.000000\n")
        if texture_paths:
            fh.write(f"map_Kd {texture_paths[0].relative_to(Path.cwd()).as_posix()}\n")

    with obj_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"mtllib {mtl_path.name}\n")

        for primitive in mesh.get("primitives", []):
            position_data = decode_accessor(gltf, bin_chunk, primitive["attributes"]["POSITION"]).values
            normal_data = None
            if "NORMAL" in primitive["attributes"]:
                normal_data = decode_accessor(gltf, bin_chunk, primitive["attributes"]["NORMAL"]).values
            uv_data = None
            if "TEXCOORD_0" in primitive["attributes"]:
                uv_data = decode_accessor(gltf, bin_chunk, primitive["attributes"]["TEXCOORD_0"]).values
            index_data = decode_accessor(gltf, bin_chunk, primitive["indices"]).values

            fh.write(f"o {base_name}\n")
            for pos in position_data:
                p = transform_point(matrix, pos)
                x, y, z = gltf_to_panda_point(p)
                fh.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")

            if uv_data is not None:
                for uv in uv_data:
                    u, v = uv
                    fh.write(f"vt {u:.6f} {v:.6f}\n")

            if normal_data is not None:
                for normal in normal_data:
                    n = transform_vector(matrix, normal)
                    x, y, z = gltf_to_panda_vector(n)
                    length = math.sqrt(x * x + y * y + z * z) or 1.0
                    fh.write(f"vn {x / length:.6f} {y / length:.6f} {z / length:.6f}\n")

            fh.write(f"usemtl {base_name}\n")
            fh.write("s off\n")
            for i in range(0, len(index_data), 3):
                a, b, c = index_data[i : i + 3]
                a += 1
                b += 1
                c += 1
                if uv_data is not None and normal_data is not None:
                    fh.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")
                elif uv_data is not None:
                    fh.write(f"f {a}/{a} {b}/{b} {c}/{c}\n")
                elif normal_data is not None:
                    fh.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")
                else:
                    fh.write(f"f {a} {b} {c}\n")

    return obj_path, mtl_path


def write_egg(gltf: dict, bin_chunk: bytes, out_dir: Path, base_name: str):
    meshes = gltf.get("meshes", [])
    if not meshes:
        raise ValueError("GLB has no meshes")

    nodes = gltf.get("nodes", [])
    node = nodes[0] if nodes else {}
    matrix = node.get("matrix")
    if matrix is None:
        matrix = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]

    mesh = meshes[node.get("mesh", 0)]
    egg_path = out_dir / f"{base_name}.egg"
    texture_paths = []
    for image_index in range(len(gltf.get("images", []))):
        texture_paths.append(extract_image(gltf, bin_chunk, image_index, out_dir, base_name))

    material = mesh["primitives"][0].get("material", 0) if mesh.get("primitives") else 0
    material_def = gltf.get("materials", [])[material] if gltf.get("materials") else {}
    with egg_path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("<CoordinateSystem> { Z-Up }\n")
        fh.write("\n")
        fh.write(f"<Group> {base_name} {{\n")
        fh.write(f"  <VertexPool> {base_name}_vpool {{\n")

        primitive = mesh["primitives"][0]
        position_data = decode_accessor(gltf, bin_chunk, primitive["attributes"]["POSITION"]).values
        normal_data = None
        if "NORMAL" in primitive["attributes"]:
            normal_data = decode_accessor(gltf, bin_chunk, primitive["attributes"]["NORMAL"]).values
        uv_data = None
        if "TEXCOORD_0" in primitive["attributes"]:
            uv_data = decode_accessor(gltf, bin_chunk, primitive["attributes"]["TEXCOORD_0"]).values
        index_data = decode_accessor(gltf, bin_chunk, primitive["indices"]).values

        for index, pos in enumerate(position_data):
            p = transform_point(matrix, pos)
            x, y, z = gltf_to_panda_point(p)
            fh.write(f"    <Vertex> {index} {{\n")
            fh.write(f"      {x:.6f} {y:.6f} {z:.6f}\n")
            if normal_data is not None:
                n = transform_vector(matrix, normal_data[index])
                nx, ny, nz = gltf_to_panda_vector(n)
                length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
                fh.write(f"      <Normal> {{ {nx / length:.6f} {ny / length:.6f} {nz / length:.6f} }}\n")
            if uv_data is not None:
                u, v = uv_data[index]
                fh.write(f"      <UV> {{ {u:.6f} {v:.6f} }}\n")
            fh.write("    }\n")

        fh.write("  }\n")
        for tri_index in range(0, len(index_data), 3):
            a, b, c = index_data[tri_index : tri_index + 3]
            fh.write("  <Polygon> {\n")
            fh.write(f"    <VertexRef> {{ {a} {b} {c} <Ref> {{ {base_name}_vpool }} }}\n")
            fh.write("  }\n")
        fh.write("}\n")

    return egg_path


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("Usage: convert_glb_to_egg.py <input.glb> <output_dir> <base_name>", file=sys.stderr)
        return 2

    input_path = Path(argv[1]).resolve()
    output_dir = Path(argv[2]).resolve()
    base_name = argv[3]

    output_dir.mkdir(parents=True, exist_ok=True)

    gltf, bin_chunk = read_glb(input_path)
    egg_path = output_dir / f"{base_name}.egg"
    write_obj(gltf, bin_chunk, output_dir, base_name)
    write_egg(gltf, bin_chunk, output_dir, base_name)

    print(str(egg_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
