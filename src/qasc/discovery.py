"""Read-only development-tool discovery; availability is not a build proof."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


# Keys remain stable for callers. Arguments only request version information.
_SPECS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "python": (("python", "python3"), ("--version",)),
    "anaconda": (("conda",), ("--version",)),
    "powershell": (("pwsh", "powershell"), ("-NoProfile", "-NonInteractive", "-Command", "$PSVersionTable.PSVersion.ToString()")),
    "node": (("node",), ("--version",)),
    "npm": (("npm",), ("--version",)),
    "git": (("git",), ("--version",)),
    "github_cli": (("gh",), ("--version",)),
    "gcc": (("gcc",), ("--version",)),
    "g++": (("g++",), ("--version",)),
    "clang": (("clang",), ("--version",)),
    "clang++": (("clang++",), ("--version",)),
    "msvc": (("cl",), ()),
    "cmake": (("cmake",), ("--version",)),
    "ninja": (("ninja",), ("--version",)),
    "rust": (("rustc",), ("--version",)),
    "cargo": (("cargo",), ("--version",)),
    "dotnet": (("dotnet",), ("--version",)),
    "pyinstaller": (("pyinstaller",), ("--version",)),
    "nuitka": (("nuitka",), ("--version",)),
    "wix": (("wix",), ("--version",)),
    "inno_setup": (("iscc",), ("/?",)),
    "nsis": (("makensis",), ("/VERSION",) if os.name == "nt" else ("-VERSION",)),
    "7zip": (("7z", "7zz"), ("i",)),
    "windows_sdk": (("rc",), ("/?",)),
}


def _known_candidates(name: str) -> list[Path]:
    """Small known install locations supplement PATH without recursive scans."""
    home = Path.home()
    candidates: list[Path] = []
    if name == "anaconda":
        roots = [home / "anaconda3", home / "miniconda3"]
        if os.name == "nt":
            roots += [Path("C:/ProgramData/anaconda3"), Path("C:/ProgramData/miniconda3")]
        if os.environ.get("CONDA_PREFIX"):
            roots.insert(0, Path(os.environ["CONDA_PREFIX"]))
        for root in roots:
            candidates.append(root / ("Scripts/conda.exe" if os.name == "nt" else "bin/conda"))
    if os.name == "nt":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            root = Path(os.environ.get(env, "C:/Program Files"))
            relative = {
                "inno_setup": "Inno Setup 6/ISCC.exe",
                "nsis": "NSIS/makensis.exe",
                "7zip": "7-Zip/7z.exe",
                "powershell": "PowerShell/7/pwsh.exe",
            }.get(name)
            if relative:
                candidates.append(root / relative)
    return candidates


def _probe(name: str, spec: tuple[tuple[str, ...], tuple[str, ...]]) -> tuple[str, dict]:
    commands, args = spec
    path = sys.executable if name == "python" else None
    if not path:
        path = next((found for command in commands if (found := shutil.which(command))), None)
    if not path:
        path = next((str(candidate) for candidate in _known_candidates(name) if candidate.is_file()), None)
    result: dict = {"available": bool(path), "path": path, "version": None, "error": None}
    if path is None:
        result["error"] = "Not found on PATH or in checked standard installation locations"
        return name, result
    try:
        completed = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            stdin=subprocess.DEVNULL,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        result["version"] = lines[0][:500] if lines else None
        result["probe_exit_code"] = completed.returncode
        # cl prints its version then returns 2 when invoked with no input files.
        if completed.returncode and not (name == "msvc" and result["version"]):
            result["error"] = f"Version probe exited with code {completed.returncode}"
    except subprocess.TimeoutExpired:
        result["error"] = "Version probe timed out after 5 seconds"
    except OSError as exc:
        result["error"] = f"Version probe could not execute: {exc}"
    return name, result


def discover_tools() -> dict:
    """Inventory executable locations and bounded version probes, without installs.

    ``available`` means an executable was located. A separate ``error`` records
    a version probe failure. Compilers/SDKs outside PATH may require their vendor
    environment shell and are not guessed to work.
    """
    with ThreadPoolExecutor(max_workers=8) as pool:
        tools = dict(pool.map(lambda item: _probe(*item), _SPECS.items()))
    return {
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "python": {"executable": sys.executable, "version": platform.python_version(), "implementation": platform.python_implementation()},
        "tools": tools,
    }
