from __future__ import annotations

import json

from deepzero.engine.stage import StageContext, StageSpec
from deepzero.engine.state import StageOutput
from tools.loldrivers_filter.loldrivers_filter import LoldriversFilter


class TestLoldriversFilterLoad:
    def _make_filter(self, config: dict | None = None):
        spec = StageSpec(name="loldrivers", tool="loldrivers_filter", config=config or {})
        return LoldriversFilter(spec)

    def test_load_valid_db(self, tmp_path):
        flt = self._make_filter()
        db = tmp_path / "drivers.json"
        db.write_text(json.dumps([
            {"KnownVulnerableSamples": [
                {"SHA256": "AAAA1111bbbb2222cccc3333dddd4444eeee5555ffff6666"},
                {"SHA256": "1234567890abcdef1234567890abcdef1234567890abcdef"},
            ]},
            {"KnownVulnerableSamples": [
                {"SHA256": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
            ]},
        ]))
        flt._load_db(db)
        assert len(flt._known_hashes) == 3
        assert "aaaa1111bbbb2222cccc3333dddd4444eeee5555ffff6666" in flt._known_hashes

    def test_load_empty_db(self, tmp_path):
        flt = self._make_filter()
        db = tmp_path / "drivers.json"
        db.write_text("[]")
        flt._load_db(db)
        assert len(flt._known_hashes) == 0

    def test_load_corrupt_db(self, tmp_path):
        flt = self._make_filter()
        db = tmp_path / "drivers.json"
        db.write_text("not valid json")
        flt._load_db(db)
        assert len(flt._known_hashes) == 0

    def test_load_entries_without_sha(self, tmp_path):
        flt = self._make_filter()
        db = tmp_path / "drivers.json"
        db.write_text(json.dumps([
            {"KnownVulnerableSamples": [{"MD5": "abcd1234"}]},
        ]))
        flt._load_db(db)
        assert len(flt._known_hashes) == 0


class TestLoldriversFilterProcess:
    def _make_ctx(self, tmp_path, sha256="abcdef"):
        sample_path = tmp_path / "test.sys"
        sample_path.write_bytes(b"MZ")

        sample_dir = tmp_path / "work" / "abc"
        sample_dir.mkdir(parents=True)

        history = {"discover": StageOutput(
            status="completed",
            data={"sha256": sha256, "size_bytes": 1024},
        )}
        return StageContext(
            sample_path=sample_path,
            sample_dir=sample_dir,
            history=history,
            config={},
            pipeline_dir=tmp_path,
            global_config={},
            llm=None,
        )

    def test_passes_unknown_sample(self, tmp_path):
        spec = StageSpec(name="loldrivers", tool="loldrivers_filter")
        flt = LoldriversFilter(spec)
        flt._known_hashes = {"deadbeef"}

        ctx = self._make_ctx(tmp_path, sha256="cafebabe")
        result = flt.process(ctx)
        assert result.verdict == "continue"

    def test_skips_known_sample(self, tmp_path):
        spec = StageSpec(name="loldrivers", tool="loldrivers_filter")
        flt = LoldriversFilter(spec)
        flt._known_hashes = {"cafebabe"}

        ctx = self._make_ctx(tmp_path, sha256="CAFEBABE")
        result = flt.process(ctx)
        assert result.verdict == "skip"
        assert "loldrivers" in result.data.get("reject_reason", "")

    def test_passes_everything_without_db(self, tmp_path):
        spec = StageSpec(name="loldrivers", tool="loldrivers_filter")
        flt = LoldriversFilter(spec)
        # empty known_hashes — db not loaded

        ctx = self._make_ctx(tmp_path, sha256="anything")
        result = flt.process(ctx)
        assert result.verdict == "continue"
