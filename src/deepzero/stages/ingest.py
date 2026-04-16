from __future__ import annotations

import hashlib
from pathlib import Path

from deepzero.engine.stage import IngestProcessor, ProcessorContext, Sample


class FileDiscovery(IngestProcessor):
    description = "generic file discovery - finds files by extension, no format parsing"

    def process(self, ctx: ProcessorContext, target: Path) -> list[Sample]:
        extensions = self.config.get("extensions", [])
        recursive = self.config.get("recursive", True)

        if target.is_file():
            return self._discover_single(target)

        if not target.is_dir():
            self.log.error("target does not exist: %s", target)
            return []

        return self._discover_directory(target, extensions, recursive)

    def _discover_single(self, path: Path) -> list[Sample]:
        self.log.info("single file mode: %s", path.name)
        sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        return [
            Sample(
                sample_id=sha256[:16],
                source_path=path,
                filename=path.name,
                data={"sha256": sha256, "size_bytes": path.stat().st_size},
            )
        ]

    def _discover_directory(
        self, directory: Path, extensions: list[str], recursive: bool
    ) -> list[Sample]:
        files: list[Path] = []

        if recursive:
            if extensions:
                for ext in extensions:
                    ext = ext if ext.startswith(".") else f".{ext}"
                    files.extend(directory.rglob(f"*{ext}"))
            else:
                files = [f for f in directory.rglob("*") if f.is_file()]
        else:
            if extensions:
                for ext in extensions:
                    ext = ext if ext.startswith(".") else f".{ext}"
                    files.extend(directory.glob(f"*{ext}"))
            else:
                files = [f for f in directory.iterdir() if f.is_file()]

        files = sorted(set(files))
        self.log.info("found %d files in %s", len(files), directory)

        samples = []
        for f in files:
            try:
                sha256 = hashlib.sha256(f.read_bytes()).hexdigest()
            except OSError as e:
                self.log.debug("skipping unreadable file %s: %s", f.name, e)
                continue

            samples.append(
                Sample(
                    sample_id=sha256[:16],
                    source_path=f,
                    filename=f.name,
                    data={"sha256": sha256, "size_bytes": f.stat().st_size},
                )
            )

        self.log.info("discovered %d samples", len(samples))
        return samples
