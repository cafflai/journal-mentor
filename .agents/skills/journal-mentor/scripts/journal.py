"""Project-local diary collection and evidence/version bookkeeping. No network or LLM calls."""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
import uuid

SHANGHAI = timezone(timedelta(hours=8))
DATE_PATTERN = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
STATUSES = {
    "fact": {"active", "historical", "retracted"},
    "stage": {"active", "historical", "retracted"},
    "goal": {"active", "historical", "retracted"},
    "correction": {"active", "historical", "retracted"},
    "hypothesis": {"tentative", "rejected", "retracted"},
    "action": {"proposed", "accepted", "tried", "completed", "dropped"},
}
RETRACTED = "# 已撤回的复盘\n\n相关来源或项目记忆已更新/删除。这份旧报告不再作为判断依据。撤回操作不会修改日记原文。\n"


class JournalError(ValueError):
    pass


def iso(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise JournalError("日期必须是 YYYY-MM-DD。")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise JournalError("无效日期。") from exc


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def stamp():
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def blank_store():
    return {"version": 1, "revision": 0, "last_default_end": None,
            "baseline_start": None, "date_overrides": {},
            "processed": {}, "records": {}, "reviews": {}, "forgotten_ids": []}


class Journal:
    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        # Validate before creating anything; disallow junctions/symlinks even within root.
        for name in ("diary", "memory", "reviews"):
            self.path(name).mkdir(exist_ok=True)

    def path(self, relative):
        if not isinstance(relative, str) or "\\" in relative or ":" in relative:
            raise JournalError("仅支持项目内的相对路径（使用 /）。")
        part = PurePosixPath(relative)
        if part.is_absolute() or ".." in part.parts or not part.parts:
            raise JournalError("路径越出项目边界。")
        current = self.root
        for component in part.parts:
            current = current / component
            if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
                raise JournalError("拒绝链接或目录联接：" + relative)
            if os.path.lexists(current):
                # Windows reparse points (also works before Path.is_junction existed).
                if getattr(current.lstat(), "st_file_attributes", 0) & 0x400:
                    raise JournalError("拒绝重解析路径：" + relative)
        if not current.resolve().is_relative_to(self.root):
            raise JournalError("路径越出项目边界。")
        return current

    def diary_path(self, relative):
        if not relative.startswith("diary/") or not relative.lower().endswith(".md"):
            raise JournalError("来源必须是 diary/ 内的 Markdown。")
        return self.path(relative)

    def read_json(self, relative, default=None):
        target = self.path(relative)
        if not target.exists():
            return copy.deepcopy(default)
        try:
            return json.loads(target.read_text(encoding="utf-8-sig"))
        except (ValueError, UnicodeError) as exc:
            raise JournalError("JSON 文件无法读取：" + relative) from exc

    def write(self, relative, raw):
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".write-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            self.path(relative)  # Recheck immediately before replace.
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def remove(self, relative):
        self.path(relative).unlink(missing_ok=True)

    @contextmanager
    def locked(self):
        lock = self.path("memory/.lock")
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise JournalError("项目正在被另一操作使用。若上次异常退出，请确认无操作运行后清理 memory/.lock。") from exc
        try:
            os.close(fd)
            yield
        finally:
            lock.unlink(missing_ok=True)

    def load(self):
        store = self.read_json("memory/store.json", blank_store())
        if not isinstance(store, dict) or store.get("version") != 1:
            raise JournalError("不支持的存储版本；不要覆盖原文件。")
        return store

    def files(self):
        for directory, dirs, files in os.walk(self.path("diary"), followlinks=False):
            for name in dirs + files:
                relative = (Path(directory) / name).relative_to(self.root).as_posix()
                self.path(relative)
            for name in sorted(files):
                if name.lower().endswith(".md"):
                    yield (Path(directory) / name).relative_to(self.root).as_posix()

    def file_date(self, relative, overrides):
        if relative in overrides:
            return iso(overrides[relative]).isoformat()
        matches = set(DATE_PATTERN.findall(Path(relative).stem))
        # Only a short local header is inspected for dating, not emitted to the model.
        with self.diary_path(relative).open("rb") as handle:
            header = handle.read(4096).decode("utf-8-sig", errors="replace")
        if header.startswith("---\n") or header.startswith("---\r\n"):
            frontmatter = re.split(r"\r?\n---(?:\r?\n|$)", header, maxsplit=1)[0]
            field = re.search(r"(?m)^date:\s*['\"]?(\d{4}-\d{2}-\d{2})(?:['\"]?\s*)$", frontmatter)
            if field:
                matches.add(field.group(1))
        if len(matches) != 1:
            return "" if matches else None
        try:
            return iso(next(iter(matches))).isoformat()
        except JournalError:
            return ""

    def evidence_valid(self, source):
        try:
            path = self.diary_path(source["path"])
            iso(source["date"])
            return path.is_file() and digest(path.read_bytes()) == source["sha256"]
        except (OSError, JournalError, KeyError, TypeError):
            return False

    def stale(self, store):
        return [key for key, record in store["records"].items()
                if record["status"] != "retracted" and
                any(not self.evidence_valid(s) for s in record.get("sources", []))]

    def recall(self):
        store = self.load()
        stale = self.stale(store)
        return {"revision": store["revision"], "stale_record_ids": stale,
                "records": [r for key, r in store["records"].items() if key not in stale],
                "forgotten_ids": store["forgotten_ids"]}

    def collect(self, today=None, start=None, end=None, overrides=None, replace=False):
        with self.locked():
            pending_path = self.path("memory/pending.json")
            if pending_path.exists() and not replace:
                raise JournalError("已有未完成批次。继续原复盘，或确认重建后用 --replace-pending。")
            store = self.load()
            today = iso(today) if today else datetime.now(SHANGHAI).date()
            explicit = start is not None or end is not None
            until = iso(end) if end else today
            since = (iso(start) if start else
                     (iso(store["last_default_end"]) if store["last_default_end"] and not explicit
                      else until - timedelta(days=6)))
            if since > until or until > today:
                raise JournalError("日期范围颠倒或结束日期在未来。")
            overrides = overrides or {}
            for relative, day in overrides.items():
                if not self.diary_path(relative).is_file():
                    raise JournalError("日期覆盖指向不存在的日记。")
                iso(day)
            effective_dates = {**store.get("date_overrides", {}), **overrides}
            entries, unknown, outside, unchanged = [], [], 0, 0
            all_paths = set(self.files())
            for relative in sorted(all_paths):
                day = self.file_date(relative, effective_dates)
                prior = store["processed"].get(relative)
                if day is None and prior:
                    day = prior["date"]  # Previously user-specified date remains known.
                if not day:
                    unknown.append(relative)
                    continue
                in_range = since <= iso(day) <= until
                if not explicit and prior is None and store.get("baseline_start"):
                    in_range = iso(store["baseline_start"]) <= iso(day) <= until
                # Old unprocessed files aren't fully read merely to build a profile.
                if not in_range and (explicit or prior is None):
                    outside += 1
                    continue
                raw = self.diary_path(relative).read_bytes()
                checksum = digest(raw)
                changed = prior is not None and (prior["sha256"] != checksum or prior["date"] != day)
                if not in_range and not changed:
                    outside += 1
                    continue
                if prior and not changed and not explicit:
                    unchanged += 1
                    continue
                try:
                    content = raw.decode("utf-8-sig")
                except UnicodeError as exc:
                    raise JournalError("日记需为 UTF-8，请确认编码：" + relative) from exc
                entries.append({"path": relative, "date": day, "sha256": checksum,
                                "reason": "revised" if changed else ("revisit" if prior else "new"),
                                "content": content})
            missing = sorted(set(store["processed"]) - all_paths)
            memory = self.recall()
            result = {"range": {"start": since.isoformat(), "end": until.isoformat()},
                      "entries": entries, "undated_or_conflicting": unknown,
                      "missing_processed_sources": missing, "outside_range_count": outside,
                      "unchanged_count": unchanged, **memory}
            if replace:
                self.remove("memory/pending.json")
                self.remove("memory/draft.json")
            if entries or memory["stale_record_ids"] or missing:
                pending = {"id": "review-" + uuid.uuid4().hex[:12], "created_at": stamp(),
                           "base_revision": store["revision"], "range": result["range"],
                           "explicit_range": explicit, "unknown": unknown,
                           "date_overrides": overrides,
                           "sources": [{k: e[k] for k in ("path", "date", "sha256")} for e in entries],
                           "missing": missing}
                self.write("memory/pending.json", encoded(pending))
                result["batch_id"] = pending["id"]
            else:
                result["batch_id"] = None
            return result

    def validate_record(self, record):
        if not isinstance(record, dict):
            raise JournalError("记忆条目必须是对象。")
        key, kind = record.get("id", ""), record.get("kind")
        if not isinstance(key, str) or not ID_PATTERN.fullmatch(key):
            raise JournalError("记忆 id 必须为小写字母、数字、连字符。")
        if kind not in STATUSES or record.get("status") not in STATUSES[kind]:
            raise JournalError("无效记忆类别或状态：" + key)
        if not isinstance(record.get("text"), str) or not record["text"].strip():
            raise JournalError("记忆缺少正文：" + key)
        if "current" in record and not isinstance(record["current"], bool):
            raise JournalError("current 必须为布尔值。")
        sources, discussion = record.get("sources", []), record.get("discussion", [])
        if not isinstance(sources, list) or not isinstance(discussion, list):
            raise JournalError("sources 和 discussion 必须是数组。")
        if not sources and not discussion:
            raise JournalError("记忆必须有原文证据或用户明确补充：" + key)
        seen = set()
        for source in sources:
            if not isinstance(source, dict):
                raise JournalError("来源格式无效：" + key)
            self.diary_path(source.get("path", ""))
            iso(source.get("date"))
            if not isinstance(source.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", source["sha256"]):
                raise JournalError("来源散列无效：" + key)
            if record["status"] != "retracted" and not self.evidence_valid(source):
                raise JournalError("来源不存在、越界或版本改变：" + key)
            source_key = (source["path"], source["sha256"])
            if source_key in seen:
                raise JournalError("同一来源不能重复计为证据：" + key)
            seen.add(source_key)
        for statement in discussion:
            if not isinstance(statement, dict):
                raise JournalError("用户补充格式无效。")
            iso(statement.get("date"))
            if not isinstance(statement.get("quote"), str) or not statement["quote"].strip():
                raise JournalError("用户补充需要明确原话。")
        if kind == "action" and record["status"] != "proposed":
            adoption = record.get("adoption", {})
            if not isinstance(adoption, dict) or not isinstance(adoption.get("quote"), str) or not adoption["quote"].strip():
                raise JournalError("跟进行动前必须记录用户采纳依据。")
            iso(adoption.get("date"))
        return copy.deepcopy(record)

    def merge(self, store, records):
        if not isinstance(records, list):
            raise JournalError("records 必须是数组。")
        touched, keys = [], set()
        for value in records:
            record = self.validate_record(value)
            key = record["id"]
            if key in keys or key in store["forgotten_ids"]:
                raise JournalError("记忆 id 重复或已被遗忘：" + key)
            keys.add(key)
            # Exact same claim+evidence under another id must not accumulate as new evidence.
            for old_key, old in store["records"].items():
                if old_key != key and all(old.get(f) == record.get(f) for f in ("kind", "text", "sources", "discussion")):
                    raise JournalError("同一判断已经存在，请更新原 id：" + old_key)
            prior = store["records"].get(key)
            record["updated_at"] = stamp()
            if prior and {k: v for k, v in prior.items() if k != "updated_at"} != {k: v for k, v in record.items() if k != "updated_at"}:
                touched.append(key)
            store["records"][key] = record
        return touched

    def retract_reports(self, store, record_ids=(), source_paths=()):
        affected = []
        for key, report in store["reviews"].items():
            if (set(record_ids) & set(report["record_ids"]) or
                    set(source_paths) & {s["path"] for s in report["sources"]}):
                report["markdown"] = RETRACTED
                report["status"] = "retracted"
                report["record_ids"] = [i for i in report["record_ids"] if i not in record_ids]
                affected.append(key)
        return affected

    def persist(self, store):
        self.validate_exports(store)
        store["revision"] += 1
        self.write("memory/store.json", encoded(store))
        self.remove("memory/draft.json")
        self.remove("memory/pending.json")
        try:
            self.export(store)
        except OSError:
            return "记忆已保存，但报告导出失败；运行 export 修复。"
        return None

    def validate_exports(self, store):
        for key in store["reviews"]:
            if not ID_PATTERN.fullmatch(key):
                raise JournalError("无效报告 id。")
            self.path("reviews/" + key + ".md")

    def export(self, store=None):
        store = self.load() if store is None else store
        self.validate_exports(store)
        for key, report in store["reviews"].items():
            self.write("reviews/" + key + ".md", report["markdown"].encode("utf-8"))
        return {"exported": len(store["reviews"])}

    def finish(self):
        with self.locked():
            store = self.load()
            pending = self.read_json("memory/pending.json")
            draft = self.read_json("memory/draft.json")
            if not isinstance(pending, dict) or not isinstance(draft, dict):
                raise JournalError("缺少待完成批次或 memory/draft.json。")
            if pending["base_revision"] != store["revision"]:
                raise JournalError("记忆已被其他操作更改，请重新收集。")
            if pending["id"] in store["reviews"]:
                raise JournalError("该复盘已完成。")
            if any(not self.evidence_valid(s) for s in pending["sources"]):
                raise JournalError("日记在交流期间改变，请重新收集，不能推进状态。")
            if any(self.path(p).exists() for p in pending["missing"]):
                raise JournalError("缺失来源重新出现，请重新收集。")
            markdown = draft.get("review")
            if not isinstance(markdown, str) or not markdown.strip():
                raise JournalError("完成复盘需要 Markdown 正文。")
            changed_sources = [s["path"] for s in pending["sources"]
                               if s["path"] in store["processed"] and store["processed"][s["path"]] != s]
            touched = self.merge(store, draft.get("records", []))
            stale = self.stale(store)
            expected_dates = {p: s["date"] for p, s in store["processed"].items()}
            expected_dates.update({s["path"]: s["date"] for s in pending["sources"]})
            for record_id, record in store["records"].items():
                if record["status"] != "retracted" and any(
                    source["date"] != expected_dates.get(source["path"], source["date"])
                    for source in record.get("sources", [])
                ):
                    stale.append(record_id)
            if stale:
                raise JournalError("请先修正或撤回失效记忆：" + ", ".join(stale))
            self.retract_reports(store, touched, changed_sources + pending["missing"])
            for source in pending["sources"]:
                store["processed"][source["path"]] = source
            for relative in pending["missing"]:
                store["processed"].pop(relative, None)
                store.get("date_overrides", {}).pop(relative, None)
            store.setdefault("date_overrides", {}).update(pending.get("date_overrides", {}))
            if not pending["explicit_range"] and not pending["unknown"]:
                old = store["last_default_end"]
                store["last_default_end"] = max(old or pending["range"]["end"], pending["range"]["end"])
                if not store.get("baseline_start"):
                    store["baseline_start"] = pending["range"]["start"]
            key = pending["id"]
            store["reviews"][key] = {"created_at": stamp(), "range": pending["range"],
                                      "sources": pending["sources"], "record_ids": list(store["records"]),
                                      "status": "complete", "markdown": markdown}
            warning = self.persist(store)
            return {"saved": "reviews/" + key + ".md", "revision": store["revision"], "warning": warning}

    def amend(self):
        with self.locked():
            store = self.load()
            draft = self.read_json("memory/draft.json")
            if not isinstance(draft, dict) or draft.get("base_revision") != store["revision"]:
                raise JournalError("先 recall，再在草稿中填写对应 base_revision。")
            touched = self.merge(store, draft.get("records", []))
            if self.stale(store):
                raise JournalError("仍有失效记忆需要修正或撤回。")
            affected = self.retract_reports(store, touched)
            warning = self.persist(store)
            return {"revision": store["revision"], "retracted_reviews": affected, "warning": warning}

    def forget(self, key, apply=False):
        with self.locked():
            store = self.load()
            if key not in store["records"]:
                raise JournalError("未找到该记忆 id。")
            affected = [rid for rid, r in store["reviews"].items() if key in r["record_ids"]]
            result = {"record_id": key, "retracted_reviews": affected, "applied": apply,
                      "scope": "删除该记忆和相关旧报告正文，清理草稿；保留原日记及平台会话。"}
            if apply:
                del store["records"][key]
                store["forgotten_ids"].append(key)
                self.retract_reports(store, [key])
                result["warning"] = self.persist(store)
            return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["collect", "recall", "finish", "amend", "forget", "export"])
    parser.add_argument("--session-isolated", action="store_true", help="执行者声明已核实当前会话记忆隔离；不是平台设置开关")
    parser.add_argument("--today")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--date", action="append", default=[], metavar="FILE=YYYY-MM-DD")
    parser.add_argument("--replace-pending", action="store_true")
    parser.add_argument("--id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if not args.session_isolated:
            raise JournalError("未声明当前会话隔离。请先核实会话控制或通过 start-mentor.ps1 启动；不能只为了通过检查而加参数。")
        journal = Journal(Path(__file__).resolve().parents[4])
        if args.command == "collect":
            overrides = {}
            for value in args.date:
                name, sep, day = value.rpartition("=")
                if not sep:
                    raise JournalError("日期覆盖使用 FILE=YYYY-MM-DD。")
                overrides["diary/" + name] = day
            output = journal.collect(args.today, args.start, args.end, overrides, args.replace_pending)
        elif args.command == "forget":
            if not args.id:
                raise JournalError("forget 需要 --id。")
            output = journal.forget(args.id, args.apply)
        elif args.command == "export":
            with journal.locked():
                output = journal.export()
        else:
            output = getattr(journal, args.command)()
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (JournalError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
