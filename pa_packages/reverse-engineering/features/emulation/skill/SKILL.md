## CPU Emulation & Disassembly (Capstone, Unicorn, Keystone)

Use the Python frameworks for scriptable instruction manipulation and basic-block emulation.

### Disassembly with Capstone

```python
from capstone import CS_ARCH_X86, CS_MODE_64, Cs

md = Cs(CS_ARCH_X86, CS_MODE_64)
code = b"\x55\x48\x89\xe5\x48\x83\xec\x10\xb8\x00\x00\x00\x00\xc9\xc3"
for instr in md.disasm(code, 0x1000):
    print(f"0x{instr.address:x}:\t{instr.mnemonic}\t{instr.op_str}")
```

### Emulation with Unicorn

```python
from unicorn import UC_ARCH_X86, UC_MODE_64, Uc
from unicorn.x86_const import UC_X86_REG_RAX

# Initialize emulator and map 2MB memory
address = 0x1000000
mu = Uc(UC_ARCH_X86, UC_MODE_64)
mu.mem_map(address, 2 * 1024 * 1024)

# Write code: mov rax, 0x42; ret
code = b"\x48\xc7\xc0\x42\x00\x00\x00\xc3"
mu.mem_write(address, code)

# Emulate
mu.emu_start(address, address + len(code))
print(f"RAX: {mu.reg_read(UC_X86_REG_RAX):#x}")
```

### Assembly with Keystone

```python
from keystone import KS_ARCH_X86, KS_MODE_64, Ks

ks = Ks(KS_ARCH_X86, KS_MODE_64)
encoding, count = ks.asm("mov rax, 0x42; ret")
print(f"Bytes: {bytes(encoding).hex()}")
```
