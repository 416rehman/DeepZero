from __future__ import annotations

import hashlib
from pathlib import Path

from deepzero.engine.stage import IngestProcessor, ProcessorContext, Sample


class FileDiscovery(IngestProcessor):
    cache_global_keys = ()
    description = "generic file discovery - finds files by extension, no format parsing"

    # both are recorded for every sample, in single-file mode and in directory
    # mode alike, so a later prompt can name either one
    provides = ("sha256", "size_bytes")

    def process(self, ctx: ProcessorContext, target: Path) -> list[Sample]:
        extensions = self.config.get("extensions", [])
        recursive = self.config.get("recursive", True)

        if target.is_file():
            return self._discover_single(target)

        if not target.is_dir():
            raise FileNotFoundError(f"target does not exist: {target}")

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

        # a directory can carry the extension being hunted too, so both branches
        # test for a file rather than trusting the glob to have found one
        if recursive:
            if extensions:
                for ext in extensions:
                    ext = ext if ext.startswith(".") else f".{ext}"
                    files.extend(f for f in directory.rglob(f"*{ext}") if f.is_file())
            else:
                files = [f for f in directory.rglob("*") if f.is_file()]
        else:
            if extensions:
                for ext in extensions:
                    ext = ext if ext.startswith(".") else f".{ext}"
                    files.extend(f for f in directory.glob(f"*{ext}") if f.is_file())
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
