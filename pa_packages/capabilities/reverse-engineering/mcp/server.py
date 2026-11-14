#!/usr/bin/env python3
"""Reverse Engineering Model Context Protocol (MCP) server.

Provides structured JSON-RPC tools over stdio for binary triage,
disassembly, decompilation, string extraction, and instruction emulation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any

SERVER_NAME = "reverse-engineering"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2024-11-05"


def handle_re_triage(args: dict[str, Any]) -> dict[str, Any]:
    filepath = args.get("filepath", "")
    if not filepath or not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    result: dict[str, Any] = {
        "filepath": filepath,
        "size_bytes": os.path.getsize(filepath),
    }

    # 1. File identification
    file_cmd = subprocess.run(["file", "-b", filepath], capture_output=True, text=True)
    result["file_type"] = file_cmd.stdout.strip()

    # 2. Check ELF headers if applicable
    with open(filepath, "rb") as f:
        magic = f.read(4)

    if magic == b"\x7fELF":
        result["format"] = "ELF"
        readelf = subprocess.run(["readelf", "-h", "-l", "-d", filepath], capture_output=True, text=True)
        out = readelf.stdout

        # Mitigations
        result["mitigations"] = {
            "relro": "Full RELRO"
            if ("GNU_RELRO" in out and "BIND_NOW" in out)
            else ("Partial RELRO" if "GNU_RELRO" in out else "No RELRO"),
            "canary": "Canary present" if "__stack_chk_fail" in out else "No canary",
            "nx": "NX disabled" if ("GNU_STACK" in out and "RWE" in out) else "NX enabled",
            "pie": "PIE enabled" if "Type:                              DYN" in out else "Executable (No PIE)",
        }
    elif magic[:2] == b"MZ":
        result["format"] = "PE"
    elif magic in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe"):
        result["format"] = "Mach-O"
    else:
        result["format"] = "Unknown / Raw binary"

    return result


def handle_re_strings(args: dict[str, Any]) -> dict[str, Any]:
    filepath = args.get("filepath", "")
    if not filepath or not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    min_len = int(args.get("min_length", 6))
    pattern = args.get("filter_regex", "")
    limit = int(args.get("limit", 100))

    cmd = ["strings", "-a", "-t", "x", "-n", str(min_len), filepath]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return {"error": f"strings command failed: {proc.stderr.strip()}"}

    lines = proc.stdout.splitlines()
    matches = []
    regex = re.compile(pattern, re.IGNORECASE) if pattern else None

    for line in lines:
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            offset_str, s = parts
            if regex is None or regex.search(s):
                matches.append({"offset": f"0x{offset_str}", "string": s})
                if len(matches) >= limit:
                    break

    return {
        "filepath": filepath,
        "total_matched": len(matches),
        "truncated": len(matches) >= limit,
        "strings": matches,
    }


def handle_re_disassemble(args: dict[str, Any]) -> dict[str, Any]:
    filepath = args.get("filepath", "")
    code_hex = args.get("code_hex", "")
    arch_str = args.get("arch", "x86_64").lower()
    start_addr = int(str(args.get("address", "0x1000")), 0)
    count = int(args.get("count", 32))

    raw_bytes = b""
    if code_hex:
        try:
            raw_bytes = bytes.fromhex(code_hex.replace(" ", "").replace("0x", ""))
        except ValueError as e:
            return {"error": f"Invalid hex bytes: {e}"}
    elif filepath and os.path.exists(filepath):
        # Use objdump if whole file
        symbol = args.get("symbol", "")
        cmd = ["objdump", "-d", "--no-show-raw-insn"]
        if symbol:
            cmd.extend([f"--disassemble={symbol}"])
        cmd.append(filepath)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return {"error": f"objdump failed: {proc.stderr.strip()}"}
        lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()][: count * 2]
        return {"disassembly": "\n".join(lines)}
    else:
        return {"error": "Either 'code_hex' or 'filepath' must be provided."}

    # Attempt Capstone disassembly if available
    try:
        import capstone

        arch_map = {
            "x86_64": (capstone.CS_ARCH_X86, capstone.CS_MODE_64),
            "x86": (capstone.CS_ARCH_X86, capstone.CS_MODE_32),
            "arm64": (capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM),
            "aarch64": (capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM),
            "arm": (capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM),
        }
        cs_arch, cs_mode = arch_map.get(arch_str, (capstone.CS_ARCH_X86, capstone.CS_MODE_64))
        md = capstone.Cs(cs_arch, cs_mode)
        instructions = []
        for i in md.disasm(raw_bytes, start_addr):
            instructions.append(
                {
                    "address": f"0x{i.address:x}",
                    "mnemonic": i.mnemonic,
                    "op_str": i.op_str,
                    "bytes": i.bytes.hex(),
                }
            )
            if len(instructions) >= count:
                break
        return {"arch": arch_str, "instructions": instructions}
    except ImportError:
        return {"error": "Capstone library not available for direct byte disassembly."}


def handle_re_decompile(args: dict[str, Any]) -> dict[str, Any]:
    filepath = args.get("filepath", "")
    target = args.get("target", "main")
    if not filepath or not os.path.exists(filepath):
        return {"error": f"File not found: {filepath}"}

    ghidra_decompile_bin = shutil.which("ghidra-decompile")
    if not ghidra_decompile_bin:
        return {"error": "ghidra-decompile utility not found. Ensure ghidra-headless feature is active."}

    proc = subprocess.run([ghidra_decompile_bin, filepath, target], capture_output=True, text=True, timeout=120)
    return {
        "filepath": filepath,
        "target": target,
        "exit_code": proc.returncode,
        "output": proc.stdout if proc.returncode == 0 else proc.stderr,
    }


def handle_re_emulate(args: dict[str, Any]) -> dict[str, Any]:
    code_hex = args.get("code_hex", "")
    arch_str = args.get("arch", "x86_64").lower()
    initial_regs = args.get("registers", {})

    try:
        raw_bytes = bytes.fromhex(code_hex.replace(" ", "").replace("0x", ""))
    except ValueError as e:
        return {"error": f"Invalid hex code: {e}"}

    try:
        import unicorn
        from unicorn.x86_const import (
            UC_X86_REG_RAX,
            UC_X86_REG_RBX,
            UC_X86_REG_RCX,
            UC_X86_REG_RDI,
            UC_X86_REG_RDX,
            UC_X86_REG_RSI,
            UC_X86_REG_RSP,
        )

        if arch_str not in ("x86_64", "x64"):
            return {"error": f"Emulation currently configured for x86_64, requested: {arch_str}"}

        address = 0x1000000
        mu = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_64)
        mu.mem_map(address, 2 * 1024 * 1024)
        mu.mem_write(address, raw_bytes)

        reg_map = {
            "rax": UC_X86_REG_RAX,
            "rbx": UC_X86_REG_RBX,
            "rcx": UC_X86_REG_RCX,
            "rdx": UC_X86_REG_RDX,
            "rdi": UC_X86_REG_RDI,
            "rsi": UC_X86_REG_RSI,
            "rsp": UC_X86_REG_RSP,
        }

        # Set initial registers
        for reg_name, reg_val in initial_regs.items():
            reg_id = reg_map.get(reg_name.lower())
            if reg_id is not None:
                mu.reg_write(reg_id, int(str(reg_val), 0))

        mu.emu_start(address, address + len(raw_bytes))

        final_regs = {name: hex(mu.reg_read(reg_id)) for name, reg_id in reg_map.items()}
        return {"status": "success", "registers": final_regs}
    except ImportError:
        return {"error": "Unicorn engine not installed."}
    except Exception as e:
        return {"error": f"Emulation execution failed: {e}"}


TOOLS = [
    {
        "name": "re_triage",
        "description": "Inspect binary headers, format, architecture, bitness, and security mitigations (RELRO, Canary, NX, PIE).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Absolute or relative path to the binary target."}
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "re_strings",
        "description": "Extract ASCII/Unicode strings from binary with minimum length filtering and regex matching.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to binary target."},
                "min_length": {"type": "integer", "description": "Minimum string length (default: 6)."},
                "filter_regex": {"type": "string", "description": "Optional case-insensitive regex filter."},
                "limit": {"type": "integer", "description": "Maximum strings to return (default: 100)."},
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "re_disassemble",
        "description": "Disassemble raw hex machine code bytes or binary functions using Capstone or objdump.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code_hex": {
                    "type": "string",
                    "description": "Raw machine code bytes in hex format (e.g. '48 89 e5 c3').",
                },
                "filepath": {"type": "string", "description": "Optional path to compiled binary."},
                "symbol": {"type": "string", "description": "Function or symbol name to disassemble in binary."},
                "arch": {"type": "string", "description": "Architecture: x86_64, x86, arm64, arm (default: x86_64)."},
                "address": {"type": "string", "description": "Base start address in hex (default: '0x1000')."},
                "count": {"type": "integer", "description": "Maximum instructions to disassemble (default: 32)."},
            },
        },
    },
    {
        "name": "re_decompile",
        "description": "Decompile a function or export entry points from a binary using Ghidra headless.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Path to target executable or library."},
                "target": {
                    "type": "string",
                    "description": "Function name or address to decompile (e.g. 'main', '0x00401122').",
                },
            },
            "required": ["filepath"],
        },
    },
    {
        "name": "re_emulate",
        "description": "Emulate machine code execution using Unicorn CPU emulator and inspect resulting registers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code_hex": {"type": "string", "description": "Machine code bytes in hex format."},
                "arch": {"type": "string", "description": "CPU architecture (default: 'x86_64')."},
                "registers": {
                    "type": "object",
                    "description": "Mapping of initial register values (e.g. {'rax': 1, 'rdi': '0x2000'}).",
                },
            },
            "required": ["code_hex"],
        },
    },
]


def run_stdio_server():
    """Main JSON-RPC stdio loop."""
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            res = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS},
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})

            handler_map = {
                "re_triage": handle_re_triage,
                "re_strings": handle_re_strings,
                "re_disassemble": handle_re_disassemble,
                "re_decompile": handle_re_decompile,
                "re_emulate": handle_re_emulate,
            }

            handler = handler_map.get(tool_name)
            if handler:
                call_res = handler(tool_args)
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(call_res, indent=2)}]},
                }
            else:
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method {tool_name} not found"},
                }
        elif method == "ping":
            res = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        else:
            if msg_id is not None:
                res = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Unhandled method: {method}"},
                }
            else:
                continue

        sys.stdout.write(json.dumps(res) + "\n")
        sys.stdout.flush()


def main():
    if "--self-test" in sys.argv:
        print("mcp-server-ready")
        sys.exit(0)
    run_stdio_server()


if __name__ == "__main__":
    main()
