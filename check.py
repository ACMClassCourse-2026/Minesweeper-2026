#!/usr/bin/env python3
"""Build the basic-task server and check every public .in/.out pair."""

from __future__ import annotations

import difflib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parent
TESTCASE_DIR = ROOT / "testcases"
TIMEOUT_SECONDS = 2
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def find_testcases() -> tuple[list[tuple[Path, Path]], list[Path]]:
    pairs: list[tuple[Path, Path]] = []
    unpaired: list[Path] = []
    for input_path in sorted(TESTCASE_DIR.rglob("*.in")):
        output_path = input_path.with_suffix(".out")
        if output_path.is_file():
            pairs.append((input_path, output_path))
        else:
            unpaired.append(input_path)
    return pairs, unpaired


def find_server(build_dir: Path) -> Path:
    candidates = (
        build_dir / "src" / "server",
        build_dir / "src" / "server.exe",
        build_dir / "src" / "Release" / "server",
        build_dir / "src" / "Release" / "server.exe",
        build_dir / "Release" / "server",
        build_dir / "Release" / "server.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("CMake built the server target, but its executable was not found")


def limit_output_size() -> None:
    if os.name != "posix":
        return
    import resource

    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))


def show_diff(expected: bytes, actual: bytes) -> None:
    expected_lines = expected.decode("utf-8", errors="replace").splitlines(keepends=True)
    actual_lines = actual.decode("utf-8", errors="replace").splitlines(keepends=True)
    diff = difflib.unified_diff(
        expected_lines,
        actual_lines,
        fromfile="expected",
        tofile="actual",
    )
    shown = 0
    for line in diff:
        print(line, end="")
        shown += 1
        if shown == 80:
            print("... diff truncated ...")
            break


def run_test(server: Path, input_path: Path, expected_path: Path, work_dir: Path) -> bool:
    relative_name = input_path.relative_to(ROOT)
    actual_path = work_dir / ("-".join(relative_name.parts) + ".actual")
    with input_path.open("rb") as input_file, actual_path.open("wb") as output_file:
        process = subprocess.Popen(
            [str(server)],
            stdin=input_file,
            stdout=output_file,
            stderr=subprocess.PIPE,
            cwd=ROOT,
            preexec_fn=limit_output_size if os.name == "posix" else None,
        )
        try:
            _, stderr = process.communicate(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate()
            print(f"[FAIL] {relative_name} (time limit exceeded: {TIMEOUT_SECONDS}s)")
            if stderr:
                print(stderr.decode("utf-8", errors="replace"))
            return False

    actual = actual_path.read_bytes()
    expected = expected_path.read_bytes()
    if process.returncode != 0:
        reason = "output limit exceeded" if len(actual) >= MAX_OUTPUT_BYTES else f"exit code {process.returncode}"
        print(f"[FAIL] {relative_name} ({reason})")
        if stderr:
            print(stderr.decode("utf-8", errors="replace"))
        return False
    if actual != expected:
        print(f"[FAIL] {relative_name} (wrong answer)")
        show_diff(expected, actual)
        return False

    print(f"[PASS] {relative_name}")
    return True


def main() -> int:
    if shutil.which("cmake") is None:
        print("error: cmake was not found in PATH", file=sys.stderr)
        return 2

    testcases, unpaired = find_testcases()
    if not testcases:
        print("error: no matching .in/.out testcase pairs were found", file=sys.stderr)
        return 2

    print(f"Found {len(testcases)} public testcase pair(s).")
    if unpaired:
        print(f"Skipping {len(unpaired)} .in file(s) without matching .out files.")

    with tempfile.TemporaryDirectory(prefix="minesweeper-check-") as temporary_dir:
        temporary_path = Path(temporary_dir)
        build_dir = temporary_path / "build"
        configure = subprocess.run(
            ["cmake", "-S", str(ROOT), "-B", str(build_dir), "-DCMAKE_BUILD_TYPE=Release"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if configure.returncode != 0:
            print("[BUILD FAILED] CMake configuration failed")
            print(configure.stdout)
            return 2

        build = subprocess.run(
            ["cmake", "--build", str(build_dir), "--target", "server", "--config", "Release"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if build.returncode != 0:
            print("[BUILD FAILED] server compilation failed")
            print(build.stdout)
            return 2

        try:
            server = find_server(build_dir)
        except FileNotFoundError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

        passed = sum(run_test(server, input_path, output_path, temporary_path) for input_path, output_path in testcases)

    print(f"\nResult: {passed}/{len(testcases)} passed.")
    return 0 if passed == len(testcases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
