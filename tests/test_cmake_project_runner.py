import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_cmake_project", ROOT / "tools" / "validate_cmake_project.py"
)
validate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate)


class CMakeProjectRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "checkout"
        self.source.mkdir()
        (self.source / "CMakeLists.txt").write_text("project(fake)\n", encoding="utf-8")
        self.build_root = self.root / "builds"
        self.cmake = Path("C:/tools/cmake.exe")
        self.ctest = Path("C:/tools/ctest.exe")

    def tearDown(self):
        self.temp.cleanup()

    def run_validation(self, runner):
        return validate.validate_project(
            self.source, self.cmake, self.ctest, "Visual Studio 17 2022", self.build_root, runner
        )

    def test_commands_are_exact_and_build_outside_checkout(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0))
        self.assertEqual(self.run_validation(runner), 0)
        build = validate.build_directory(self.source, self.build_root)
        self.assertFalse(validate._is_within(build, self.source))
        self.assertEqual(runner.call_count, 5)
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(commands, [
            [str(self.cmake), "-S", str(self.source.resolve()), "-B", str(build), "-G", "Visual Studio 17 2022", "-A", "x64"],
            [str(self.cmake), "--build", str(build), "--config", "Debug"],
            [str(self.ctest), "--test-dir", str(build), "-C", "Debug", "--output-on-failure", "--no-tests=error"],
            [str(self.cmake), "--build", str(build), "--config", "Release"],
            [str(self.ctest), "--test-dir", str(build), "-C", "Release", "--output-on-failure", "--no-tests=error"],
        ])
        for call in runner.call_args_list:
            self.assertEqual(call.kwargs["cwd"], self.source.resolve())
            self.assertEqual(call.kwargs["timeout"], 1200)
            self.assertFalse(call.kwargs["check"])

    def test_first_command_failure_stops_pipeline(self):
        runner = Mock(side_effect=[
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 7),
            subprocess.CompletedProcess([], 0),
        ])
        self.assertEqual(self.run_validation(runner), 7)
        self.assertEqual(runner.call_count, 2)

    def test_relative_build_root_is_rejected_before_resolve(self):
        runner = Mock()
        result = validate.validate_project(
            self.source, self.cmake, self.ctest, "Ninja", Path("relative-build"), runner
        )
        self.assertEqual(result, 2)
        self.assertEqual(runner.call_count, 0)
        self.assertFalse((self.root / "relative-build").exists())

    def test_timeout_stops_pipeline_with_nonzero_status(self):
        runner = Mock(side_effect=subprocess.TimeoutExpired([str(self.cmake)], 1200))
        self.assertEqual(self.run_validation(runner), 124)
        self.assertEqual(runner.call_count, 1)

    def test_oserror_stops_pipeline_with_nonzero_status(self):
        runner = Mock(side_effect=OSError("not executable"))
        self.assertEqual(self.run_validation(runner), 127)
        self.assertEqual(runner.call_count, 1)

    def test_ctest_failure_stops_before_release_commands(self):
        runner = Mock(side_effect=[
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 0),
            subprocess.CompletedProcess([], 9),
        ])
        self.assertEqual(self.run_validation(runner), 9)
        self.assertEqual(runner.call_count, 3)
        self.assertEqual(runner.call_args_list[-1].args[0][0], str(self.ctest))

    def test_build_directory_differs_for_different_checkouts(self):
        other = self.root / "other-checkout"
        other.mkdir()
        self.assertNotEqual(
            validate.build_directory(self.source, self.build_root),
            validate.build_directory(other, self.build_root),
        )

    def test_rejects_build_root_inside_source_and_source_inside_build_root(self):
        runner = Mock()
        nested_build = self.source / "build"
        self.assertNotEqual(validate.validate_project(self.source, self.cmake, self.ctest, "Ninja", nested_build, runner), 0)
        self.assertEqual(runner.call_count, 0)
        parent_build = self.root / "parent"
        nested_source = parent_build / "checkout"
        nested_source.mkdir(parents=True)
        (nested_source / "CMakeLists.txt").write_text("project(fake)\n", encoding="utf-8")
        self.assertNotEqual(validate.validate_project(nested_source, self.cmake, self.ctest, "Ninja", parent_build, runner), 0)
        self.assertEqual(runner.call_count, 0)

    def test_missing_cmake_lists_fails_without_running_commands(self):
        (self.source / "CMakeLists.txt").unlink()
        runner = Mock()
        self.assertNotEqual(self.run_validation(runner), 0)
        self.assertEqual(runner.call_count, 0)


if __name__ == "__main__":
    unittest.main()
