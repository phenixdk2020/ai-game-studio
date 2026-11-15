"""Configure, build, and run CTest for a CMake checkout in Debug and Release."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable, Sequence


TIMEOUT_SECONDS = 1200


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def build_directory(source: Path, build_root: Path) -> Path:
    """Return the deterministic, checkout-specific directory under build_root."""
    identity = hashlib.sha256(os.fsencode(str(source.resolve()))).hexdigest()[:16]
    return build_root.resolve() / identity


def validate_project(
    source: Path,
    cmake: Path,
    ctest: Path,
    generator: str,
    build_root: Path,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    if not cmake.is_absolute() or not ctest.is_absolute() or not build_root.is_absolute():
        print("--cmake, --ctest, and --build-root must be absolute paths", file=sys.stderr)
        return 2
    source = source.resolve()
    build_root = build_root.resolve()
    if not (source / "CMakeLists.txt").is_file():
        print(f"Missing CMakeLists.txt in source checkout: {source}", file=sys.stderr)
        return 2
    if _is_within(build_root, source):
        print("Build root must be outside the source checkout", file=sys.stderr)
        return 2
    if _is_within(source, build_root):
        print("Source checkout must be outside the build root", file=sys.stderr)
        return 2

    build = build_directory(source, build_root)
    build.mkdir(parents=True, exist_ok=True)
    commands = [
        [str(cmake), "-S", str(source), "-B", str(build), "-G", generator, "-A", "x64"],
        [str(cmake), "--build", str(build), "--config", "Debug"],
        [str(ctest), "--test-dir", str(build), "-C", "Debug", "--output-on-failure", "--no-tests=error"],
        [str(cmake), "--build", str(build), "--config", "Release"],
        [str(ctest), "--test-dir", str(build), "-C", "Release", "--output-on-failure", "--no-tests=error"],
    ]
    for command in commands:
        print(f"RUN {command!r}", flush=True)
        try:
            result = runner(command, cwd=source, timeout=TIMEOUT_SECONDS, check=False)
        except subprocess.TimeoutExpired:
            print(f"Timed out after {TIMEOUT_SECONDS}s: {command!r}", file=sys.stderr)
            return 124
        except OSError as exc:
            print(f"Could not run {command!r}: {exc}", file=sys.stderr)
            return 127
        if result.returncode:
            print(f"Command failed ({result.returncode}): {command!r}", file=sys.stderr)
            return result.returncode
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cmake", required=True, type=Path, help="Absolute path to cmake executable")
    parser.add_argument("--ctest", required=True, type=Path, help="Absolute path to ctest executable")
    parser.add_argument("--generator", required=True)
    parser.add_argument("--build-root", required=True, type=Path, help="Absolute path outside checkout")
    args = parser.parse_args(argv)
    return validate_project(Path.cwd(), args.cmake, args.ctest, args.generator, args.build_root)


if __name__ == "__main__":
    raise SystemExit(main())
