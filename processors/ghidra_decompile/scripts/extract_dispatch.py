# -*- coding: utf-8 -*-
# @category BYOVD
# @description extract IRP dispatch table and decompile IOCTL handlers
# runs inside ghidra's jython environment via analyzeHeadless -postScript
# ruff: noqa: F821

import json
import os
import re

from ghidra.app.decompiler import DecompileOptions, DecompInterface


def get_decompiler():
    """set up the decompiler interface"""
    decomp = DecompInterface()
    opts = DecompileOptions()
    opts.setMaxPayloadMBytes(64)
    decomp.setOptions(opts)
    decomp.openProgram(currentProgram)
    return decomp


def decompile_function(decomp, func, timeout=120):
    """decompile a function and return the C string"""
    if func is None:
        return ""
    result = decomp.decompileFunction(func, timeout, getMonitor())
    if result and result.decompileCompleted():
        return result.getDecompiledFunction().getC()
    return ""


def find_driver_entry():
    """locate DriverEntry or GsDriverEntry"""
    fm = currentProgram.getFunctionManager()

    # try exported names first
    for name in ["DriverEntry", "GsDriverEntry"]:
        funcs = list(getGlobalFunctions(name))
        if funcs:
            return funcs[0]

    # fallback: entry point via symbol table
    entry_point = currentProgram.getSymbolTable().getExternalEntryPointIterator()
    for addr in entry_point:
        f = fm.getFunctionAt(addr)
        if f:
            return f

    return None


# known external api prefixes and names to skip when following subfunctions
EXTERNAL_PREFIXES = (
    "Nt",
    "Zw",
    "Ke",
    "Io",
    "Mm",
    "Ob",
    "Ps",
    "Se",
    "Ex",
    "Rtl",
    "Hal",
    "Wdf",
    "WDF",
    "Ndis",
    "Pc",
    "Ks",
    "Stor",
    "Scsi",
    "Hid",
    "__security_check_cookie",
    "__C_specific_handler",
    "__report_rangecheckfailure",
    "memcpy",
    "memset",
    "memmove",
    "strlen",
    "strcmp",
    "wcscpy",
    "wcslen",
)


def _resolve_handler_name(fm, name):
    """resolve a handler name to a function object"""
    target_funcs = list(getGlobalFunctions(name))
    if target_funcs:
        return target_funcs[0]

    for candidate in fm.getFunctions(True):
        if candidate.getName() == name:
            return candidate

    # just a symbol/label ΓÇö try to create a function at that address
    syms = currentProgram.getSymbolTable().getSymbols(name)
    if syms.hasNext():
        sym = syms.next()
        addr = sym.getAddress()
        from ghidra.app.cmd.function import CreateFunctionCmd

        cmd = CreateFunctionCmd(addr)
        cmd.applyTo(currentProgram)
        return fm.getFunctionAt(addr)

    return None


def _search_code_for_dispatch(c_code, patterns):
    """search decompiled c code for dispatch table assignment, return handler name or None"""
    for pat in patterns:
        matches = list(re.finditer(pat, c_code, re.IGNORECASE))
        if matches:
            return matches[-1].group(1)
    return None


def find_dispatch_assignment(decomp, driver_entry=None):
    """find the IRP_MJ_DEVICE_CONTROL handler address.
    starts from DriverEntry and its direct callees before falling
    back to a full function scan, avoiding unnecessary decompilations."""

    patterns = [
        # x64 raw offset pattern (handles &LAB_XXXX)
        r"\*\s*\([^)]*\+\s*0xe0\)\s*=\s*&?(\w+)",
        r"\*\s*\([^)]*\+\s*0x0?e0\)\s*=\s*&?(\w+)",
        # x64 with cast
        r"\*\s*\([^)]*\)\s*\([^)]*\+\s*0xe0\)\s*=\s*&?(\w+)",
        # array index pattern (x64: index 0x1c = 0xe0/8)
        r"\[0x1c\]\s*=\s*&?(\w+)",
        # MajorFunction pattern (if types are applied)
        r"MajorFunction\s*\[\s*0xe\s*\]\s*=\s*&?(\w+)",
        r"MajorFunction\s*\[\s*14\s*\]\s*=\s*&?(\w+)",
        # x86 offset pattern
        r"\*\s*\([^)]*\+\s*0x70\)\s*=\s*&?(\w+)",
        r"\*\s*\([^)]*\)\s*\([^)]*\+\s*0x70\)\s*=\s*&?(\w+)",
    ]

    fm = currentProgram.getFunctionManager()

    # phase 1: search DriverEntry and its immediate callees (covers 95%+ of drivers)
    priority_funcs = []
    if driver_entry:
        priority_funcs.append(driver_entry)
        try:
            for called in driver_entry.getCalledFunctions(getMonitor()):
                priority_funcs.append(called)
                # also grab one level deeper - some drivers have DriverEntry -> InitDevice -> SetupDispatch
                for sub in called.getCalledFunctions(getMonitor()):
                    priority_funcs.append(sub)
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError(
                "ghidra structural failure: failed to enumerate callees from driver entry: "
                + str(exc)
            )

    seen_addrs = set()
    for func in priority_funcs:
        addr = func.getEntryPoint()
        if addr in seen_addrs:
            continue
        seen_addrs.add(addr)

        c_code = decompile_function(decomp, func)
        if not c_code:
            continue

        handler_name = _search_code_for_dispatch(c_code, patterns)
        if handler_name:
            resolved = _resolve_handler_name(fm, handler_name)
            if resolved:
                return resolved

    # phase 2: fallback full scan if priority search failed
    for func in fm.getFunctions(True):
        addr = func.getEntryPoint()
        if addr in seen_addrs:
            continue

        c_code = decompile_function(decomp, func)
        if not c_code:
            continue

        handler_name = _search_code_for_dispatch(c_code, patterns)
        if handler_name:
            resolved = _resolve_handler_name(fm, handler_name)
            if resolved:
                return resolved

    return None


def extract_ioctl_codes(decompiled_c):
    """extract IOCTL code constants from a decompiled dispatch function"""
    codes = []

    # look for comparisons: if (local_var == 0x80002000) or switch cases
    # ghidra style: iVar == 0x222004, param_2 == -1294821, case 2236420:
    hex_pattern = r"(?:==|case)\s*(-?0x[0-9a-fA-F]+|-?\d{6,10})"
    for match in re.finditer(hex_pattern, decompiled_c):
        raw_val = match.group(1).lower()
        if raw_val.startswith("0x") or raw_val.startswith("-0x"):
            code = int(raw_val, 16)
        else:
            code = int(raw_val, 10)

        # Convert signed 32-bit negatives back to 32-bit unsigned uint32 representation
        if code < 0:
            code = code & 0xFFFFFFFF

        # basic sanity: ioctl codes have device type in upper 16 bits
        if (code >> 16) > 0 and (code >> 16) < 0xFFFF:
            codes.append(code)

    return sorted(set(codes))


def main():
    output_dir = os.environ.get("DEEPZERO_OUTPUT_DIR", ".")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    decomp = get_decompiler()
    result = {
        "success": False,
        "error": "",
        "driver_entry_c": "",
        "dispatch_name": "",
        "dispatch_c": "",
        "device_name": "",
        "symbolic_link": "",
        "ioctl_handlers": [],
        "function_count": 0,
    }

    # count functions
    fm = currentProgram.getFunctionManager()
    result["function_count"] = fm.getFunctionCount()

    # find DriverEntry
    driver_entry = find_driver_entry()
    if not driver_entry:
        result["error"] = "could not locate DriverEntry"
        write_result(output_dir, result)
        return

    # decompile DriverEntry
    entry_c = decompile_function(decomp, driver_entry)
    result["driver_entry_c"] = entry_c

    # write DriverEntry decompilation
    with open(os.path.join(output_dir, "driver_entry.c"), "w") as f:
        f.write(entry_c)

    # extract device name and symbolic link from strings
    for s in currentProgram.getListing().getDefinedData(True):
        try:
            val = s.getValue()
            if hasattr(val, "__str__"):
                sv = str(val)
                if "\\Device\\" in sv:
                    result["device_name"] = sv.strip('"').strip("u'")
                elif "\\DosDevices\\" in sv:
                    result["symbolic_link"] = sv.strip('"').strip("u'")
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            print("ghidra warning: failed to read data entry:", str(exc))
            continue

    # find dispatch handler
    dispatch_func = find_dispatch_assignment(decomp, driver_entry)

    if not dispatch_func:
        result["error"] = "could not locate IRP_MJ_DEVICE_CONTROL handler"
        result["success"] = True  # partial success, we still have DriverEntry
        write_result(output_dir, result)
        return

    result["dispatch_name"] = dispatch_func.getName()

    # decompile full dispatch function
    dispatch_c = decompile_function(decomp, dispatch_func)
    result["dispatch_c"] = dispatch_c

    # extract individual IOCTL codes from the raw dispatch function
    ioctl_codes = extract_ioctl_codes(dispatch_c)

    # now collect all internal subfunctions called by the dispatch
    subfuncs_c = []
    seen = {dispatch_func.getName()}
    max_subfuncs = 60

    def _is_external(name):
        """skip known external api calls ΓÇö follow everything else"""
        for prefix in EXTERNAL_PREFIXES:
            if name.startswith(prefix):
                return True
        return name.startswith("_") and not name.startswith("FUN_")

    def get_subfuncs(func, depth=0):
        if depth > 4 or len(subfuncs_c) >= max_subfuncs:
            return
        try:
            for called in func.getCalledFunctions(getMonitor()):
                if len(subfuncs_c) >= max_subfuncs:
                    return
                name = called.getName()
                if name not in seen and not _is_external(name):
                    seen.add(name)
                    c = decompile_function(decomp, called)
                    if c:
                        subfuncs_c.append(c)
                        get_subfuncs(called, depth + 1)
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError(
                "ghidra structural failure: failed to decompile or resolve calls: " + str(exc)
            )

    get_subfuncs(dispatch_func)

    # append subfunctions to the dispatch text so they are included in all output files
    if subfuncs_c:
        dispatch_c += "\n\n// " + "=" * 40 + " //\n"
        dispatch_c += "//   INTERNAL SUBFUNCTIONS CALLED BY DISPATCH   //\n"
        dispatch_c += "// " + "=" * 40 + " //\n\n"
        dispatch_c += "\n\n".join(subfuncs_c)

    # write full decompiled payload
    result["dispatch_c"] = dispatch_c
    with open(os.path.join(output_dir, "dispatch_ioctl.c"), "w") as f:
        f.write(dispatch_c)

    # create ioctls subdirectory
    ioctls_dir = os.path.join(output_dir, "ioctls")
    if not os.path.exists(ioctls_dir):
        os.makedirs(ioctls_dir)

    for code in ioctl_codes:
        handler_info = {
            "code": code,
            "hex": "0x%08X" % code,
            "device_type": (code >> 16) & 0xFFFF,
            "function": (code >> 2) & 0xFFF,
            "method": code & 0x3,
            "access": (code >> 14) & 0x3,
            "decompiled_c": dispatch_c,  # full dispatch for now
        }
        result["ioctl_handlers"].append(handler_info)

        # write per-ioctl file
        with open(os.path.join(ioctls_dir, "0x%08X.c" % code), "w") as f:
            f.write("// IOCTL Code: 0x%08X\n" % code)
            f.write("// Method: %d\n" % (code & 0x3))
            f.write("// Device Type: 0x%04X\n" % ((code >> 16) & 0xFFFF))
            f.write("// Function: 0x%03X\n\n" % ((code >> 2) & 0xFFF))
            f.write(dispatch_c)

    result["success"] = True
    write_result(output_dir, result)


def write_result(output_dir, result):
    with open(os.path.join(output_dir, "ghidra_result.json"), "w") as f:
        json.dump(result, f, indent=2, default=str)


try:
    main()
except (RuntimeError, ValueError, TypeError, AttributeError, OSError):
    import traceback

    output_dir = os.environ.get("DEEPZERO_OUTPUT_DIR", ".")
    res = {
        "success": False,
        "error": "script crashed:\n" + traceback.format_exc(),
    }
    with open(os.path.join(output_dir, "ghidra_result.json"), "w") as f:
        json.dump(res, f, indent=2)
