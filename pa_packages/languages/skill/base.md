---
name: languages
description: Programming languages and developer toolchains runtime capability in the container.
---

# Programming Languages & Toolchains

## Overview

The container provides modular language environments, compilers, and runtimes:
- **Python**: System CPython 3.15 runtime with `uv` and `pip` (core/mandatory).
- **Node.js**: Node.js 26 JavaScript runtime with `npm` and `npx`.
- **C/C++**: Clang/LLVM, `clangd` language server, `mold` modern linker, CMake, and Ninja.
- **Go**: Official Go compiler toolchain and `gopls` language server.
- **Rust**: Official Rust toolchain with `rustc`, `cargo`, and `rust-analyzer`.
- **Ruby**: Ruby 3.4+ runtime with YJIT and jemalloc.
- **Zig**: Zig compiler toolchain and `zls` language server.
