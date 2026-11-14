---
name: virtual-desktop
description: Control, observe, and automate graphical (GUI) applications running on the virtual desktop within the container environment. Provides commands for taking screenshots, inspecting open windows, launching GUI tools (e.g. Chromium, emulators), and synthesizing mouse clicks, drags, and keyboard shortcuts. Use whenever running, testing, or debugging GUI apps or web browsers.
---

# Virtual Desktop & GUI Automation

## When to Use

Use this skill when you need to run, inspect, or automate GUI applications inside the container environment:
- Launching graphical applications (e.g. Chromium, device emulators, test runners with UI).
- Capturing screenshots of application state to inspect rendering and layout.
- Simulating mouse movements, clicks, and drag-and-drop operations on the virtual desktop.
- Synthesizing keyboard typing and key combinations (shortcuts).
- Inspecting active top-level windows and application titles.

## Environment Overview

The container runs a headless virtual desktop with one active display backend, selected in `.pa-container/config.yaml` via the `virtual-desktop` package features (`wayland` or `x11`):
- **X11 Display**: `DISPLAY=:0`
- **Runtime Directory**: `XDG_RUNTIME_DIR=/run/user/1000`
- **Resolution**: 1920x1080 (or custom configured resolution)
- **Backend**: `${PA_DESKTOP_BACKEND}` (wayland or x11)

The display server, VNC server, and `noVNC` web streaming service are pre-started when desktop support is enabled. See the display backend sections appended below for backend-specific displays and tooling.

## In-Container Automation (`agent-desktop`)

The `agent-desktop` CLI utility provides direct observation and synthetic input primitives:

### 1. Check Status
Verify display server and streaming status:
```bash
agent-desktop status
```

### 2. Capture Screenshots
Take a snapshot of the full virtual desktop (saved as PNG):
```bash
agent-desktop screenshot /tmp/app-screen.png
```
Inspect the saved PNG file using available file or image inspection tools to observe UI state and locate widget pixel coordinates.

### 3. List Windows
List all open top-level application windows and titles:
```bash
agent-desktop windows
```

### 4. Launch GUI Applications
Launch an application detached in the background on the virtual desktop:
```bash
agent-desktop launch chromium https://example.com
```

### 5. Mouse Automation

- **Move Cursor**:
```bash
agent-desktop move 500 300
```

- **Left Mouse Click**:
```bash
# Click at current cursor position
agent-desktop mouse-click-left

# Move to (x, y) coordinates and click
agent-desktop mouse-click-left 500 300
```

- **Right Mouse Click (Context Menus)**:
```bash
# Right click at current cursor position
agent-desktop mouse-click-right

# Move to (x, y) coordinates and right click
agent-desktop mouse-click-right 500 300
```

- **Button Down and Up (Dragging & Range Selection)**:
```bash
# Press and hold left button down (optionally moving to x y first)
agent-desktop mouse-left-down 100 200

# Move cursor while button is held down
agent-desktop move 400 200

# Release left button
agent-desktop mouse-left-up 400 200

# Right button down and up
agent-desktop mouse-right-down 500 300
agent-desktop mouse-right-up 500 300
```

- **Drag Convenience**:
```bash
# Perform atomic drag from (x1, y1) to (x2, y2)
agent-desktop drag 100 200 400 200
```

### 6. Keyboard Automation

- **Type Text**:
```bash
agent-desktop type "hello world"
```

- **Single Key Events**:
```bash
agent-desktop key Return
agent-desktop key Tab
agent-desktop key Escape
agent-desktop key BackSpace
```

- **Key Combinations & Shortcuts**:
```bash
agent-desktop key ctrl+s
agent-desktop key ctrl+shift+p
agent-desktop key alt+F4
agent-desktop key ctrl+c
agent-desktop key ctrl+v
```

## Recommended Interactive Verification Workflow

When automating or testing a graphical application, follow this verification loop:
1. Launch the target GUI application:
    - Run `agent-desktop launch <app> [args...]`
2. Inspect open windows to verify the application has initialized:
    - Run `agent-desktop windows`
3. Capture visual snapshot:
    - Run `agent-desktop screenshot /tmp/step1.png`
4. Inspect the screenshot image:
    - Use image or file inspection tools to check visual rendering and identify target pixel coordinates for buttons, inputs, or menus.
5. Synthesize input:
    - Run `agent-desktop mouse-click-left <x> <y>` or `agent-desktop type "input"` or `agent-desktop key ctrl+s`.
6. Confirm visual result:
    - Run `agent-desktop screenshot /tmp/step2.png` and verify that the UI updated as expected.

## Running Chromium & Browser Tools

When `chromium` is included under `tools.include` in `.pa-container/config.yaml`:
- The binary is available on PATH as `chromium` and `google-chrome`.
- It connects to the active virtual desktop display backend automatically.
- All HTTP/HTTPS traffic is automatically routed through the project's mitmproxy container and trusts the mitmproxy CA certificate through its initialized NSS database.
- DNS-over-HTTPS (DoH) is disabled by managed policy so DNS filtering remains effective.

## Nested Container Display Forwarding

When running containerized GUI tools inside nested podman containers, forward the display sockets and GPU device:
```bash
podman run --rm -it \
    -e WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-}" \
    -e DISPLAY="${DISPLAY}" \
    -e XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR}" \
    -v "${XDG_RUNTIME_DIR}:${XDG_RUNTIME_DIR}" \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    --device /dev/dri \
    my-gui-tool-image
```
This renders nested graphical output directly onto the main virtual desktop. The `WAYLAND_DISPLAY` variables only apply when the wayland backend is active.
