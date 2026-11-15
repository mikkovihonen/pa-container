# Tart Metal Capabilities Shim

Vendored adaptation of the minimal Cua/Lume Metal capability shim for Apple Silicon macOS virtualization.
Retains original Cua/Cirrus copyright and MIT license.

## Overview

In Apple Silicon macOS guest virtualization, Apple's `ParavirtualizedGraphics` framework artificially clamps guest GPUs to Apple Family 5 (A13 Bionic) and limits `maxThreadgroupMemoryLength` to 32 KiB.

This shim dynamically intercepts `_MTLDevice` methods (`initGPUFamilySupport`, `supportsFamily:`, `maxThreadgroupMemoryLength`, `recommendedMaxWorkingSetSize`) using Objective-C runtime method swizzling to expose modern Apple Silicon feature levels (Apple Family 6-9, M1-M4) and 64 KiB threadgroup memory to guest processes.

## Configuration Variables

| Variable | Description |
| --- | --- |
| `TART_METAL_APPLE_FAMILY_MAX` | Apple family ceiling (1001 to 1999). Default: 1009 (Apple Family 9). |
| `TART_METAL_MAX_THREADGROUP_MEMORY` | Threadgroup memory floor in bytes. Default: 65536 (64 KiB). |
| `TART_METAL_RECOMMENDED_WORKING_SET_SIZE` | Optional working-set floor in bytes. |

## Usage

The library is inactive by default. It is activated on demand for specific commands via `DYLD_INSERT_LIBRARIES`:

```bash
DYLD_INSERT_LIBRARIES=/usr/local/lib/TartMetalCapabilities.dylib \
TART_METAL_APPLE_FAMILY_MAX=1009 \
TART_METAL_MAX_THREADGROUP_MEMORY=65536 \
/path/to/workload
```
