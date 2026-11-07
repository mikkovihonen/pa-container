---
name: virtual-desktop
description: Observe and interact with GUI applications running on the virtual desktop in pi-container. Provides commands for screenshots, window inspection, and synthetic input (click, type, key). Use when running or testing desktop applications, browsers, or emulators.
---

# Virtual Desktop & GUI Automation

## When to Use

Use this skill when you need to run, inspect, or automate GUI applications inside the `pi-container` environment:
- Launching graphical applications (e.g. Chromium, device emulators, test runners with UI).
- Capturing screenshots of application state to inspect rendering and layout.
- Simulating user mouse and keyboard input on the virtual desktop.
- Querying host observation endpoints (noVNC web UI and VNC) to share with the user.

## Prerequisites

1. Ensure virtual desktop support is enabled in `.pi-container/config.yaml`:
```yaml
desktop:
    enabled: true
    resolution: 1920x1080
    novnc:
        enabled: true
        port: auto
    vnc:
        enabled: true
        port: auto
    gpu:
        enabled: auto
```
2. Run `pi-container run` to start the agent with the virtual desktop compositor and streaming stack.

## Host Observation Commands

From the host, you can query endpoints for the active virtual desktop:

- **Display Desktop Info**:
```bash
pi-container desktop
```
- **Get noVNC Web URL Only**:
```bash
pi-container desktop --url
```
- **Get VNC Endpoint Only**:
```bash
pi-container desktop --vnc
```
- **Open in Default Web Browser**:
```bash
pi-container desktop --open
```
- **List All Running Desktops Across Projects**:
```bash
pi-container desktop --all
```
- **Machine-Readable JSON Output**:
```bash
pi-container desktop --json
```

## In-Container Automation (`pi-desktop`)

Inside the agent container, the `pi-desktop` CLI wrapper controls the Wayland/Xwayland desktop:

### 1. Check Status
Verify compositor and output state:
```bash
pi-desktop status
```

### 2. Capture Screenshots
Take a snapshot of the full virtual desktop (saved as PNG):
```bash
pi-desktop screenshot /tmp/app-screen.png
```
You can inspect the saved PNG file or use read_file / image inspection tools to verify UI state.

### 3. List Windows
List all open top-level application windows:
```bash
pi-desktop windows
```

### 4. Launch GUI Applications
Start an application in the background on the virtual desktop:
```bash
pi-desktop launch chromium https://example.com
```

### 5. Mouse and Keyboard Automation
Simulate user interaction:
- **Click**:
```bash
pi-desktop click 500 300
```
- **Move Cursor**:
```bash
pi-desktop move 500 300
```
- **Type Text**:
```bash
pi-desktop type "hello world"
```
- **Send Key Sequences**:
```bash
pi-desktop key Return
pi-desktop key Tab
pi-desktop key BackSpace
pi-desktop key ctrl+s
```

## Running Chromium & Browser Tools

When `chromium` is included under `tools.include` in `.pi-container/config.yaml`:
- The binary is available on PATH as `chromium` and `google-chrome`.
- It automatically connects to the Wayland compositor (`wayland-0`) with Ozone platform auto-detection.
- All HTTP/HTTPS traffic is automatically routed through the project's mitmproxy container and trusts the mitmproxy CA certificate through its initialized NSS database.
- DNS-over-HTTPS (DoH) is disabled by managed policy so DNS filtering remains effective.
