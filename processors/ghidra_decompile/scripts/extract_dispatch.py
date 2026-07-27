# -*- coding: utf-8 -*-
# @category BYOVD
# @description extract IRP dispatch table and decompile IOCTL handlers
# runs inside ghidra's jython environment via analyzeHeadless -postScript
# ruff: noqa: F821

import io  # Added for stable UTF-8 file writing
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

    # just a symbol/label — try to create a function at that address
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


def classify_device_creation(entry_name, creating_functions, load_path_names):
    """where the device object is created, and whether that is on the load path.

    A driver that only creates its device from a PnP add-device or start-device
    callback has no device at all on a machine without the hardware, so nothing
    it exposes can be exercised there. One that creates it in DriverEntry, or in
    something DriverEntry calls, can be reached anywhere the driver will load.

    Kept free of Ghidra so the decision can be checked on its own: it takes the
    names of the functions that call IoCreateDevice and the names reachable from
    DriverEntry, and returns (where, on_load_path).
    """
    if not creating_functions:
        return "", False
    for name in creating_functions:
        if name == entry_name:
            return name, True
    for name in creating_functions:
        if name in load_path_names:
            return name, True
    return creating_functions[0], False


def _functions_calling(api_name):
    """names of functions that reference an imported api, via the symbol table.

    Cheaper and steadier than decompiling everything and matching text: a call
    that Ghidra renders differently in C is still a reference here.
    """
    fm = currentProgram.getFunctionManager()
    found = []
    try:
        for sym in currentProgram.getSymbolTable().getSymbols(api_name):
            for ref in sym.getReferences():
                func = fm.getFunctionContaining(ref.getFromAddress())
                if func is not None and func.getName() not in found:
                    found.append(func.getName())
    except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
        print("ghidra warning: failed to resolve callers of", api_name, ":", str(exc))
    return found


def _load_path_names(driver_entry, depth=2):
    """names reachable from DriverEntry, to the depth the dispatch search uses."""
    names = []
    if driver_entry is None:
        return names
    frontier = [driver_entry]
    for _ in range(depth):
        nxt = []
        for func in frontier:
            try:
                for called in func.getCalledFunctions(getMonitor()):
                    if called.getName() not in names:
                        names.append(called.getName())
                        nxt.append(called)
            except (RuntimeError, ValueError, TypeError, AttributeError):
                continue
        frontier = nxt
    return names


def decode_ioctl_code(code):
    """what a single IOCTL code decodes to.

    The routine handling it is the same for every code in a driver, and is
    recorded once as dispatch_c. An entry therefore carries only the code and
    its decoded fields: storing the routine per code grew one driver's result
    to 52 MB, nearly all of it the same text repeated.
    """
    return {
        "code": code,
        "hex": "0x%08X" % code,
        "device_type": (code >> 16) & 0xFFFF,
        "function": (code >> 2) & 0xFFF,
        "method": code & 0x3,
        "access": (code >> 14) & 0x3,
    }


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


def _get_output_dir():
    output_dir = os.environ.get("DEEPZERO_OUTPUT_DIR", ".")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    return output_dir


def main():
    output_dir = _get_output_dir()

    decomp = get_decompiler()
    result = {
        "success": False,
        "error": "",
        "driver_entry_c": "",
        "dispatch_name": "",
        "dispatch_c": "",
        "device_name": "",
        "symbolic_link": "",
        "device_created_in": "",
        "device_on_load_path": False,
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
    # FIX: Use io.open with utf-8 encoding and unicode() cast for Jython stability
    with io.open(os.path.join(output_dir, "driver_entry.c"), "w", encoding="utf-8") as f:
        f.write(unicode(entry_c))

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

    # whether the device object exists on a machine without the hardware: a
    # driver that only creates it from a PnP callback exposes nothing there,
    # so a finding against it cannot be exercised on an ordinary test system
    creators = _functions_calling("IoCreateDevice")
    where, on_load_path = classify_device_creation(
        driver_entry.getName(), creators, _load_path_names(driver_entry)
    )
    result["device_created_in"] = where
    result["device_on_load_path"] = on_load_path

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
        """skip known external api calls — follow everything else"""
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
    # FIX: Use io.open with utf-8 encoding and unicode() cast for Jython stability
    with io.open(os.path.join(output_dir, "dispatch_ioctl.c"), "w", encoding="utf-8") as f:
        f.write(unicode(dispatch_c))

    # create ioctls subdirectory
    ioctls_dir = os.path.join(output_dir, "ioctls")
    if not os.path.exists(ioctls_dir):
        os.makedirs(ioctls_dir)

    for code in ioctl_codes:
        # every code is handled by the same dispatch routine, which is recorded
        # once as result["dispatch_c"] and written to dispatch_ioctl.c. repeating
        # it per code made this file grow to tens of megabytes for one driver.
        result["ioctl_handlers"].append(decode_ioctl_code(code))

        # one file per code recording what the code decodes to. the routine that
        # handles it is the same for every code and is written once to
        # dispatch_ioctl.c: copying it into each file made these directories
        # hundreds of megabytes and made a scanner read the same function once
        # per code, counting every finding again for each one.
        # unicode() cast required: a jython io text stream rejects str, and
        # "..." % int yields str (raising "can't write str to text stream")
        with io.open(os.path.join(ioctls_dir, "0x%08X.c" % code), "w", encoding="utf-8") as f:
            f.write(unicode("// IOCTL Code: 0x%08X\n" % code))
            f.write(unicode("// Method: %d\n" % (code & 0x3)))
            f.write(unicode("// Device Type: 0x%04X\n" % ((code >> 16) & 0xFFFF)))
            f.write(unicode("// Function: 0x%03X\n" % ((code >> 2) & 0xFFF)))
            f.write(unicode("// Access: %d\n" % ((code >> 14) & 0x3)))
            f.write(unicode("// Handler: %s (see ../dispatch_ioctl.c)\n" % result["dispatch_name"]))

    result["success"] = True
    write_result(output_dir, result)


def write_result(output_dir, result):
    # FIX: Use io.open with utf-8 and ensure_ascii=False for JSON dump
    with io.open(os.path.join(output_dir, "ghidra_result.json"), "w", encoding="utf-8") as f:
        data = json.dumps(result, indent=2, default=str, ensure_ascii=False)
        f.write(unicode(data))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, TypeError, AttributeError, OSError):
        import traceback

        try:
            output_dir = _get_output_dir()
        except Exception:
            output_dir = os.environ.get("DEEPZERO_OUTPUT_DIR", ".")

        res = {
            "success": False,
            "error": "script crashed:\n" + traceback.format_exc(),
        }
        write_result(output_dir, res)
