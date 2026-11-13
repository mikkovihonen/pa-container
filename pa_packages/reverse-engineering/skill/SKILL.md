# Reverse Engineering and Binary Analysis

This capability package provides binary inspection, disassembly, decompilation, CPU emulation, and mitigation auditing tools.

## Binary Triage Workflow

Follow a disciplined triage procedure before attempting heavy decompilation:

1. **File Identification & Metadata**
    - Run `file <target>` to identify file format, architecture (x86_64, AArch64, ARM, MIPS), bitness (32/64-bit), and endianness.
    - Check headers and sections: `readelf -h <target>` and `readelf -l <target>`.

2. **Security Mitigations Audit**
    - Audit binary protections with `checksec <target>`.
    - Check for Stack Canary, NX/DEP (No-Execute stack), PIE (Position Independent Executable), and RELRO (Relocation Read-Only).

3. **Symbol & Export Enumeration**
    - List exported dynamic symbols: `nm -D <target>` or `readelf -s --dyn-syms <target>`.
    - Avoid dumping symbol tables larger than 100 entries without filtering.
    - Filter strings safely with minimum length and regex pattern:
        - `strings -a -t x -n 8 <target> | grep -iE 'key|pass|http|token|flag'`
        - Avoid unpiped `strings <target>` which exhausts context length.

4. **Dynamic Tracing**
    - Trace system calls: `strace -f -s 128 -o /tmp/strace.log <target> <args>`
    - Trace library calls: `ltrace -f -s 128 -o /tmp/ltrace.log <target> <args>`
