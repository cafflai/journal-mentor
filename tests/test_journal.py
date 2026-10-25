"""Synthetic data only. Never discovers or reads the user's diary directory."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents/skills/journal-mentor/scripts/journal.py"
spec = importlib.util.spec_from_file_location("journal", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
WORK = ROOT / ".test-work"
WORK.mkdir(exist_ok=True)


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-", dir=WORK)
        self.root = Path(self.temp.name).resolve()
        self.j = module.Journal(self.root)

    def tearDown(self):
        # The only recursive cleanup is the verified, generated test workspace.
        self.assertTrue(self.root.is_relative_to(WORK.resolve()))
        self.temp.cleanup()

    def diary(self, filename="2026-10-14.md", text="今天明确了求职方向，也感到紧张。"):
        path = self.root / "diary" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def collect(self, **kwargs):
        return self.j.collect(today="2026-10-14", **kwargs)

    def record(self, batch, key="stage-001", kind="stage", status="active"):
        return {"id": key, "kind": kind, "status": status, "current": True,
                "text": "用户表示正在求职。", "discussion": [],
                "sources": [{k: batch["entries"][0][k] for k in ("path", "date", "sha256")}]}

    def draft(self, records=(), review="# 虚构复盘\n\n记录显示阶段发生了变化。", **extra):
        self.j.write("memory/draft.json", module.encoded({"review": review, "records": list(records), **extra}))

    def completed(self):
        self.diary()
        batch = self.collect()
        record = self.record(batch)
        self.draft([record])
        result = self.j.finish()
        return record, result

    def test_initial_window_and_no_old_profile(self):
        self.diary("2026-10-07.md", "旧记录")
        self.diary("2026-10-08.md", "边界记录")
        self.diary()
        result = self.collect()
        self.assertEqual(result["range"]["start"], "2026-10-08")
        self.assertEqual(len(result["entries"]), 2)
        self.assertEqual(result["outside_range_count"], 1)
        self.assertFalse((self.root / "memory/store.json").exists())

    def test_finish_and_restart_incremental(self):
        _, result = self.completed()
        self.assertTrue((self.root / result["saved"]).exists())
        restarted = module.Journal(self.root)
        self.assertEqual(len(restarted.recall()["records"]), 1)
        self.assertIsNone(restarted.collect(today="2026-10-14")["batch_id"])
        self.assertFalse((self.root / "memory/draft.json").exists())

    def test_pending_not_overwritten(self):
        self.diary()
        self.collect()
        before = (self.root / "memory/pending.json").read_bytes()
        with self.assertRaises(module.JournalError):
            self.collect()
        self.assertEqual(before, (self.root / "memory/pending.json").read_bytes())

    def test_source_edit_during_dialogue_rejected(self):
        source = self.diary()
        batch = self.collect()
        self.draft([self.record(batch)])
        source.write_text("修正：还没有开始求职。", encoding="utf-8")
        with self.assertRaises(module.JournalError):
            self.j.finish()
        self.assertIsNone(self.j.load()["last_default_end"])

    def test_revision_invalidation_and_repair(self):
        old, report = self.completed()
        self.diary(text="修正：已经创业，暂无求职计划。")
        recall = self.j.recall()
        self.assertEqual(recall["stale_record_ids"], [old["id"]])
        self.assertEqual(recall["records"], [])
        batch = self.collect()
        self.draft([])
        with self.assertRaises(module.JournalError):
            self.j.finish()
        new = self.record(batch)
        new["text"] = "用户表示已经创业。"
        self.draft([new])
        self.j.finish()
        self.assertEqual((self.root / report["saved"]).read_text(encoding="utf-8"), module.RETRACTED)
        self.assertEqual(len(self.j.load()["records"]), 1)

    def test_missing_source_can_be_retracted_without_inventing_evidence(self):
        old, _ = self.completed()
        (self.root / "diary/2026-10-14.md").unlink()
        self.collect()
        old["status"] = "retracted"
        old["current"] = False
        self.draft([old])
        self.j.finish()
        self.assertEqual(self.j.load()["processed"], {})
        self.assertEqual(self.j.stale(self.j.load()), [])

    def test_unknown_date_does_not_advance_cursor(self):
        self.diary("随手记.md", "不知道日期")
        self.diary()
        batch = self.collect()
        self.assertEqual(batch["undated_or_conflicting"], ["diary/随手记.md"])
        self.draft([])
        self.j.finish()
        self.assertIsNone(self.j.load()["last_default_end"])
        batch = self.collect(overrides={"diary/随手记.md": "2026-10-13"})
        self.assertEqual(batch["entries"][0]["date"], "2026-10-13")

    def test_header_date_conflict_and_override(self):
        self.diary("2026-10-14记.md", "---\ndate: 2026-10-13\n---\n今天的记录")
        result = self.collect()
        self.assertEqual(result["entries"], [])
        self.assertTrue(result["undated_or_conflicting"])
        result = self.collect(overrides={"diary/2026-10-14记.md": "2026-10-13"})
        self.assertEqual(result["entries"][0]["date"], "2026-10-13")

    def test_header_only_date(self):
        self.diary("记录.md", "---\ndate: '2026-10-14'\n---\n记录")
        self.assertEqual(len(self.collect()["entries"]), 1)

    def test_confirmed_date_override_persists(self):
        self.diary("2026-10-14.md", "---\ndate: 2026-10-13\n---\n记录")
        self.collect(overrides={"diary/2026-10-14.md": "2026-10-13"})
        self.draft([])
        self.j.finish()
        result = self.collect()
        self.assertFalse(result["undated_or_conflicting"])
        self.assertIsNone(result["batch_id"])

    def test_date_correction_requires_memory_source_update(self):
        old, _ = self.completed()
        batch = self.collect(overrides={"diary/2026-10-14.md": "2026-10-13"})
        self.draft([])
        with self.assertRaises(module.JournalError):
            self.j.finish()
        replacement = self.record(batch)
        self.draft([replacement])
        self.j.finish()
        self.assertEqual(self.j.load()["records"][old["id"]]["sources"][0]["date"], "2026-10-13")

    def test_explicit_history_does_not_skip_default_window(self):
        self.diary("2026-09-01.md", "旧记录")
        self.collect(start="2026-09-01", end="2026-09-01")
        self.draft([])
        self.j.finish()
        self.assertIsNone(self.j.load()["last_default_end"])
        self.diary()
        self.assertEqual(len(self.collect()["entries"]), 1)

    def test_late_added_entry_in_baseline_is_seen(self):
        self.completed()
        self.diary("2026-10-10.md", "补记之前一天的事件")
        batch = self.collect()
        self.assertEqual(batch["entries"][0]["date"], "2026-10-10")

    def test_original_bytes_never_changed(self):
        path = self.diary(text="---\r\ndate: 2026-10-14\r\n---\r\n原文\r\n")
        before = path.read_bytes()
        self.collect()
        self.draft([])
        self.j.finish()
        self.assertEqual(before, path.read_bytes())

    def test_path_escape_rejected(self):
        for path in ("../private.md", "diary/../../secret.md", "C:/secret.md", "/secret.md", "diary\\secret.md"):
            with self.assertRaises(module.JournalError):
                self.j.path(path)

    def test_directory_link_escape_rejected(self):
        outside = self.root / "outside"
        outside.mkdir()
        link = self.root / "diary/link"
        if os.name == "nt":
            # PowerShell's native junction creation; no shell-to-shell file operation.
            command = "New-Item -ItemType Junction -Path '" + str(link).replace("'", "''") + "' -Target '" + str(outside).replace("'", "''") + "' | Out-Null"
            subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True, capture_output=True)
        else:
            link.symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaises(module.JournalError):
                self.collect()
        finally:
            # Remove only the link, never the target tree.
            if os.name == "nt":
                os.rmdir(link)
            else:
                link.unlink()

    def test_action_requires_user_adoption(self):
        self.diary()
        batch = self.collect()
        record = self.record(batch, "action-001", "action", "accepted")
        self.draft([record])
        with self.assertRaises(module.JournalError):
            self.j.finish()
        record["adoption"] = {"date": "2026-10-14", "quote": "我决定尝试这个办法。"}
        self.draft([record])
        self.j.finish()
        self.assertEqual(self.j.load()["records"]["action-001"]["status"], "accepted")

    def test_hypothesis_cannot_be_confirmed_personality(self):
        self.diary()
        batch = self.collect()
        self.draft([self.record(batch, "pattern-001", "hypothesis", "confirmed")])
        with self.assertRaises(module.JournalError):
            self.j.finish()

    def test_duplicate_claim_rejected(self):
        old, _ = self.completed()
        new = copy.deepcopy(old)
        new["id"] = "stage-002"
        self.draft([new], base_revision=self.j.load()["revision"])
        with self.assertRaises(module.JournalError):
            self.j.amend()

    def test_project_isolation(self):
        self.completed()
        sibling = self.root / "another-project"
        sibling.mkdir()
        other = module.Journal(sibling)
        self.assertEqual(other.recall()["records"], [])
        self.assertEqual(other.load()["processed"], {})

    def test_amend_current_stage_keeps_history(self):
        old, report = self.completed()
        old["current"] = False
        old["status"] = "historical"
        new = {"id": "stage-002", "kind": "stage", "status": "active", "current": True,
               "text": "现在在经营自己的业务。", "sources": [],
               "discussion": [{"date": "2026-10-14", "quote": "我已经开始创业了。"}]}
        self.draft([old, new], base_revision=self.j.recall()["revision"])
        self.j.amend()
        records = self.j.load()["records"]
        self.assertFalse(records["stage-001"]["current"])
        self.assertTrue(records["stage-002"]["current"])
        self.assertEqual(self.j.load()["last_default_end"], "2026-10-14")
        self.assertEqual((self.root / report["saved"]).read_text(encoding="utf-8"), module.RETRACTED)

    def test_forget_removes_derived_copies_and_keeps_diary(self):
        old, report = self.completed()
        before = (self.root / "memory/store.json").read_bytes()
        preview = self.j.forget(old["id"])
        self.assertFalse(preview["applied"])
        self.assertEqual(before, (self.root / "memory/store.json").read_bytes())
        self.draft([old])
        self.j.forget(old["id"], apply=True)
        store = self.j.load()
        self.assertNotIn(old["id"], store["records"])
        self.assertNotIn(old["text"], json.dumps(store, ensure_ascii=False))
        self.assertEqual((self.root / report["saved"]).read_text(encoding="utf-8"), module.RETRACTED)
        self.assertTrue((self.root / "diary/2026-10-14.md").exists())
        self.assertFalse((self.root / "memory/draft.json").exists())
        self.draft([old], base_revision=store["revision"])
        with self.assertRaises(module.JournalError):
            self.j.amend()

    def test_export_failure_recoverable(self):
        self.diary()
        self.collect()
        self.draft([])
        with patch.object(self.j, "export", side_effect=OSError("test disk failure")):
            result = self.j.finish()
        self.assertIsNotNone(result["warning"])
        self.j.export()
        self.assertTrue((self.root / result["saved"]).exists())

    def test_lock_prevents_concurrent_mutations(self):
        with self.j.locked():
            with self.assertRaises(module.JournalError):
                self.collect()

    def test_cli_privacy_gate_precedes_data_access(self):
        result = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "collect"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertIn("隔离", result.stderr)


if __name__ == "__main__":
    unittest.main()
