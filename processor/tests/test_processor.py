import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pymupdf
from fastapi.testclient import TestClient

from processor import llm
from processor.app import create_app
from processor.documents import read_document
from processor.engine import Engine
from processor.folders import create_folder, list_folders
from processor.store import Store


def make_pdf(path, text="A signed agreement grants oil and gas extraction rights in Belmont County. " * 4):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(35, 35, 550, 700), text)
        doc.save(path)


class ScoringTests(unittest.TestCase):
    def test_threshold_is_strict_and_uncertainty_requires_review(self):
        values = [{"result": "met"}] * 7 + [{"result": "not_met"}] * 3
        self.assertEqual(llm.decision(values, 70), (70.0, "not_selected"))
        values[-1] = {"result": "met"}
        self.assertEqual(llm.decision(values, 70), (80.0, "golden"))
        values[-2] = {"result": "unknown"}
        self.assertEqual(llm.decision(values, 70), (80.0, "needs_review"))

    def test_response_must_include_every_condition_and_valid_pages(self):
        criteria = [{"id": "one"}, {"id": "two"}]
        with self.assertRaises(ValueError):
            llm.parse_result('{"conditions": []}', criteria, 2)
        value = {"conditions": [{"id": c["id"], "result": "met", "explanation": "Found", "evidence": "Lease", "pages": [3]} for c in criteria]}
        with self.assertRaisesRegex(ValueError, "page reference"):
            llm.parse_result(json.dumps(value), criteria, 2)

    def test_unsupported_positive_claim_is_downgraded(self):
        raw = json.dumps({"conditions": [{"id": "one", "result": "met", "explanation": "Yes", "pages": []}]})
        self.assertEqual(llm.parse_result(raw, [{"id": "one"}], 1)["conditions"][0]["result"], "unknown")

    def test_unknown_usage_never_becomes_zero_cost(self):
        config = {"provider": "openai", "input_rate": 2, "output_rate": 8}
        self.assertIsNone(llm.estimated_cost(config, None, 200))
        self.assertAlmostEqual(llm.estimated_cost(config, 1000, 200), .0036)
        self.assertIsNone(llm.estimated_cost({"provider": "claude"}, 100, 100))


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_vision_and_reported_usage(self):
        response = {"status": "completed", "output": [{"content": [{"type": "output_text", "text": "{}"}]}], "usage": {"input_tokens": 100, "output_tokens": 30}}
        with patch("processor.llm.request", AsyncMock(return_value=response)) as request:
            result = await llm.evaluate({"provider": "openai", "model": "test"}, "key", "prompt", [(1, "image/png", "encoded")])
        self.assertEqual(result["input_tokens"], 100)
        self.assertTrue(result["complete"])
        self.assertEqual(request.call_args.args[-1]["input"][0]["content"][-1]["image_url"], "data:image/png;base64,encoded")

    async def test_claude_includes_cache_tokens(self):
        response = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "{}"}], "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 40}}
        with patch("processor.llm.request", AsyncMock(return_value=response)):
            result = await llm.evaluate({"provider": "claude", "model": "test"}, "key", "prompt", [])
        self.assertEqual(result["input_tokens"], 50)

    async def test_gemini_includes_thinking_and_rejects_truncation(self):
        response = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "{}"}]}}],
                    "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20, "thoughtsTokenCount": 30}}
        with patch("processor.llm.request", AsyncMock(return_value=response)):
            result = await llm.evaluate({"provider": "gemini", "model": "test"}, "key", "prompt", [])
        self.assertEqual(result["output_tokens"], 50)
        self.assertFalse(result["complete"])

    async def test_ollama_non_streaming_usage_and_images(self):
        response = {"done": True, "message": {"content": "{}"}, "prompt_eval_count": 50, "eval_count": 20}
        with patch("processor.llm.request", AsyncMock(return_value=response)) as request:
            result = await llm.evaluate({"provider": "ollama", "model": "test"}, "", "prompt", [(2, "image/png", "encoded")])
        self.assertEqual(result["output_tokens"], 20)
        self.assertEqual(request.call_args.args[-1]["messages"][0]["images"], ["encoded"])


class DocumentTests(unittest.TestCase):
    def test_pdf_text_and_image_inputs(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / "lease.pdf"
            make_pdf(pdf)
            text, images, pages = read_document(pdf)
            self.assertIn("Belmont County", text)
            self.assertEqual(pages, 1)
            self.assertEqual(images, [])
            with pymupdf.open(pdf) as doc:
                for suffix in ("png", "jpg"):
                    image = Path(folder) / ("lease." + suffix)
                    doc[0].get_pixmap().save(image)
                    _, images, pages = read_document(image)
                    self.assertEqual(len(images), 1)
                    self.assertEqual(pages, 1)

    def test_pages_are_rejected_instead_of_silently_truncated(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / "long.pdf"
            with pymupdf.open() as doc:
                doc.new_page()
                doc.new_page()
                doc.save(pdf)
            with self.assertRaisesRegex(ValueError, "Split larger"):
                read_document(pdf, max_pages=1)


class FolderTests(unittest.TestCase):
    def test_browser_lists_folders_only_in_name_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "Zulu").mkdir()
            (root / "Alpha folder").mkdir()
            (root / ".hidden").mkdir()
            (root / "not-a-folder.pdf").write_text("not a folder")
            result = list_folders(str(root))
            self.assertEqual([f["name"] for f in result["folders"]], ["Alpha folder", "Zulu"])
            self.assertEqual(result["path"], str(root))
            self.assertEqual(result["parent"], str(root.parent))
            self.assertEqual(result["breadcrumbs"][-1]["path"], str(root))
            self.assertEqual(result["breadcrumbs"][0]["path"], root.anchor)

    def test_empty_folder_is_selectable_and_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(list_folders(str(root))["folders"], [])
            file = root / "document.txt"
            file.write_text("test")
            with self.assertRaisesRegex(ValueError, "rather than a file"):
                list_folders(str(file))
            with self.assertRaisesRegex(ValueError, "absolute"):
                list_folders("relative/path")

    def test_create_folder_preserves_name_and_rejects_invalid_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            created = create_folder(directory, "Golden results")
            self.assertTrue(Path(created["path"]).is_dir())
            with self.assertRaisesRegex(ValueError, "already exists"):
                create_folder(directory, "Golden results")
            for name in ("../escape", ".", "..", "child/folder", "child\\folder", " "):
                with self.assertRaises(ValueError):
                    create_folder(directory, name)


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input"
        self.source.mkdir()
        make_pdf(self.source / "lease.pdf")
        self.store = Store(self.root / "data")
        self.connection = self.store.put("connections", {"name": "Test", "provider": "openai", "model": "test", "tested": True,
                                                       "secret": self.store.seal("key"), "input_rate": 1, "output_rate": 2})
        self.condition = self.store.put("conditions", {"name": "Lease", "criteria": [{"id": "one", "text": "It is a lease"}]})
        self.profile = self.store.put("profiles", {"name": "Test", "state": "draft", "input_folder": str(self.source),
            "output_folder": str(self.root / "output"), "connection_id": self.connection["id"], "condition_ids": [self.condition["id"]], "threshold": 70})
        self.engine = Engine(self.store)

    def answer(self, raw=None):
        return {"raw_response": raw or json.dumps({"summary": "Lease", "conditions": [{"id": "one", "result": "met", "explanation": "Explicit grant", "evidence": "oil and gas extraction rights", "pages": [1]}]}),
                "input_tokens": 100, "output_tokens": 50, "usage": {}, "complete": True}

    async def run_queue(self, answer=None):
        with patch("processor.llm.evaluate", AsyncMock(return_value=answer or self.answer())) as evaluate:
            await self.engine.start(self.profile["id"])
            await self.engine.tasks[self.profile["id"]]
        return evaluate

    async def test_warmup_no_llm_and_repeat_scan_no_duplicates(self):
        (self.source / "ignore.txt").write_text("ignore")
        with patch("processor.llm.evaluate", AsyncMock()) as evaluate:
            await self.engine.warm(self.profile["id"])
            await self.engine.warm(self.profile["id"])
        evaluate.assert_not_awaited()
        self.assertEqual(len(self.engine.files(self.profile["id"])), 1)
        self.assertEqual(len(self.store.list("files")), 1)

    async def test_golden_copy_report_history_and_no_rebilling(self):
        await self.engine.warm(self.profile["id"])
        await self.run_queue()
        file = self.engine.files(self.profile["id"])[0]
        self.assertEqual(file["status"], "golden")
        attempt = self.store.list("attempts")[0]
        self.assertEqual(attempt["input_tokens"], 100)
        self.assertTrue(Path(attempt["copied_to"]).exists())
        self.assertTrue(Path(attempt["report_path"]).exists())
        self.assertTrue((self.source / "lease.pdf").exists())
        self.assertNotIn("secret", attempt["connection"])
        self.assertNotIn("key", attempt["connection"].values())
        await self.engine.warm(self.profile["id"])
        with self.assertRaisesRegex(ValueError, "No pending"):
            await self.engine.start(self.profile["id"])

    async def test_invalid_response_retains_usage_and_cost(self):
        await self.engine.warm(self.profile["id"])
        await self.run_queue(self.answer("invalid JSON"))
        attempt = self.store.list("attempts")[0]
        self.assertEqual(attempt["status"], "error")
        self.assertEqual(attempt["input_tokens"], 100)
        self.assertAlmostEqual(attempt["cost"], .0002)

    async def test_pause_finishes_current_file_and_resume_processes_rest(self):
        make_pdf(self.source / "second.pdf")
        await self.engine.warm(self.profile["id"])
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow(*args):
            entered.set()
            await release.wait()
            return self.answer()

        with patch("processor.llm.evaluate", side_effect=slow) as evaluate:
            await self.engine.start(self.profile["id"])
            await entered.wait()
            self.engine.pause(self.profile["id"])
            with self.assertRaisesRegex(ValueError, "wait"):
                self.engine.require_idle(self.profile["id"])
            release.set()
            await self.engine.tasks[self.profile["id"]]
            self.assertEqual(self.store.get("profiles", self.profile["id"])["state"], "paused")
            self.assertEqual(sum(f["status"] == "pending" for f in self.engine.files(self.profile["id"])), 1)
            await self.engine.start(self.profile["id"])
            await self.engine.tasks[self.profile["id"]]
        self.assertEqual(evaluate.await_count, 2)
        self.assertTrue(all(f["status"] == "golden" for f in self.engine.files(self.profile["id"])))

    async def test_source_changes_are_not_sent_or_copied(self):
        await self.engine.warm(self.profile["id"])
        (self.source / "lease.pdf").write_bytes(b"changed")
        evaluate = await self.run_queue()
        evaluate.assert_not_awaited()
        self.assertEqual(self.engine.files(self.profile["id"])[0]["status"], "error")

    async def test_restart_requires_manual_retry_of_uncertain_request(self):
        await self.engine.warm(self.profile["id"])
        file = self.engine.files(self.profile["id"])[0]
        self.store.put("files", {**file, "status": "processing"})
        Engine(self.store)
        self.assertEqual(self.engine.files(self.profile["id"])[0]["status"], "interrupted")

    async def test_export_retry_never_calls_llm(self):
        await self.engine.warm(self.profile["id"])
        with patch.object(self.engine, "export", side_effect=OSError("disk full")):
            await self.run_queue()
        file = self.engine.files(self.profile["id"])[0]
        self.assertEqual(file["status"], "export_error")
        with patch("processor.llm.evaluate", AsyncMock()) as evaluate:
            self.engine.export(file, self.store.list("attempts")[0])
        evaluate.assert_not_awaited()
        self.assertEqual(self.engine.files(self.profile["id"])[0]["status"], "golden")

    async def completed_file(self):
        await self.engine.warm(self.profile["id"])
        file = self.engine.files(self.profile["id"])[0]
        attempt = self.store.put("attempts", {"file_id": file["id"], "profile_id": self.profile["id"],
            "status": "not_selected", "connection": self.store.public(self.connection),
            "criteria": self.engine.criteria(self.profile), "threshold": 70,
            "input_tokens": 120, "output_tokens": 45, "cost": .00021})
        file = self.store.put("files", {**file, "status": "not_selected", "last_attempt_id": attempt["id"]})
        return file, attempt

    async def test_rerun_queues_present_files_without_erasing_history(self):
        file, attempt = await self.completed_file()
        missing = self.store.put("files", {**file, "id": "removed-file", "present": False})
        await self.engine.start(self.profile["id"], rerun=True)
        try:
            queued = self.store.get("files", file["id"])
            self.assertEqual(queued["status"], "pending")
            self.assertEqual(queued["last_attempt_id"], attempt["id"])
            self.assertEqual(self.store.get("attempts", attempt["id"]), attempt)
            self.assertEqual(self.store.get("files", missing["id"])["status"], "not_selected")
        finally:
            # Pause before the worker dispatches: this test makes no model request.
            self.engine.pause(self.profile["id"])
            await self.engine.tasks[self.profile["id"]]

    async def test_rerun_dispatches_current_settings_and_keeps_original_snapshot(self):
        file, attempt = await self.completed_file()
        self.store.put("connections", {**self.connection, "model": "updated-model"})
        self.store.put("conditions", {**self.condition, "criteria": [{"id": "new", "text": "It reserves oil rights"}]})
        profile = self.store.get("profiles", self.profile["id"])
        self.store.put("profiles", {**profile, "threshold": 60})
        # Inspect dispatch only; no document evaluation or simulated LLM response.
        with patch.object(self.engine, "process", new_callable=AsyncMock) as process:
            await self.engine.start(self.profile["id"], rerun=True)
            await self.engine.tasks[self.profile["id"]]
        dispatched_file, connection, criteria, threshold = process.call_args.args
        self.assertEqual(dispatched_file["id"], file["id"])
        self.assertEqual(connection["model"], "updated-model")
        self.assertEqual(criteria[0]["text"], "It reserves oil rights")
        self.assertEqual(threshold, 60)
        self.assertEqual(self.store.get("attempts", attempt["id"]), attempt)

    async def test_invalid_rerun_configuration_does_not_reset_results(self):
        file, attempt = await self.completed_file()
        self.store.put("connections", {**self.connection, "tested": False})
        with self.assertRaisesRegex(ValueError, "Test the LLM"):
            await self.engine.start(self.profile["id"], rerun=True)
        self.assertEqual(self.store.get("files", file["id"]), file)
        self.store.put("connections", self.connection)
        self.store.put("conditions", {**self.condition, "criteria": []})
        with self.assertRaisesRegex(ValueError, "at least one condition"):
            await self.engine.start(self.profile["id"], rerun=True)
        self.assertEqual(self.store.get("files", file["id"]), file)
        self.assertEqual(self.store.get("attempts", attempt["id"]), attempt)

    async def test_active_profile_cannot_be_rerun(self):
        file, attempt = await self.completed_file()
        task = asyncio.create_task(asyncio.Event().wait())
        self.engine.tasks[self.profile["id"]] = task
        try:
            with self.assertRaisesRegex(ValueError, "Pause the profile"):
                await self.engine.start(self.profile["id"], rerun=True)
            self.assertEqual(self.store.get("files", file["id"]), file)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(self.root / "data"))

    def login(self):
        self.assertEqual(self.client.post("/api/login", json={"username": "admin", "password": "admin"}).status_code, 200)

    def test_auth_and_cross_origin_rejection(self):
        self.assertEqual(self.client.get("/api/state").status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"username": "admin", "password": "wrong"}).status_code, 401)
        self.login()
        self.assertEqual(self.client.get("/api/state").status_code, 200)
        self.assertEqual(self.client.post("/api/logout", headers={"Origin": "https://elsewhere.test"}).status_code, 403)
        self.client.post("/api/logout")
        self.assertEqual(self.client.get("/api/state").status_code, 401)

    def test_folder_browser_requires_auth_and_creates_output_folder(self):
        source = self.root / "input"
        source.mkdir()
        (source / "Child folder").mkdir()
        self.assertEqual(self.client.get("/api/folders").status_code, 401)
        self.assertEqual(self.client.post("/api/folders", json={"parent": str(source), "name": "Output"}).status_code, 401)
        self.login()
        response = self.client.get("/api/folders", params={"path": str(source)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["folders"][0]["name"], "Child folder")
        response = self.client.post("/api/folders", json={"parent": str(source), "name": "Output"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(Path(response.json()["path"]).is_dir())
        self.assertEqual(self.client.post("/api/folders", json={"parent": str(source), "name": "../escape"}).status_code, 400)

    def test_api_keys_are_encrypted_redacted_and_preserved_on_edit(self):
        self.login()
        value = {"name": "Review", "provider": "openai", "model": "test", "api_key": "VERY-SECRET-TOKEN"}
        response = self.client.post("/api/connections", json=value)
        self.assertEqual(response.status_code, 200, response.text)
        identity = response.json()["id"]
        self.assertNotIn("VERY-SECRET-TOKEN", self.client.get("/api/state").text)
        store = self.client.app.state.store
        self.assertNotIn("VERY-SECRET-TOKEN", json.dumps(store.get("connections", identity)))
        with patch("processor.llm.test_connection", AsyncMock()):
            self.assertEqual(self.client.post(f"/api/connections/{identity}/test").status_code, 200)
        response = self.client.put(f"/api/connections/{identity}", json={**value, "api_key": ""})
        self.assertFalse(response.json()["tested"])
        self.assertEqual(store.secret(store.get("connections", identity)), "VERY-SECRET-TOKEN")

    def test_folder_validation_and_start_before_warmup(self):
        self.login()
        c = self.client.post("/api/connections", json={"name": "Local", "provider": "ollama", "model": "test"}).json()
        condition = self.client.post("/api/conditions", json={"name": "Lease", "conditions": ["It is a lease"]}).json()
        source = self.root / "input"
        source.mkdir()
        body = {"name": "Review", "connection_id": c["id"], "condition_ids": [condition["id"]], "input_folder": str(source), "output_folder": str(source / "nested"), "threshold": 70}
        self.assertEqual(self.client.post("/api/profiles", json=body).status_code, 400)
        response = self.client.post("/api/profiles", json={**body, "output_folder": str(self.root / "output")})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post(f"/api/profiles/{response.json()['id']}/start").status_code, 400)


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = create_app(self.root / "data")
        self.store = self.app.state.store
        self.addCleanup(self.store.db.close)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.client.post("/api/login", json={"username": "admin", "password": "admin"})
        self.connection = self.client.post("/api/connections", json={"name": "Local", "provider": "ollama", "model": "test"}).json()
        self.condition = self.client.post("/api/conditions", json={"name": "Rights", "conditions": ["The document mentions oil rights"]}).json()
        self.source = self.root / "input"
        self.source.mkdir()
        self.profile_body = {"name": "Review", "input_folder": str(self.source), "output_folder": str(self.root / "output"),
                             "connection_id": self.connection["id"], "condition_ids": [self.condition["id"]], "threshold": 70}
        self.profile = self.client.post("/api/profiles", json=self.profile_body).json()

    def test_referenced_connections_and_conditions_cannot_be_deleted(self):
        for kind, value in (("connections", self.connection), ("conditions", self.condition)):
            response = self.client.delete(f"/api/{kind}/{value['id']}")
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn("Review", response.json()["detail"])
            self.assertEqual(self.store.get(kind, value["id"])["id"], value["id"])

    def test_profile_deletion_is_scoped_and_preserves_disk_files(self):
        other = self.client.post("/api/profiles", json={**self.profile_body, "name": "Other profile"}).json()
        original = self.source / "original.pdf"
        original.write_bytes(b"original must survive")
        golden = self.root / "output" / "golden.pdf"
        golden.write_bytes(b"golden must survive")
        report = self.root / "output" / "report.json"
        report.write_text('{"keep":true}')
        for present in (True, False):
            self.store.put("files", {"profile_id": self.profile["id"], "present": present})
        self.store.put("attempts", {"profile_id": self.profile["id"], "status": "golden"})
        unrelated = self.store.put("files", {"profile_id": other["id"], "present": True})
        unrelated_attempt = self.store.put("attempts", {"profile_id": other["id"], "status": "error"})
        response = self.client.delete(f"/api/profiles/{self.profile['id']}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deleted_files"], 2)
        self.assertEqual(response.json()["deleted_attempts"], 1)
        with self.assertRaises(KeyError):
            self.store.get("profiles", self.profile["id"])
        self.assertEqual(self.store.list("files"), [unrelated])
        self.assertEqual(self.store.list("attempts"), [unrelated_attempt])
        self.assertEqual(self.store.get("profiles", other["id"])["name"], "Other profile")
        self.assertTrue(original.exists() and golden.exists() and report.exists())
        self.assertEqual(self.store.get("connections", self.connection["id"])["id"], self.connection["id"])
        self.assertEqual(self.store.get("conditions", self.condition["id"])["id"], self.condition["id"])

    def test_unreferenced_configuration_deletion_keeps_historical_snapshots(self):
        spare = self.store.put("connections", {"name": "Old model", "provider": "ollama", "model": "old", "secret": self.store.seal("test-secret")})
        old_condition = self.store.put("conditions", {"name": "Old conditions", "criteria": [{"id": "old", "text": "Old criterion"}]})
        attempt = self.store.put("attempts", {"profile_id": self.profile["id"], "connection": self.store.public(spare),
                                              "criteria": old_condition["criteria"]})
        for kind, identity in (("connections", spare["id"]), ("conditions", old_condition["id"])):
            response = self.client.delete(f"/api/{kind}/{identity}")
            self.assertEqual(response.status_code, 200, response.text)
            with self.assertRaises(KeyError):
                self.store.get(kind, identity)
        self.assertEqual(self.store.get("attempts", attempt["id"]), attempt)

    def test_active_profiles_cannot_be_deleted(self):
        for state in ("running", "warming", "pausing"):
            self.store.put("profiles", {**self.profile, "state": state})
            response = self.client.delete(f"/api/profiles/{self.profile['id']}")
            self.assertEqual(response.status_code, 409, response.text)
            self.assertEqual(self.store.get("profiles", self.profile["id"])["state"], state)
        self.store.put("profiles", self.profile)
        self.app.state.engine.tasks[self.profile["id"]] = SimpleNamespace(done=lambda: False)
        self.assertEqual(self.client.delete(f"/api/profiles/{self.profile['id']}").status_code, 409)

    def test_profile_deletion_rolls_back_all_records_on_storage_failure(self):
        file = self.store.put("files", {"profile_id": self.profile["id"]})
        attempt = self.store.put("attempts", {"profile_id": self.profile["id"]})
        self.store.db.execute("CREATE TRIGGER reject_test_delete BEFORE DELETE ON entities WHEN OLD.kind='files' BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
        self.store.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            self.app.state.engine.delete_profile(self.profile["id"])
        self.assertEqual(self.store.get("profiles", self.profile["id"]), self.profile)
        self.assertEqual(self.store.get("files", file["id"]), file)
        self.assertEqual(self.store.get("attempts", attempt["id"]), attempt)

    def test_delete_requires_auth_and_rejects_missing_records(self):
        for kind in ("connections", "conditions", "profiles"):
            self.assertEqual(self.client.delete(f"/api/{kind}/missing").status_code, 404)
        self.client.post("/api/logout")
        self.assertEqual(self.client.delete(f"/api/profiles/{self.profile['id']}").status_code, 401)


if __name__ == "__main__":
    unittest.main()
