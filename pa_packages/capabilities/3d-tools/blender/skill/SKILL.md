## Feature: `blender` (Headless Blender 5.2 Scripting and Rendering)

Always invoke Blender with `-b` (`--background`) for headless execution. Use `--python-exit-code 1` so Python exceptions fail the shell command.

### Recipes

- **Render a `.blend` frame headless using Cycles CPU:**
    ```sh
    blender -b scene.blend -E CYCLES -o /tmp/render_#### -F PNG -f 1 -- --cycles-device CPU
    ```
- **Run a headless `bpy` geometry/conversion script:**
    ```sh
    blender -b --factory-startup --python-exit-code 1 --python - <<'PY'
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.gltf_import(filepath="input.glb")
    bpy.ops.wm.stl_export(filepath="output.stl")
    PY
    ```
