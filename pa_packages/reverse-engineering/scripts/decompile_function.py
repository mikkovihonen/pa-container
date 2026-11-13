# Ghidra headless post-script to decompile a single function
# @category Decompiler
# @author pa-container

from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor


def run():
    args = getScriptArgs()
    if not args:
        print("ERROR: Function name or address required as script argument.")
        return

    target = args[0]
    decompiler = DecompInterface()
    decompiler.openProgram(currentProgram)
    monitor = ConsoleTaskMonitor()

    target_func = None
    funcs = getGlobalFunctions(target)
    if funcs:
        target_func = funcs[0]
    else:
        try:
            addr = currentAddress.getAddress(target)
            target_func = getFunctionAt(addr)
        except Exception:
            pass

    if not target_func:
        print("ERROR: Function '%s' not found." % target)
        return

    print("=== Decompiled Function: %s at %s ===" % (target_func.getName(), target_func.getEntryPoint()))
    results = decompiler.decompileFunction(target_func, 60, monitor)
    decomp_code = results.getDecompiledFunction()
    if decomp_code:
        print(decomp_code.getC())
    else:
        print("ERROR: Failed to decompile function: %s" % results.getErrorMessage())


run()
