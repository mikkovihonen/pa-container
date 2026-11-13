## X11 Display Backend (`x11` feature)

The `x11` backend runs a classic X11 display stack without any Wayland component:
- **X11 Display**: `DISPLAY=:0` (no `WAYLAND_DISPLAY` is set)
- **Display Server**: `Xvfb` (auto-recovery supervised; software framebuffer at the configured resolution)
- **Window Manager**: `openbox` (click-to-focus, window stacking, and decorations)
- **VNC Server**: `x11vnc` on port 5900
- **Web Streaming**: `noVNC` via `websockify` on port 6080

Backend-specific tooling:
- `xdotool`: synthetic mouse and keyboard input (used by `agent-desktop` input commands).
- `wmctrl -l`: list and manage top-level windows (used by `agent-desktop windows`).
- `import -window root out.png`: ImageMagick X11 screenshot capture (used by `agent-desktop screenshot`).

Chromium and other GUI applications run against the X11 display `:0` using the X11 backend.

Operational notes for Xvfb:
- The display resolution is fixed at startup; to change it, update `resolution` in `.pa-container/config.yaml` and restart with `pa run` (Xvfb RANDR mode changes are not applied).
- OpenGL applications render through software GLX (Mesa llvmpipe); there is no hardware-accelerated presentation on this backend.
- Do not forward a `WAYLAND_DISPLAY` variable into nested containers; forward `/tmp/.X11-unix` and `DISPLAY=:0` instead.
