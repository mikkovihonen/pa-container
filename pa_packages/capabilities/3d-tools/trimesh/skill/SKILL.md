## Feature: `trimesh` (Python 3D Mesh Toolkit)

`python3-trimesh` is installed on the container's system Python (`python3`) alongside `numpy`, `scipy`, `networkx`, and `lxml`, supporting STL, OBJ, PLY, GLB/glTF, 3MF, and DAE out of the box.

### Recipes

- **Inspect watertightness, volume, extents, and repair holes:**
    ```sh
    python3 - <<'PY'
    import trimesh

    mesh = trimesh.load("part.stl", force="mesh")
    print("Watertight:", mesh.is_watertight, "Extents:", mesh.extents)
    if not mesh.is_watertight:
        trimesh.repair.fix_normals(mesh)
        trimesh.repair.fill_holes(mesh)
    print("Volume:", mesh.volume)
    mesh.export("part_repaired.3mf")
    PY
    ```
- **Convert a multi-part scene (`.glb` / `.3mf`) into merged STL:**
    ```sh
    python3 -c "import trimesh; s = trimesh.load('model.glb'); s.to_geometry().export('merged.stl')"
    ```
