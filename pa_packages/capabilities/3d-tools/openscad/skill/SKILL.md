## Feature: `openscad` (Parametric CAD Modeling)

Fedora 45 ships OpenSCAD 2021.01. Headless geometry exports (`STL`, `OFF`, `AMF`, `3MF`, `DXF`, `SVG`, `CSG`) run directly on CPU without a display server.

### Recipes

- **Compile `.scad` to binary STL with parameter overrides (`-D`):**
    ```sh
    openscad -o bracket.stl -D 'wall_thickness=3.2' -D '$fn=64' bracket.scad
    ```

### Caveat on `.png` Previews

Exporting `.png` images (`openscad -o preview.png part.scad`) requires an active X11/OpenGL display context (`virtual-desktop` package). Without a display, export to `.stl` first and render via `blender -b` or inspect geometry with `trimesh`.
