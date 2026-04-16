from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from deepzero.engine.stage import IngestProcessor, ProcessorContext, Sample


class PEIngest(IngestProcessor):
    description = (
        "discovers portable executable files, parses PE headers, and extracts driver metadata"
    )
    version = "2.0"

    def process(self, ctx: ProcessorContext, target: Path) -> list[Sample]:
        extensions = self.config.get("extensions", [".sys"])
        recursive = self.config.get("recursive", True)
        subdirs = self.config.get("subdirs", [])

        if target.is_file():
            return self._ingest_single(target)

        if not target.is_dir():
            self.log.error("target does not exist: %s", target)
            return []

        if subdirs:
            return self._ingest_filtered(ctx, target, subdirs, extensions)

        return self._ingest_directory(ctx, target, extensions, recursive)

    def _ingest_single(self, path: Path) -> list[Sample]:
        self.log.info("single file mode: %s", path.name)
        data = self._extract_metadata(path)
        sample_id = data.get("sha256", "")[:16] or path.stem
        return [Sample(sample_id=sample_id, source_path=path, filename=path.name, data=data)]

    def _ingest_filtered(
        self, ctx: ProcessorContext, root: Path, subdirs: list[str], extensions: list[str]
    ) -> list[Sample]:
        all_dirs = sorted(d for d in root.iterdir() if d.is_dir())
        matching = [d for d in all_dirs if any(p.lower() in d.name.lower() for p in subdirs)]

        if not matching:
            self.log.warning("no subdirectories matched patterns %s in %s", subdirs, root)
            return self._ingest_directory(ctx, root, extensions, True)

        self.log.info("scanning %d/%d matching subdirectories", len(matching), len(all_dirs))

        files: list[Path] = []
        for pack_dir in matching:
            for ext in extensions:
                ext = ext if ext.startswith(".") else f".{ext}"
                files.extend(pack_dir.rglob(f"*{ext}"))

        files = sorted(set(files))
        self.log.info("found %d files across %d directories", len(files), len(matching))
        return self._analyze_files(ctx, files)

    def _ingest_directory(
        self, ctx: ProcessorContext, directory: Path, extensions: list[str], recursive: bool
    ) -> list[Sample]:
        files: list[Path] = []
        for ext in extensions:
            ext = ext if ext.startswith(".") else f".{ext}"
            if recursive:
                files.extend(directory.rglob(f"*{ext}"))
            else:
                files.extend(directory.glob(f"*{ext}"))

        files = sorted(set(files))
        self.log.info("found %d files in %s", len(files), directory)
        return self._analyze_files(ctx, files)

    def _analyze_files(self, ctx: ProcessorContext, files: list[Path]) -> list[Sample]:
        import time
        from concurrent.futures import ThreadPoolExecutor

        samples = []
        total = len(files)
        limit = self.config.get("limit", 0)
        start = time.monotonic()

        ctx.progress.update(
            total=min(limit, total) if limit > 0 else total, description="starting analysis..."
        )

        subsys_filter = self.config.get("subsystem_filter", [])
        max_workers = ctx.get_setting("max_workers", 8)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # We map in order, so progress is more stable
            for i, (f, meta, data) in enumerate(executor.map(_io_worker, files)):
                if data is not None and data[:2] == b"MZ":
                    # run pefile in main thread strictly to avoid GIL thrashing
                    meta.update(_parse_pe(data, subsys_filter))

                sample_id = meta.get("sha256", "")[:16] or f.stem
                samples.append(
                    Sample(sample_id=sample_id, source_path=f, filename=f.name, data=meta)
                )

                ctx.progress.update(amount=1, description=f.name)

                if (i + 1) % 500 == 0 or (i + 1) == total:
                    elapsed = time.monotonic() - start
                    rate = (i + 1) / elapsed if elapsed > 0 else 0
                    self.log.info(
                        "pe analysis: %d/%d (%.0f files/s, %.0fs elapsed)",
                        i + 1,
                        total,
                        rate,
                        elapsed,
                    )

                if limit > 0 and len(samples) >= limit:
                    self.log.info(
                        "reached limit of %d samples, stopping early (%d/%d files scanned)",
                        limit,
                        i + 1,
                        total,
                    )
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

        self.log.info(
            "ingest complete: %d samples in %.1fs",
            len(samples),
            time.monotonic() - start,
        )
        return samples

    def _extract_metadata(self, path: Path) -> dict[str, Any]:
        # For single file non-parallel parsing backward compat
        _, meta, data = _io_worker(path)
        if data is not None and data[:2] == b"MZ":
            meta.update(_parse_pe(data, self.config.get("subsystem_filter", [])))
        return meta


def _io_worker(f: Path) -> tuple[Path, dict[str, Any], bytes | None]:
    try:
        data = f.read_bytes()
        sha256 = hashlib.sha256(data).hexdigest()
        md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()  # noqa: S324
        return f, {"sha256": sha256, "md5": md5, "size_bytes": len(data)}, data
    except OSError as e:
        return f, {"error": f"cannot read: {e}"}, None


def _parse_pe(data: bytes, subsystem_filter: list[int]) -> dict[str, Any]:
    try:
        import lief
    except ImportError:
        return {}

    try:
        pe = lief.parse(data)
        if pe is None or not isinstance(pe, lief.PE.Binary):
            return {"is_valid_pe": False}
    except Exception:
        return {"is_valid_pe": False}

    subsys = pe.optional_header.subsystem
    subsys_name = subsys.name
    is_kernel_driver = subsys_name == "NATIVE"
    machine_name = pe.header.machine.name

    meta: dict[str, Any] = {
        "is_valid_pe": True,
        "subsystem": subsys_name,
        "is_kernel_driver": is_kernel_driver,
        "machine_type": machine_name,
    }

    if subsystem_filter and subsys.value not in subsystem_filter:
        meta["reject_reason"] = f"subsystem {subsys.value} not in filter {subsystem_filter}"
        return meta

    imported_functions = []
    imported_dlls = []
    for imp in pe.imports:
        imported_dlls.append(imp.name)
        for entry in imp.entries:
            if entry.name:
                imported_functions.append(entry.name)

    meta["imported_dlls"] = imported_dlls
    meta["imported_functions"] = imported_functions

    func_set = set(imported_functions)

    ioctl_indicators = {
        "IoCreateDevice",
        "IoCreateDeviceSecure",
        "IoCreateSymbolicLink",
        "IofCompleteRequest",
        "IoCompleteRequest",
        "WdfDeviceCreate",
        "WdfDeviceCreateSymbolicLink",
        "WdfIoQueueCreate",
        "WdfRequestComplete",
        "WdfDriverCreate",
        "NdisMRegisterMiniportDriver",
        "NdisFRegisterFilterDriver",
        "StorPortInitialize",
        "ScsiPortInitialize",
        "HidRegisterMinidriver",
        "IoRegisterDeviceInterface",
    }
    meta["has_ioctl_surface"] = bool(func_set & ioctl_indicators)
    meta["creates_device"] = "IoCreateDevice" in func_set
    meta["creates_symlink"] = "IoCreateSymbolicLink" in func_set

    dangerous_apis = {
        "MmMapIoSpace",
        "MmUnmapIoSpace",
        "ZwMapViewOfSection",
        "ZwOpenSection",
        "MmGetPhysicalAddress",
        "MmCopyVirtualMemory",
        "MmCopyMemory",
        "PsLookupProcessByProcessId",
        "ZwOpenProcess",
        "ZwTerminateProcess",
        "KeStackAttachProcess",
        "__readmsr",
        "__writemsr",
        "HalGetBusDataByOffset",
        "HalSetBusDataByOffset",
        "MmProbeAndLockPages",
        "IoAllocateMdl",
        "MmIsAddressValid",
        "ZwLoadDriver",
        "MmLoadSystemImage",
    }
    meta["dangerous_imports"] = sorted(func_set & dangerous_apis)

    is_signed = False
    try:
        is_signed = len(pe.signatures) > 0
    except AttributeError:
        pass
    meta["is_signed"] = is_signed

    score = 0.0
    if meta["has_ioctl_surface"]:
        phys_mem = {
            "MmMapIoSpace",
            "ZwMapViewOfSection",
            "ZwOpenSection",
            "MmGetPhysicalAddress",
        }
        proc_manip = {
            "PsLookupProcessByProcessId",
            "ZwTerminateProcess",
            "ZwOpenProcess",
        }
        msr_io = {
            "__readmsr",
            "__writemsr",
            "HalGetBusDataByOffset",
            "HalSetBusDataByOffset",
        }

        if func_set & phys_mem:
            score += 3.0
        if func_set & proc_manip:
            score += 2.0
        if func_set & msr_io:
            score += 2.0
        if pe.header.numberof_sections <= 6:
            score += 1.0

    try:
        if pe.optional_header.major_operating_system_version >= 10:
            score += 3.0
    except AttributeError:
        pass

    meta["priority_score"] = min(10.0, score)

    try:
        meta["imphash"] = lief.PE.get_imphash(pe) or ""
    except Exception:
        meta["imphash"] = ""

    return meta
