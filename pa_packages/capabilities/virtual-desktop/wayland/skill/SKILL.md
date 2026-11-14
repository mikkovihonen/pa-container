## Wayland Display Backend (`wayland` feature)

The default `wayland` backend runs a headless Wayland stacking compositor with Xwayland backwards compatibility:
- **Wayland Display**: `WAYLAND_DISPLAY=wayland-0`
- **X11 Display (Xwayland)**: `DISPLAY=:0`
- **Compositor**: `labwc` (auto-recovery supervised; compositor exit keybinds are disabled)
- **VNC Server**: `wayvnc` on port 5900 (with `--render-cursor`)
- **Web Streaming**: `noVNC` via `websockify` on port 6080

Backend-specific tooling:
- `wlr-randr --output HEADLESS-1 --custom-mode <WIDTHxHEIGHT>@60Hz`: query and change output resolution at runtime.
- `grim`: native Wayland screenshot capture (used by `agent-desktop screenshot`).
- `slurp`: interactive region selection helper for screenshots.
- `xdotool`: synthetic input for Xwayland clients (mouse, keyboard, and window queries via `DISPLAY=:0`).
- `wtype`: synthetic text and key input for native Wayland clients (fallback for `agent-desktop type` and `agent-desktop key`).
- `wlrctl toplevel list`: optional fallback window inspection tool when installed.

Chromium and other Ozone-aware applications automatically connect to the Wayland compositor (`wayland-0`) with platform auto-detection, with Xwayland serving legacy X11-only applications on `:0`. Native Wayland windows only accept synthetic text input (`wtype`); synthetic mouse input applies to Xwayland clients.

When forwarding the display into nested containers, also bind the Wayland socket:
```bash
-v /run/user/1000/wayland-0:/run/user/1000/wayland-0
```
