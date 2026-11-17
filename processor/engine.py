"""Persisted file queue with a single worker per profile and bounded concurrency."""
import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from . import llm
from .documents import digest, read_document
from .store import now, uid

SUPPORTED = {".pdf", ".jpg", ".jpeg", ".png"}


class Engine:
    def __init__(self, store):
        self.store = store
        self.tasks = {}
        self.slots = asyncio.Semaphore(2)
        for profile in store.list("profiles"):
            if profile["state"] in {"running", "pausing", "warming"}:
                store.put("profiles", {**profile, "state": "paused", "notice": "Application restarted. Review interrupted files before retrying."})
        for file in store.list("files"):
            if file["status"] == "processing":
                store.put("files", {**file, "status": "interrupted", "error": "Interrupted request: usage and billing may be unknown. Retry manually."})
        for attempt in store.list("attempts"):
            if attempt["status"] == "processing":
                store.put("attempts", {**attempt, "status": "interrupted", "error": "Application stopped during processing; billing may be unknown."})

    def busy(self, identity):
        task = self.tasks.get(identity)
        return bool(task and not task.done())

    def require_idle(self, identity):
        if self.busy(identity):
            raise ValueError("Pause the profile and wait for the current file to finish before editing or scanning.")

    def files(self, identity):
        return [f for f in self.store.list("files") if f["profile_id"] == identity and f.get("present", True)]

    def criteria(self, profile):
        result = []
        for identity in profile["condition_ids"]:
            group = self.store.get("conditions", identity)
            result.extend({**c, "group": group["name"]} for c in group["criteria"])
        return result

    def delete_profile(self, identity):
        profile = self.store.get("profiles", identity)
        self.require_idle(identity)
        if profile["state"] in {"running", "warming", "pausing"}:
            raise ValueError("Pause the profile and wait for it to finish before deleting it.")
        files = [f for f in self.store.list("files") if f["profile_id"] == identity]
        attempts = [a for a in self.store.list("attempts") if a["profile_id"] == identity]
        self.store.delete_many([("profiles", identity)] + [("files", f["id"]) for f in files]
                               + [("attempts", a["id"]) for a in attempts])
        self.tasks.pop(identity, None)
        return {"ok": True, "deleted_files": len(files), "deleted_attempts": len(attempts)}

    async def warm(self, identity):
        self.require_idle(identity)
        profile = self.store.get("profiles", identity)
        previous_state = profile["state"]
        self.store.put("profiles", {**profile, "state": "warming", "notice": ""})
        # Track warming as a task too, so concurrent requests cannot start or edit it.
        self.tasks[identity] = asyncio.current_task()
        try:
            inventory = await asyncio.to_thread(self.inventory, profile)
            existing = {(f["relative_path"], f["sha256"]): f for f in self.store.list("files") if f["profile_id"] == identity}
            for file in existing.values():
                self.store.put("files", {**file, "present": False})
            for item in inventory:
                old = existing.get((item["relative_path"], item["sha256"]))
                self.store.put("files", {**(old or {"status": "pending", "profile_id": identity}), **item, "present": True})
            self.store.put("profiles", {**profile, "state": "ready", "warmed_at": now(), "notice": f"Found {len(inventory)} supported files."})
        except Exception:
            self.store.put("profiles", {**profile, "state": previous_state, "notice": "Warm up failed; previous inventory retained."})
            raise
        finally:
            self.tasks.pop(identity, None)

    @staticmethod
    def inventory(profile):
        root = Path(profile["input_folder"])
        if not root.is_dir():
            raise ValueError("Input folder no longer exists or cannot be read.")
        values = []
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=lambda e: (_ for _ in ()).throw(e)):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and not (Path(directory) / d).is_symlink())
            for name in sorted(files):
                path = Path(directory) / name
                if path.suffix.lower() not in SUPPORTED or path.is_symlink() or name.startswith("."):
                    continue
                stat = path.stat()
                sha = digest(path)
                after = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError(f"{name} changed during warm up. Wait for downloads to finish and try again.")
                values.append({"name": name, "relative_path": str(path.relative_to(root)), "path": str(path),
                               "size": stat.st_size, "sha256": sha})
        return values

    async def start(self, identity, rerun=False):
        self.require_idle(identity)
        profile = self.store.get("profiles", identity)
        if not profile.get("warmed_at"):
            raise ValueError("Warm up the profile before starting.")
        connection = self.store.get("connections", profile["connection_id"])
        if not connection.get("tested"):
            raise ValueError("Test the LLM connection in Settings before starting.")
        files = self.files(identity)
        if not files:
            raise ValueError("No files in this profile. Warm up to discover supported files.")
        if not rerun and not any(f["status"] == "pending" for f in files):
            raise ValueError("No pending files. Use Rerun to evaluate the current files again, or warm up to discover new files.")
        criteria = self.criteria(profile)
        if not criteria:
            raise ValueError("Add at least one condition.")
        if rerun:
            # Validate settings before resetting the queue. Prior attempts remain
            # available through last_attempt_id until a new attempt is started.
            for file in files:
                self.store.put("files", {**file, "status": "pending", "error": None})
        self.store.put("profiles", {**profile, "state": "running", "notice": ""})
        self.tasks[identity] = asyncio.create_task(self.run(identity, connection, criteria, profile["threshold"]))

    def pause(self, identity):
        profile = self.store.get("profiles", identity)
        if profile["state"] != "running":
            raise ValueError("This profile is not running.")
        self.store.put("profiles", {**profile, "state": "pausing", "notice": "Finishing the current request before pausing."})

    async def run(self, identity, connection, criteria, threshold):
        interrupted = False
        try:
            for file in self.files(identity):
                if file["status"] != "pending":
                    continue
                async with self.slots:
                    if self.store.get("profiles", identity)["state"] != "running":
                        break
                    await self.process(file, connection, criteria, threshold)
        except asyncio.CancelledError:
            interrupted = True
            raise
        finally:
            profile = self.store.get("profiles", identity)
            paused = interrupted or profile["state"] == "pausing"
            self.store.put("profiles", {**profile, "state": "paused" if paused else "completed",
                                        "notice": "Paused. Review interrupted files before retrying." if paused else "Processing finished. Open a file to review its report."})

    async def process(self, file, connection, criteria, threshold):
        started = time.monotonic()
        attempt = self.store.put("attempts", {"file_id": file["id"], "profile_id": file["profile_id"],
            "status": "processing", "connection": self.store.public(connection), "criteria": criteria,
            "threshold": threshold, "input_tokens": None, "output_tokens": None, "cost": None,
            "started_at": now(), "error": None})
        self.store.put("files", {**file, "status": "processing", "error": None, "last_attempt_id": attempt["id"]})
        try:
            if Path(file["path"]).is_symlink() or await asyncio.to_thread(digest, file["path"]) != file["sha256"]:
                raise ValueError("File changed since warm up. Run warm up again before processing.")
            text, images, pages = await asyncio.to_thread(read_document, file["path"])
            attempt.update({"pages": pages, "image_pages": len(images)})
            response = await llm.evaluate(connection, self.store.secret(connection), llm.prompt_for(criteria, text), images)
            attempt.update(response)
            attempt["cost"] = llm.estimated_cost(connection, response["input_tokens"], response["output_tokens"])
            # Persist usage before parsing, so invalid or truncated answers retain their billable usage.
            self.store.put("attempts", attempt)
            if not response["complete"]:
                raise ValueError("LLM response was incomplete or blocked. Review the saved response before retrying.")
            result = llm.parse_result(response["raw_response"], criteria, pages)
            score, status = llm.decision(result["conditions"], threshold)
            attempt.update({"result": result, "score": score, "status": status})
        except asyncio.CancelledError:
            attempt.update({"status": "interrupted", "error": "Application stopped. Request billing may be unknown; retry manually."})
            raise
        except Exception as error:
            attempt.update({"status": "error", "error": str(error) if isinstance(error, (ValueError, OSError, json.JSONDecodeError)) else "Processing failed. Check document format and provider configuration."})
        finally:
            attempt["duration"] = round(time.monotonic() - started, 2)
            attempt["finished_at"] = now()
            attempt = self.store.put("attempts", attempt)
            file = self.store.put("files", {**file, "status": attempt["status"], "last_attempt_id": attempt["id"], "error": attempt.get("error")})
            try:
                await asyncio.to_thread(self.export, file, attempt)
            except Exception as error:
                self.store.put("files", {**file, "status": "export_error", "error": f"Report or copy failed: {error}. Retry export without another LLM request."})

    def export(self, file, attempt):
        profile = self.store.get("profiles", file["profile_id"])
        root = Path(profile["output_folder"])
        reports = root / "reports" / file["id"]
        reports.mkdir(parents=True, exist_ok=True)
        if attempt["status"] == "golden":
            source = Path(file["path"])
            if source.is_symlink() or digest(source) != file["sha256"]:
                raise ValueError("Source changed after evaluation; refusing to copy a different file")
            target = root / "golden" / f"{source.stem}.{file['sha256'][:12]}{source.suffix}"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if digest(target) != file["sha256"]:
                    raise ValueError("Output collision: existing file has different contents")
            else:
                # Exclusive create prevents overwriting an existing output.
                created = False
                try:
                    with open(target, "xb") as dst:
                        created = True
                        with open(source, "rb") as src:
                            shutil.copyfileobj(src, dst)
                    if digest(target) != file["sha256"]:
                        raise ValueError("Source changed while copying")
                except Exception:
                    if created and target.exists():
                        target.unlink()
                    raise
            attempt["copied_to"] = str(target)
        report = reports / f"{attempt['id']}.json"
        report.write_text(json.dumps({"file": {k: v for k, v in file.items() if k != "error"}, "attempt": attempt}, indent=2), encoding="utf-8")
        attempt["report_path"] = str(report)
        self.store.put("attempts", attempt)
        self.store.put("files", {**file, "status": attempt["status"], "error": attempt.get("error")})

    async def close(self):
        tasks = [t for t in self.tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
