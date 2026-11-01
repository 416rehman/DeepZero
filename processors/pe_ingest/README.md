# pe_ingest

An `IngestProcessor` that turns a tree of Windows binaries into samples. One
sample is one file, its `source_path` is the file itself, and its `sample_id` is
the first 16 characters of the file's sha256, so a rerun over the same corpus
keeps the same samples.

Every sample is hashed and sized by reading the bytes. Everything past that is
read out of the PE headers by lief, so how much a sample carries depends on how
far it got: a file that is not a PE stops at `is_valid_pe`, and one the
`subsystem_filter` rejects stops at `reject_reason`.

## Pointing it at binaries

| Target | What happens |
|---|---|
| a **file** | that one file becomes a sample, whatever its extension |
| a **directory** | every file whose suffix is in `extensions` becomes a sample, recursively by default |

Single file mode ignores `extensions` entirely: naming one file is taken as
meaning that file. A target that does not exist is logged and produces no
samples, so the run ends with an empty corpus rather than an error.

`subdirs` narrows a directory to the packs worth walking:

```yaml
subdirs: [DP_Chipset, DP_LAN_Intel, DP_Vendor]
```

Each pattern is matched case-insensitively as a substring against the names of
the target's immediate subdirectories, and only the ones that match are walked.
If none of them matches, the whole target is walked instead, with a warning. A
misspelled pattern therefore widens the run rather than narrowing it, which is
worth knowing before pointing this at a disk full of driver packs.

Two byte-identical files hash the same and so claim the same `sample_id`. The
engine keeps the first and drops the rest, naming both in an error, so the same
driver shipped in twenty packs is analysed once.

Files are read on a thread pool sized by the pipeline's `max_workers` setting,
default 8. The header parse runs on the calling thread rather than in the pool,
because it is CPU work that only contends for the GIL when spread over threads.

## What it emits

Every key below lands in `history["<stage name>"].data` and is available to any
later stage's prompt, filter or ranking metric.

| Key | Meaning |
|---|---|
| `sha256` | sha256 of the file's bytes, and what `sample_id` is cut from |
| `md5` | md5 of the same bytes |
| `size_bytes` | length of the file in bytes |
| `error` | why the file could not be read |
| `is_valid_pe` | whether lief parsed the bytes as a PE image |
| `subsystem` | the subsystem name lief reports, for example `NATIVE` |
| `is_kernel_driver` | whether that name is `NATIVE` |
| `machine_type` | the machine the image targets, as lief names it |
| `reject_reason` | why parsing stopped short: the subsystem was outside `subsystem_filter`, or lief was not installed |
| `imported_dlls` | the imported module names, in import-table order |
| `imported_functions` | every named import across all of them |
| `has_ioctl_surface` | whether any import is one of a fixed set of device, queue and request-completion routines (WDM, KMDF, NDIS, StorPort, ScsiPort, HID) |
| `creates_device` | `IoCreateDevice` is imported |
| `creates_symlink` | `IoCreateSymbolicLink` is imported |
| `dangerous_imports` | sorted intersection of the imports with a fixed list of physical memory, process, MSR and bus, and image-loading routines |
| `is_signed` | whether the file carries an embedded signature |
| `priority_score` | 0 to 10, see below |
| `imphash` | lief's import hash, empty when it cannot be computed |

`error` is the only key a sample gets when the file could not be opened, so
nothing else in the table was computed for it.

A file whose first two bytes are not `MZ` is never handed to lief, so it carries
the hashes and nothing else: `is_valid_pe` is absent rather than false.
`is_valid_pe: false` means lief was asked and refused. Everything from
`imported_dlls` down is only recorded for a PE that also passed the subsystem
filter, so a prompt or a filter should tolerate any of it being missing.

`creates_device` is the literal `IoCreateDevice` import. A driver that uses
`IoCreateDeviceSecure`, or the KMDF equivalents, sets `has_ioctl_surface` but
not this one, because the two answer different questions.

`is_signed` only sees a signature embedded in the file. A driver signed through a
separate catalog carries none, so this reads false for it; it is not a statement
about whether Windows would load the driver.

### priority_score

Four of the five terms are only added when `has_ioctl_surface` is true:

| Term | Points |
|---|---|
| imports `MmMapIoSpace`, `ZwMapViewOfSection`, `ZwOpenSection` or `MmGetPhysicalAddress` | 3 |
| imports `PsLookupProcessByProcessId`, `ZwOpenProcess` or `ZwTerminateProcess` | 2 |
| imports `__readmsr`, `__writemsr`, `HalGetBusDataByOffset` or `HalSetBusDataByOffset` | 2 |
| six sections or fewer | 1 |
| optional header major OS version 10 or greater | 3 |

The last term is added whether or not there is any IOCTL surface, and the total
is capped at 10. So a PE with no dispatch surface at all still scores 3, and a
score is only comparable with other scores from the same corpus. It ranks what
to look at first; it says nothing about severity.

## Config

| Field | Default | Meaning |
|---|---|---|
| `extensions` | `[".sys"]` | which suffixes are collected in directory mode; a missing leading dot is added. Ignored when the target is a file |
| `recursive` | `true` | `false` collects only the top level of each directory that is searched |
| `subdirs` | none | substring patterns deciding which immediate subdirectories are walked |
| `subsystem_filter` | none | numeric PE subsystem values worth reading imports for; `[1]` is the native subsystem a kernel driver is built as |
| `limit` | `0` | stop after this many samples; `0` means no limit |

`subsystem_filter` does not filter. A file outside the list keeps `is_valid_pe`,
`subsystem`, `is_kernel_driver` and `machine_type`, gains a `reject_reason`, and
is still emitted as a sample. What it loses is the import walk and everything
derived from it. Dropping it from the run is a later stage's job, which is why
the shipped pipeline follows this one with a `metadata_filter`.

`limit` is read here as well as by the engine. The engine truncates the sample
list after the stage has run; reading it here stops the analysis as soon as
enough samples exist. Discovery still enumerates every matching file and queues
a read for all of them, but the queue is cancelled once the limit is reached.

This processor reads the raw config dict rather than declaring a `Config`
dataclass, so a key misspelled here is neither read nor reported.

`validate()` checks that lief is importable and that `extensions` is not empty,
both before a single file is read. lief is worth stopping the run for: without
it every sample carries hashes and nothing else, so a later stage filtering on
`is_kernel_driver` or `has_ioctl_surface` drops the entire corpus and the run
reports an empty result rather than a missing dependency.

## In a pipeline

```yaml
settings:
  work_dir: work
  max_workers: 4

stages:
  - name: discover
    processor: pe_ingest/pe_ingest.py
    config:
      extensions: [".sys"]
      recursive: true
      # read imports only for native-subsystem images
      subsystem_filter: [1]
      subdirs:
        - DP_Chipset
        - DP_LAN_Intel
        - DP_Vendor

  # this is what actually removes anything
  - name: kernel_filter
    processor: metadata_filter
    config:
      require:
        is_kernel_driver: true
        has_ioctl_surface: true
      dedup_field: sha256
```
