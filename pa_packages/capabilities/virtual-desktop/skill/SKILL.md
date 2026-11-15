---
name: virtual-desktop
description: "Launch GUI applications, capture screenshots, and perform synthetic mouse and keyboard inputs to verify application rendering and interactive behavior."
---

# Virtual Desktop & UI Inspection (`virtual-desktop`)

Provides graphical desktop automation for launching GUI desktop applications, capturing window/desktop screenshots, and sending synthetic mouse and keyboard inputs to test visual rendering and UI behavior.

## Tool Overview: `agent-desktop`

`agent-desktop` is the unified cross-platform CLI tool for desktop observation and control.

| Command | Arguments | Description |
|---|---|---|
| `status` | none | Query compositor, display server, and active display output status |
| `screenshot` | `[output_path.png]` | Capture the full desktop screen to PNG (defaults to `/tmp/screenshot.png`) |
| `launch` | `<cmd...>` | Launch a GUI application in the background on the virtual desktop |
| `windows` | none | List active application windows |
| `move` | `<x> <y>` | Move mouse cursor to screen coordinates |
| `mouse-click-left` | `[x] [y]` | Perform left mouse click (optionally moving to x y first) |
| `mouse-click-right`| `[x] [y]` | Perform right mouse click (optionally moving to x y first) |
| `drag` | `<x1> <y1> <x2> <y2>`| Drag mouse from (x1, y1) to (x2, y2) with left button held down |
| `type` | `<text>` | Type text into the currently focused window |
| `key` | `<key...>` | Send keyboard key or combo (e.g. `Return`, `Tab`, `ctrl+s`, `Escape`) |

## Common Recipes

### Launch Application and Capture Visual Rendering

```sh
# 1. Launch target GUI app in the background
agent-desktop launch my-gui-app --config test.yaml

# 2. Wait for application window to render
sleep 2

# 3. Capture screenshot to verify visual appearance and layout
agent-desktop screenshot /tmp/app_render.png
```

### Test Interactive UI Behavior (Form Input & Click)

```sh
# Focus text box and type
agent-desktop mouse-click-left 320 240
agent-desktop type "user@example.com"

# Press Tab to switch field
agent-desktop key Tab
agent-desktop type "SecurePassword123"

# Click Submit button
agent-desktop mouse-click-left 450 380

# Capture result screenshot
agent-desktop screenshot /tmp/submission_result.png
```

## Guidelines
- **Cross-platform execution**: `agent-desktop` automatically routes commands to native display subsystems:
    - **Linux**: Wayland (`grim`, `wlrctl`) or X11 (`xdotool`, `Xvfb`).
    - **macOS**: Native Quartz (`screencapture`, `cliclick`).
- **Inspection artifacts**: Always save screenshots under `/tmp/pa-desktop` or `/tmp/screenshot.png`.
