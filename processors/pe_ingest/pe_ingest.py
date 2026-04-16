from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from deepzero.engine.stage import IngestProcessor, Sample, ProcessorContext


class PEIngest(IngestProcessor):
    description = "discovers portable executable files, parses PE headers, and extracts driver metadata"
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
            return self._ingest_filtered(target, subdirs, extensions)

        return self._ingest_directory(target, extensions, recursive)

    def _ingest_single(self, path: Path) -> list[Sample]:
        self.log.info("single file mode: %s", path.name)
        data = self._extract_metadata(path)
        sample_id = data.get("sha256", "")[:16] or path.stem
        return [
            Sample(sample_id=sample_id, source_path=path, filename=path.name, data=data)
        ]

    def _ingest_filtered(
        self, root: Path, subdirs: list[str], extensions: list[str]
    ) -> list[Sample]:
        all_dirs = sorted(d for d in root.iterdir() if d.is_dir())
        matching = [
            d for d in all_dirs if any(p.lower() in d.name.lower() for p in subdirs)
        ]

        if not matching:
            self.log.warning(
                "no subdirectories matched patterns %s in %s", subdirs, root
            )
            return self._ingest_directory(root, extensions, True)

        self.log.info(
            "scanning %d/%d matching subdirectories", len(matching), len(all_dirs)
        )

        files: list[Path] = []
        for pack_dir in matching:
            for ext in extensions:
                ext = ext if ext.startswith(".") else f".{ext}"
                files.extend(pack_dir.rglob(f"*{ext}"))

        files = sorted(set(files))
        self.log.info("found %d files across %d directories", len(files), len(matching))
        return self._analyze_files(files)

    def _ingest_directory(
        self, directory: Path, extensions: list[str], recursive: bool
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
        return self._analyze_files(files)

    def _analyze_files(self, files: list[Path]) -> list[Sample]:
        import time

        samples = []
        total = len(files)
        limit = self.config.get("limit", 0)
        start = time.monotonic()

        for i, f in enumerate(files):
            data = self._extract_metadata(f)
            sample_id = data.get("sha256", "")[:16] or f.stem
            samples.append(
                Sample(sample_id=sample_id, source_path=f, filename=f.name, data=data)
            )

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
                break

        self.log.info(
            "ingest complete: %d samples in %.1fs",
            len(samples),
            time.monotonic() - start,
        )
        return samples

    def _extract_metadata(self, path: Path) -> dict[str, Any]:
        try:
            data = path.read_bytes()
        except OSError as e:
            return {"error": f"cannot read: {e}"}

        sha256 = hashlib.sha256(data).hexdigest()
        md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()  # noqa: S324
        meta: dict[str, Any] = {"sha256": sha256, "md5": md5, "size_bytes": len(data)}

        subsystem_filter = self.config.get("subsystem_filter", [])
        if data[:2] == b"MZ":
            meta.update(self._parse_pe(data, subsystem_filter))

        return meta

    def _parse_pe(self, data: bytes, subsystem_filter: list[int]) -> dict[str, Any]:
        try:
            import pefile
        except ImportError:
            return {}

        try:
            pe = pefile.PE(data=data, fast_load=True)
        except (OSError, ValueError, AttributeError) as exc:
            self.log.debug("pe parse failed: %s", exc)
            return {"is_valid_pe": False}

        subsys = pe.OPTIONAL_HEADER.Subsystem
        subsys_names = {1: "NATIVE", 2: "WINDOWS_GUI", 3: "WINDOWS_CUI"}
        is_kernel_driver = subsys == 1
        machine_types = {0x14C: "I386", 0x8664: "AMD64", 0xAA64: "ARM64"}
        machine = machine_types.get(
            pe.FILE_HEADER.Machine, f"0x{pe.FILE_HEADER.Machine:04X}"
        )

        meta: dict[str, Any] = {
            "is_valid_pe": True,
            "subsystem": subsys_names.get(subsys, str(subsys)),
            "is_kernel_driver": is_kernel_driver,
            "machine_type": machine,
        }

        if subsystem_filter and subsys not in subsystem_filter:
            meta["reject_reason"] = (
                f"subsystem {subsys} not in filter {subsystem_filter}"
            )
            pe.close()
            return meta

        try:
            pe.parse_data_directories(
                directories=[
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_SECURITY"],
                ]
            )
        except (OSError, AttributeError, ValueError) as exc:
            self.log.debug("pe data directory parse error: %s", exc)

        imported_functions = []
        imported_dlls = []
        if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
            for entry in pe.DIRECTORY_ENTRY_IMPORT:
                dll = entry.dll.decode("utf-8", errors="replace")
                imported_dlls.append(dll)
                for imp in entry.imports:
                    if imp.name:
                        imported_functions.append(
                            imp.name.decode("utf-8", errors="replace")
                        )

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

        try:
            sec_dir = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
            meta["is_signed"] = sec_dir.VirtualAddress != 0 and sec_dir.Size != 0
        except (IndexError, AttributeError):
            meta["is_signed"] = False

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
            if pe.FILE_HEADER.NumberOfSections <= 6:
                score += 1.0
            try:
                if pe.OPTIONAL_HEADER.MajorOperatingSystemVersion >= 10:
                    score += 3.0
            except (AttributeError, IndexError):
                self.log.debug("could not read os version from PE header")

        meta["priority_score"] = min(10.0, score)

        try:
            meta["imphash"] = pe.get_imphash() or ""
        except (AttributeError, ValueError, IndexError) as exc:
            self.log.debug("imphash extraction failed: %s", exc)
            meta["imphash"] = ""

        pe.close()
        return meta
