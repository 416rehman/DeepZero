# ghidra_decompile

A `MapProcessor` that decompiles one binary per sample by running Ghidra
headless with a post-script. The post-script does the analysis and writes
`ghidra_result.json`; this processor launches it, waits for it, lifts a few
values out of that file into the sample's data, and records the files it wrote
as artifacts so a later stage's prompt can reach them.

The strategy script is the interesting half. `extract_dispatch.py` ships beside
this processor and looks for a driver's `IRP_MJ_DEVICE_CONTROL` handler, but the
processor itself has no opinion about what a post-script does. Its contract is
narrow: run in Ghidra's Jython environment, write `ghidra_result.json` into
`$DEEPZERO_OUTPUT_DIR`, and put a boolean `success` at the top level of it.

## What one sample costs

Everything lands in `<sample dir>/decompiled/`:

```
decompiled/
  ghidra_result.json     the result document, and the cache marker
  dispatch_ioctl.c       the dispatch routine plus the internal functions it calls
  driver_entry.c         DriverEntry
  ioctls/0x00222004.c    one file per IOCTL code, recording what the code decodes to
  ghidra_project/        where Ghidra's project is made; -deleteProject removes it again
  ghidra_stdout.log      Ghidra's output, kept out of the pipeline's own logs
  ghidra_stderr.log
```

The command is `support/analyzeHeadless` (or the `.bat` on Windows) with
`-import`, `-postScript`, `-scriptPath`, `-overwrite`, `-deleteProject` and
`-analysisTimeoutPerFile`. `DEEPZERO_OUTPUT_DIR` is exported to the child so the
script knows where to write, and `JAVA_HOME` is exported when `java_home` is set.

## Decompiled output on disk is adopted instead of re-analysed

This is the surprising one, and it is a cache that lives outside the run state.

Before running anything, `should_skip()` looks for
`<sample dir>/decompiled/ghidra_result.json`. If it is there, parses, and records
`success: true`, the sample is skipped and counted as passed. Analysing one
binary costs minutes, so an interrupted run does not pay for it twice.

Only a result recording a finished run is adopted. A file that will not decode,
will not parse, or says `success: false` is not an analysis: the post-script
writes that last one on its way out of a crash, and adopting it would mark the
driver decompiled while leaving nothing decompiled and none of the values a
later prompt reads. Both readers of the file go through the same helper so they
cannot disagree, and an unusable file is deleted before Ghidra is launched again.

Two consequences are worth knowing before copying this pattern:

- A skipped sample records **no data**. `mark_stage_cached` sets the stage to
  completed and leaves `data` alone, so the keys below come from the run that
  actually executed. On a resume the earlier run's history entry is still there
  and its values survive. If the run state was discarded while the files were
  kept, the stage completes with an empty `data` and a later prompt asking for
  `device_name` gets nothing.
- `deepzero run --redo <stage>` is what forces a genuine re-analysis, and it
  works because `ghidra_result.json` is recorded as an artifact: `--redo` deletes
  the artifacts of the stages it drops. `driver_entry.c`, `ioctls/` and the two
  log files are not recorded, so they survive. The next successful run overwrites
  `driver_entry.c` and `dispatch_ioctl.c`, but `ioctls/` is not emptied first, so
  a code the previous run found and this one did not leaves its file behind.

## What it emits

Every key below lands in `history["<stage name>"].data` and is available to any
later stage's prompt, filter or ranking metric. All of them are read out of
`ghidra_result.json`, so what they mean is really what the strategy script put
there; the descriptions are `extract_dispatch.py`'s.

| Key | Meaning |
|---|---|
| `device_name` | a `\Device\...` string found in the binary's defined data |
| `symbolic_link` | a `\DosDevices\...` string found the same way |
| `device_created_in` | the function that calls `IoCreateDevice` |
| `device_on_load_path` | whether that function is `DriverEntry` or reachable from it |
| `dispatch_name` | the `IRP_MJ_DEVICE_CONTROL` handler the script identified |
| `function_count` | how many functions Ghidra found in the image |
| `ioctl_codes` | the codes the dispatch routine compares against, as `0x00000000` strings, sorted and deduplicated |
| `ioctl_count` | how many of those there are |
| `decompiled_ghidra_result_json` | the name a prompt uses to reach `ghidra_result.json` |
| `decompiled_dispatch_ioctl_c` | the name a prompt uses to reach `dispatch_ioctl.c` |

The last two are artifact names, not values: an artifact is addressed by its path
with the separators and the dot folded into the name. `dispatch_ioctl.c` is only
recorded when the file exists, which is to say when a dispatch routine was found.

`device_on_load_path` is the one worth reading carefully. A driver that only
creates its device object from a PnP add-device or start-device callback has no
device at all on a machine without the hardware, so nothing it exposes can be
exercised there. One that creates it in `DriverEntry`, or in something two call
levels below it, can be reached anywhere the driver loads. This is why the
shipped report puts that column beside the finding count.

`ioctl_codes` and `ioctl_count` are absent when no codes were recovered. They
come from pattern-matching `==` and `case` constants in the decompiled dispatch
routine, so a driver that computes its codes, or dispatches through a table,
reports none of them while still having them.

`device_name` and `symbolic_link` take the last matching string in Ghidra's
listing, so a binary carrying several device paths reports one of them rather
than all of them.

A run that finds `DriverEntry` but no dispatch routine is reported as
`success: true`. That is deliberate: the driver entry decompilation is still
worth having. It reaches the next stage with `dispatch_name` empty, no
`ioctl_codes`, and no `dispatch_ioctl.c` artifact, which is not the same thing as
a driver with no IOCTL surface.

The result document also holds `driver_entry_c` and `dispatch_c`. Neither is
lifted into `data`, because a prompt should reach the code through the artifact
rather than carry it in the run state.

## Config

| Field | Default | Meaning |
|---|---|---|
| `ghidra_install_dir` | none, required | the Ghidra installation root; `${GHIDRA_INSTALL_DIR}` is expanded before this processor sees it |
| `strategy` | none | the post-script's filename in `scripts/`, or an absolute path to one |
| `timeout` | `300` | seconds allowed per binary, unless the stage sets its own |
| `java_home` | none | exported as `JAVA_HOME` to the Ghidra process |
| `max_functions` | none | exported as `DEEPZERO_MAX_FUNCTIONS` to the post-script |
| `max_depth` | none | exported as `DEEPZERO_MAX_DEPTH` to the post-script |
| `max_parallel` | `0` | ceiling on automatic concurrency; `0` derives one |

`max_functions` and `max_depth` are environment variables and nothing more. It is
up to the post-script to read them, and the shipped `extract_dispatch.py` does
not: it follows callees to a depth of 4 and stops after 60 decompiled
subfunctions, both fixed in the script. Setting them changes nothing with that
strategy, and setting them is only meaningful for a script written to read them.

The stage's own `timeout:` wins over the config one when it is set, so
`timeout: 600` on the stage is the number that reaches Ghidra. That one number
does three jobs: it is Ghidra's `-analysisTimeoutPerFile`, it is the wall clock
this processor waits for the subprocess, and it is the engine's per-sample
budget. A binary whose analysis phase consumes the whole budget therefore leaves
no time for the post-script and is killed with nothing written, which the next
run sees as an unanalysed sample rather than a cached one.

`max_parallel` only applies to `parallel: 0`. With `0`, this processor derives a
ceiling from the CPU count, from roughly 4 GiB of RAM per worker, and a hard cap
of 16, because each worker is a separate JVM holding a full program database in
memory. When total RAM cannot be measured the bound falls back to at most 4
workers. The engine then clamps the result again to the pipeline's `max_workers`
setting, so whichever of the two is lower is what runs. An explicit `parallel: N`
on the stage is honoured as given and neither ceiling applies to it.

`validate()` checks that `ghidra_install_dir` is set, that it exists, and that
`analyzeHeadless` is under its `support/` directory. Nothing else is checked
before the run:

- Java is not. A missing or wrong JVM surfaces as a per-sample failure carrying
  Ghidra's own message and whatever `ghidra_stderr.log` ends with.
- `strategy` is not. Leaving it unset fails every sample with "no strategy script
  configured", and naming one that is neither in `scripts/` nor an absolute path
  fails every sample with `FileNotFoundError`, with the traceback in
  `<sample dir>/<stage>_error.log`.

## In a pipeline

```yaml
stages:
  - name: decompile
    processor: ghidra_decompile/ghidra_decompile.py
    # auto concurrency, bounded by RAM rather than by core count
    parallel: 0
    # this is the budget Ghidra actually gets
    timeout: 600
    config:
      strategy: extract_dispatch.py
      ghidra_install_dir: ${GHIDRA_INSTALL_DIR}
      java_home: ${JAVA_HOME:-}

  # the C this stage wrote is what gets scanned, so target_dir names its directory
  - name: semgrep_scanner
    processor: semgrep_scanner/semgrep_scanner.py
    config:
      target_dir: decompiled
      rules_dir: pipelines/loldrivers/rules
      min_findings: 1
```

A report for this kind of pipeline reads better with the load path beside the
finding count, since it is what decides whether a finding can be exercised on an
ordinary test machine:

```yaml
report:
  columns:
    - semgrep_scanner.finding_count
    - decompile.device_on_load_path
    - decompile.function_count
```
