from __future__ import annotations

import hashlib

from deepzero.engine.stage import ProcessorContext, StageSpec
from processors.pe_ingest.pe_ingest import PEIngest


class TestPEIngestDiscover:
    def _make_tool(self):
        spec = StageSpec(name="discover", processor="pe_ingest")
        return PEIngest(spec)

    def test_discover_single_file(self, tmp_path):
        processor = self._make_tool()
        target = tmp_path / "test.sys"
        target.write_bytes(b"NOT A PE FILE")

        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=None)
        samples = processor.process(ctx, target)
        assert len(samples) == 1
        assert samples[0].filename == "test.sys"
        # should have sha256 and md5 in data
        assert "sha256" in samples[0].data
        assert "md5" in samples[0].data
        expected = hashlib.sha256(b"NOT A PE FILE").hexdigest()
        assert samples[0].data["sha256"] == expected

    def test_discover_directory(self, tmp_path):
        processor = self._make_tool()

        (tmp_path / "a.sys").write_bytes(b"file_a")
        (tmp_path / "b.sys").write_bytes(b"file_b")
        (tmp_path / "c.exe").write_bytes(b"file_c")

        # default extensions is [".sys"]
        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=None)
        samples = processor.process(ctx, tmp_path)
        assert len(samples) == 2
        filenames = {s.filename for s in samples}
        assert "a.sys" in filenames
        assert "b.sys" in filenames

    def test_discover_respects_extensions(self, tmp_path):
        processor = self._make_tool()

        (tmp_path / "driver.sys").write_bytes(b"sys")
        (tmp_path / "app.exe").write_bytes(b"exe")
        (tmp_path / "readme.txt").write_bytes(b"txt")

        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=None)
        processor.config["extensions"] = [".exe"]
        samples = processor.process(ctx, tmp_path)
        assert len(samples) == 1
        assert samples[0].filename == "app.exe"

    def test_discover_missing_target(self, tmp_path):
        processor = self._make_tool()
        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=None)
        samples = processor.process(ctx, tmp_path / "nope")
        assert len(samples) == 0

    def test_discover_recursive(self, tmp_path):
        processor = self._make_tool()
        sub = tmp_path / "nested"
        sub.mkdir()
        (tmp_path / "root.sys").write_bytes(b"top")
        (sub / "deep.sys").write_bytes(b"nested")

        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=None)
        processor.config["recursive"] = True
        samples = processor.process(ctx, tmp_path)
        assert len(samples) == 2

    def test_discover_non_recursive(self, tmp_path):
        processor = self._make_tool()
        sub = tmp_path / "nested"
        sub.mkdir()
        (tmp_path / "root.sys").write_bytes(b"top")
        (sub / "deep.sys").write_bytes(b"nested")

        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=None)
        processor.config["recursive"] = False
        samples = processor.process(ctx, tmp_path)
        assert len(samples) == 1
        assert samples[0].filename == "root.sys"

    def test_discover_with_subdirs_filter(self, tmp_path):
        processor = self._make_tool()
        match_dir = tmp_path / "matching_pack"
        match_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()

        (match_dir / "a.sys").write_bytes(b"match")
        (other_dir / "b.sys").write_bytes(b"other")

        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=None)
        processor.config["subdirs"] = ["matching"]
        samples = processor.process(ctx, tmp_path)
        assert len(samples) >= 1
        filenames = {s.filename for s in samples}
        assert "a.sys" in filenames


class TestPEIngestMetadata:
    def _make_tool(self):
        spec = StageSpec(name="discover", processor="pe_ingest")
        return PEIngest(spec)

    def test_metadata_has_hashes(self, tmp_path):
        processor = self._make_tool()
        f = tmp_path / "test.sys"
        content = b"test content"
        f.write_bytes(content)

        ctx = ProcessorContext(pipeline_dir=tmp_path, global_config={}, llm=None)
        samples = processor.process(ctx, f)
        data = samples[0].data
        assert data["sha256"] == hashlib.sha256(content).hexdigest()
        assert data["md5"] == hashlib.md5(content, usedforsecurity=False).hexdigest()
        assert data["size_bytes"] == len(content)
