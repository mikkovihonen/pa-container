# Ghidra headless post-script to list program functions and entry points
# @category Analysis
# @author pa-container


def run():
    print("=== Functions and Entry Points ===")
    fm = currentProgram.getFunctionManager()
    funcs = fm.getFunctions(True)
    count = 0
    for f in funcs:
        print("0x%s  %-40s  [size: %d bytes]" % (f.getEntryPoint(), f.getName(), f.getBody().getNumAddresses()))
        count += 1
        if count >= 200:
            print("... (truncated at 200 functions)")
            break


run()
