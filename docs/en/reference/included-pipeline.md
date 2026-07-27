---
layout: default
title: LOLDrivers Pipeline
order: 3
---

## LOLDrivers Pipeline Reference

A reference BYOVD (Bring Your Own Vulnerable Driver) pipeline is maintained in `pipelines/loldrivers/`.

1. **discover:** PE ingestion and LIEF header parsing.
2. **kernel_filter:** Constraints processing to kernel-mode drivers exposing IOCTL surfaces.
3. **loldrivers_filter:** Excludes known entities cataloged via loldrivers.io.
4. **decompile:** Executes Ghidra headless decompilation.
5. **semgrep_scanner:** Bulk static analysis against exported C source.
6. **pick_top_10:** Heuristic reduction to top candidate tier.
7. **assess:** LLM prompt injection and logical assessment.

### Whether a finding can be exercised without the hardware

Many drivers create their device object only once their hardware is enumerated. On a
machine or VM without that device, `\.\<name>` never opens, so nothing the driver
exposes can be reached — and from the report alone that is indistinguishable from the
driver not being vulnerable.

The `decompile` stage records where the device object is created:

| Value | Meaning |
|-------|---------|
| `device_created_in` | the function that calls `IoCreateDevice` |
| `device_on_load_path` | whether that function is `DriverEntry`, or something it calls |

`device_on_load_path: true` means the device appears on any machine that will load the
driver, so a finding against it can be confirmed today. `false` means it is created
somewhere else — typically a PnP add-device or start-device callback — and confirming
anything needs the physical device. Neither is recorded when `IoCreateDevice` is not
found at all, rather than guessing.

The bundled pipeline lists `decompile.device_on_load_path` under `report.columns`, so
it shows against each driver. That is all it takes: the value is declared in the
processor's `provides` and named by the pipeline, and the report stays unaware of what
a device object is.

### What decompilation writes per driver

The `decompile` stage writes into each sample's `decompiled/` directory:

| File | Contents |
|------|----------|
| `dispatch_ioctl.c` | The dispatch routine, recorded once |
| `ioctls/0xXXXXXXXX.c` | One per IOCTL code: what the code decodes to, pointing at the routine above |
| `ghidra_result.json` | Metadata — device name, symbolic link, dispatch name, and one entry per IOCTL code |

Every code in a driver is handled by the same routine, so it is stored once and
referenced, never copied per code. An entry in `ioctl_handlers` holds only the code and
its decoded fields (`hex`, `device_type`, `function`, `method`, `access`).

Size is worth watching, because the failure mode here is silent — output still looks
correct, just enormous. As a reference point, a pack of 1,388 decompiled drivers
produces roughly **28 MB** of `ghidra_result.json` in total. Storing the routine per
code instead produced **734 MB** for the same corpus, with a single driver reaching
52 MB. A stage run whose output is orders of magnitude above this has regressed to
repeating the routine, and the assessment stage will then parse that document per
driver when building its prompt.

`tests/test_extract_dispatch.py` guards the entry shape directly.
