## Ghidra Headless Decompilation

Ghidra headless is available for batch static analysis and decompilation without a graphical desktop.

### Quick Single-Function Decompilation

Use `ghidra-decompile` for fast one-shot decompilation:

```bash
# Export all function entry points and symbol names
ghidra-decompile /path/to/binary

# Decompile a specific function by name or address
ghidra-decompile /path/to/binary main
ghidra-decompile /path/to/binary 0x00401122
```

### Advanced Headless Batch Analysis

Use `ghidra-headless` (`analyzeHeadless`) for custom analysis scripts:

```bash
ghidra-headless /tmp/ghidra_proj TempProj \
    -import /path/to/binary \
    -scriptPath /usr/local/share/pa-container/packages/reverse-engineering/scripts \
    -postScript decompile_function.py main \
    -deleteProject \
    -readOnly
```

### Performance Guidelines

- **JVM Startup Time**: Ghidra takes 10–20 seconds to boot the JVM. Prefer batching or querying multiple symbols when possible.
- **Temporary Projects**: Always pass `-deleteProject` and `-readOnly` to prevent disk bloat from persistent Ghidra project files.
