import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core"))
import runtime
import studio


class StudioTests(unittest.TestCase):
    def test_studio_config_parses_and_has_required_sections(self):
        config = json.loads((ROOT / "config" / "studio.json").read_text(encoding="utf-8"))

        self.assertEqual(config["project"], "AI Game Studio 1864")
        self.assertIn("light", config["llm"]["models"])
        self.assertIn("heavy", config["llm"]["models"])
        self.assertTrue(config["paths"]["blender"].endswith("blender.exe"))

    def test_model_routing_selects_configured_light_and_heavy_models(self):
        self.assertEqual(runtime.route("historical_research"), ("light", runtime.cfg()["llm"]["models"]["light"]))
        self.assertEqual(runtime.route("gameplay"), ("heavy", runtime.cfg()["llm"]["models"]["heavy"]))
        self.assertEqual(runtime.route("unlisted_role"), ("light", runtime.cfg()["llm"]["models"]["light"]))

    def test_task_dependencies_only_release_queued_tasks_after_success(self):
        rows = [
            {"id": "research", "status": "done"},
            {"id": "model", "status": "queued", "dependencies": ["research"]},
            {"id": "rig", "status": "queued", "dependencies": ["model"]},
            {"id": "blocked", "status": "queued", "dependencies": ["missing"]},
            {"id": "failed-parent", "status": "failed"},
            {"id": "failed-child", "status": "queued", "dependencies": ["failed-parent"]},
            {"id": "independent", "status": "queued"},
        ]

        self.assertEqual([task["id"] for task in studio.ready_tasks(rows)], ["model", "independent"])

    def test_queue_loads_utf8_json(self):
        queue = [{"title": "Éclairage", "description": "café"}]
        with TemporaryDirectory() as temp_dir:
            queue_path = Path(temp_dir) / "queue.json"
            queue_path.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")

            self.assertEqual(studio.load_queue(queue_path), queue)

    def test_queue_loads_utf8_bom_json(self):
        queue = [{"title": "Éclairage", "description": "café"}]
        with TemporaryDirectory() as temp_dir:
            queue_path = Path(temp_dir) / "queue.json"
            queue_path.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8-sig")

            self.assertEqual(studio.load_queue(queue_path), queue)

    def test_runtime_state_directories_are_ignored_and_untracked(self):
        protected = ("tasks", "results", "logs", "state")
        ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        ignored_entries = {line.strip().rstrip("/") for line in ignore_text.splitlines()}

        for directory in protected:
            with self.subTest(directory=directory):
                self.assertIn(directory, ignored_entries)

        tracked = subprocess.run(
            ["git", "ls-files", "--", *protected],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout.splitlines()
        self.assertEqual(tracked, [])


if __name__ == "__main__":
    unittest.main()
