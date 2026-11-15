---
name: 3d-tools
description: "Use when inspecting, converting, or repairing 3D meshes and models (STL, OBJ, PLY, GLB/glTF, FBX, 3MF) using Assimp and ADMesh."
---

# 3D Model Processing (`3d-tools`)

Provides tools for inspecting 3D model geometry, converting between common exchange formats (OBJ, STL, PLY, glTF/GLB), and repairing non-manifold mesh topology with `assimp` and `admesh`.

## Tool Overview

| Task | Tool | Primary Command |
|---|---|---|
| Inspect bounding box, vertex/face count, materials | `assimp info` | `assimp info model.glb` |
| Format conversion (FBX/OBJ/STL/PLY/GLB) | `assimp export` | `assimp export input.obj output.glb -f glb2` |
| Extract embedded textures | `assimp extract` | `assimp extract model.fbx textures/` |
| Inspect and repair STL topology, normals, and holes | `admesh` | `admesh --fill-holes --normal-directions in.stl -b out.stl` |

## Common Recipes

### Inspect Model Geometry and Bounds

```sh
assimp info model.glb
```

### Format Conversion with `assimp export`

```sh
# Convert Wavefront OBJ to glTF Binary (GLB)
assimp export input.obj output.glb -f glb2

# Convert Stanford PLY to STL
assimp export input.ply output.stl -f stlb
```

List all available export format identifiers:
```sh
assimp listexport
```

### Repair a Non-Manifold STL for 3D Printing with `admesh`

`admesh` fixes inverted facet normals, connects shared edges, and fills holes:

```sh
admesh --exact --remove-unconnected --fill-holes --normal-directions --normal-values in.stl -b repaired.stl
```

## Guidelines
- **Output directories**: Store generated models and intermediate exports in `/tmp/pa-3d`.
- **Supported formats**: Assimp natively reads dozens of formats including OBJ, STL, PLY, glTF/GLB, FBX, DAE (Collada), DXF, and 3DS.
