# ruff: noqa: F821, UP031, SIM113
# Ghidra headless post-script to list program functions and entry points
# @category Analysis
# @author pa-container


def run():
    print("=== Functions and Entry Points ===")
    fm = currentProgram.getFunctionManager()
    funcs = fm.getFunctions(True)
    for count, f in enumerate(funcs):
        print(f"0x{f.getEntryPoint()}  {f.getName():<40}  [size: {f.getBody().getNumAddresses()} bytes]")
        if count >= 200:
            print("... (truncated at 200 functions)")
            break


run()
