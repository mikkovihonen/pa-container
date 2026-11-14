## Feature: `meshlab` (Headless MeshLab CLI)

MeshLab 2023.12+ merged `meshlabserver` into the main `meshlab` binary. Because `meshlab` initializes Qt on startup, **always prefix invocations with `QT_QPA_PLATFORM=offscreen`** in headless containers.

### Recipes

- **Convert mesh formats and export vertex/face attributes:**
    ```sh
    QT_QPA_PLATFORM=offscreen meshlab -i input.ply -o output.stl
    ```
