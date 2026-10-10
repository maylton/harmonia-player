"""A JavaScript engine to run YouTube's player code, whatever the platform has.

In order: JavaScriptCore through GObject introspection (it comes with
WebKitGTK, which the GTK frontend already needs on Linux), the QuickJS
shipped with the Windows build, then QuickJS, Node.js, Deno or Bun on PATH.
Toolkit-free: the KDE frontend uses the same engines.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Protocol

LOGGER = logging.getLogger(__name__)
TIMEOUT_S = 90
# Executables on PATH, and the arguments that run a script file with them.
_PROCESS_RUNTIMES = (
    ("qjs", ("--script",)),
    ("node", ()),
    ("deno", ("run",)),
    ("bun", ()),
)


class JsRuntimeError(RuntimeError):
    """The script failed, or no engine is available."""


class JsRuntime(Protocol):
    name: str

    def run(self, body: str, result: str) -> str:
        """Run *body*, then return the string the expression *result* evaluates to."""


class JavaScriptCoreRuntime:
    """In-process JavaScriptCore (GObject introspection)."""

    name = "JavaScriptCore"

    def __init__(self, module) -> None:
        self._jsc = module

    def run(self, body: str, result: str) -> str:
        # A context per run: they are cheap, and the caller's worker thread owns it.
        context = self._jsc.Context.new()
        value = context.evaluate(f"{body}\n;{result}", -1)
        exception = context.get_exception()
        if exception is not None:
            raise JsRuntimeError(f"JavaScriptCore: {exception.get_message()}")
        return value.to_string()


class ProcessRuntime:
    """An engine run as a process on a temporary script, which prints the result."""

    def __init__(self, name: str, path: str, arguments: tuple[str, ...] = ()) -> None:
        self.name = name
        self.path = path
        self.arguments = arguments

    def run(self, body: str, result: str) -> str:
        # QuickJS cannot read a script from stdin: a file, removed afterwards.
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8", newline="\n"
        ) as handle:
            handle.write(f"{body}\n;console.log({result});\n")
        try:
            done = subprocess.run(
                [self.path, *self.arguments, handle.name],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=TIMEOUT_S,
                # No console window flashes over the user's desktop on Windows.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise JsRuntimeError(f"{self.name}: {exc}") from exc
        finally:
            Path(handle.name).unlink(missing_ok=True)
        if done.returncode:
            raise JsRuntimeError(f"{self.name} ({done.returncode}): {done.stderr.strip()[:300]}")
        return done.stdout.strip()


def _javascriptcore() -> JavaScriptCoreRuntime | None:
    try:
        import gi

        for version in ("6.0", "4.1", "4.0"):
            try:
                gi.require_version("JavaScriptCore", version)
                break
            except ValueError:
                continue
        else:
            return None
        from gi.repository import JavaScriptCore
    except (ImportError, ValueError):
        return None
    return JavaScriptCoreRuntime(JavaScriptCore)


def _bundled_quickjs() -> ProcessRuntime | None:
    """The qjs the Windows build ships next to the application."""
    for folder in (getattr(sys, "_MEIPASS", None), Path(sys.executable).parent):
        if folder and (Path(folder) / "qjs.exe").is_file():
            return ProcessRuntime("QuickJS", str(Path(folder) / "qjs.exe"), ("--script",))
    return None


def _on_path() -> ProcessRuntime | None:
    for executable, arguments in _PROCESS_RUNTIMES:
        path = shutil.which(executable)
        if path:
            return ProcessRuntime(executable, path, arguments)
    return None


@functools.cache
def find_runtime() -> JsRuntime | None:
    """The first engine available, or None. Set HARMONIA_JS_RUNTIME=path to force one."""
    forced = os.environ.get("HARMONIA_JS_RUNTIME", "")
    if forced:
        name = Path(forced).stem.lower()
        arguments = dict(_PROCESS_RUNTIMES).get(name, ())
        return ProcessRuntime(name, forced, arguments)
    for finder in (_javascriptcore, _bundled_quickjs, _on_path):
        runtime = finder()
        if runtime is not None:
            LOGGER.info("JavaScript engine: %s", runtime.name)
            return runtime
    return None
