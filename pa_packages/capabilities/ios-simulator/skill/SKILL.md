---
name: ios-simulator
description: "Build iOS applications, boot iOS Simulator, deploy .app bundles, and capture screenshots to verify mobile visual rendering and runtime behavior on macOS."
---

# iOS Simulator (`ios-simulator`)

Provides automated iOS Simulator lifecycle control, app installation, and display screenshot capture on macOS Apple Silicon.

## Tool Overview: `pa-ios`

The `pa-ios` CLI automates interaction with Apple's `xcrun simctl` engine.

| Command | Arguments | Description |
|---|---|---|
| `list` | none | List available iOS Simulator devices and runtimes |
| `boot` | `[device]` | Boot target simulator (default: "iPhone 16 Pro") |
| `install` | `<app_path.app>` | Install built `.app` bundle onto the booted simulator |
| `launch` | `<bundle_id>` | Launch application by bundle ID |
| `screenshot` | `[output.png]` | Capture high-resolution simulator display to PNG |
| `terminate` | `<bundle_id>` | Stop the target application |
| `shutdown` | `[device]` | Shut down simulator device |

## Common End-to-End Workflow

### 1. Build iOS Target for Simulator

```sh
xcodebuild -scheme MyApp \
    -destination 'generic/platform=iOS Simulator' \
    -configuration Debug \
    -derivedDataPath /tmp/pa-ios/build \
    build
```

### 2. Boot Simulator and Install Application

```sh
# Boot simulator
pa-ios boot "iPhone 16 Pro"

# Install .app bundle from DerivedData
pa-ios install /tmp/pa-ios/build/Build/Products/Debug-iphonesimulator/MyApp.app
```

### 3. Launch App and Verify Visual Rendering

```sh
# Launch app
pa-ios launch com.example.myapp

# Allow layout and animations to settle
sleep 2

# Capture screenshot for visual inspection
pa-ios screenshot /tmp/ios_preview.png
```

## Guidelines
- **Platform requirement**: This capability operates exclusively on macOS Apple Silicon guest VMs with Xcode installed.
- **Artifact paths**: Write build outputs and preview screenshots to `/tmp/pa-ios` or `/tmp`.
