---
name: 3d-tools
description: "Use when inspecting, converting, repairing, compressing, or generating 3D meshes and volumetric grids (STL, OBJ, PLY, GLB/glTF, 3MF, FBX, OpenVDB) using assimp, admesh, draco, openvdb, and optional trimesh, Blender, MeshLab, or OpenSCAD."
---

# 3D Model Processing (`3d-tools`)

## Tool Triage

| Task | Tool | Primary Command |
|---|---|---|
| Inspect bounding box, vertex/face count, materials | `assimp info` | `assimp info model.glb` |
| Quick format conversion (FBX/DAE/OBJ/STL/PLY/GLB) | `assimp export` | `assimp export input.obj output.glb -f glb2` |
| Check and repair STL topology, normals, and holes | `admesh` | `admesh --fill-holes --normal-directions --normal-values in.stl -b out.stl` |
| Compress / decompress mesh to Google Draco (`.drc`) | `draco_encoder` / `draco_decoder` | `draco_encoder -i input.ply -o output.drc -cl 7` |
| Inspect OpenVDB volumetric grids (`.vdb`) | `vdb_print` | `vdb_print -l smoke.vdb` |
| Programmatic mesh analysis, 3MF/GLB I/O, hole repair | `trimesh` feature (default on) | `python3 -c "import trimesh; m = trimesh.load('in.3mf'); ..."` |
| Filter chains, mesh cleaning, remeshing | `meshlab` feature | `QT_QPA_PLATFORM=offscreen meshlab -i in.ply -o out.stl` |
| Parametric CAD modeling (`.scad` → `.stl`/`.3mf`/`.dxf`) | `openscad` feature | `openscad -o part.stl part.scad` |
| Complex booleans, UV unwrapping, animation, CPU Cycles rendering | `blender` feature | `blender -b scene.blend --python script.py` |

## Common Recipes

### Repair a Non-Manifold STL for 3D Printing with `admesh`

```sh
admesh --exact --nearby --remove-unconnected --fill-holes --normal-directions --normal-values broken.stl -b repaired.stl
```

### Compress a Mesh with Draco and Decode Back to PLY

```sh
draco_encoder -i model.obj -o model.drc -qp 14 -cl 7
draco_decoder -i model.drc -o decoded.ply
```

### Convert Between Common 3D Formats with `assimp`

Run `assimp listexport` to see supported export format IDs (`stl`, `stlb`, `obj`, `ply`, `plyb`, `glb2`, `gltf2`, `collada`):

```sh
assimp export input.fbx output.glb -f glb2
```

## Caveats

- **Prefer `trimesh` for 3MF and modern glTF/GLB:** When the `trimesh` feature is enabled (default), prefer it over `assimp` for `.3mf` and `.glb` manipulation.
- **No GPU acceleration in headless containers:** All geometry and rendering tools run on CPU.
