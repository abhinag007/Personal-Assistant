"""macOS control (§28) — open apps/files/URLs, search, and (opt-in) run shell commands.

Split by risk:
  * open_app / open_path / open_url / browser_search — harmless, reversible (you can close it).
  * run_command — arbitrary shell. Genuinely dangerous, so it's OPT-IN (JARVIS_ALLOW_SHELL=1)
    and routed through the approval gate by the registry (ActionType.RUN_COMMAND).

`runner` is injectable so tests never actually spawn processes.
"""
from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional
from urllib.parse import quote

from ..tools import ToolResult

Runner = Callable[..., object]


def _exec(args, runner: Optional[Runner] = None, *, shell=False, timeout=30):
    runner = runner or subprocess.run
    return runner(args, capture_output=True, text=True, timeout=timeout, shell=shell)


def open_app(name: str = "", runner: Optional[Runner] = None) -> ToolResult:
    if not name:
        return ToolResult.failure("app name required")
    r = _exec(["open", "-a", name], runner)
    return ToolResult.success(f"opened {name}") if r.returncode == 0 \
        else ToolResult.failure(r.stderr.strip() or f"couldn't open {name}")


def open_path(path: str = "", runner: Optional[Runner] = None) -> ToolResult:
    if not path:
        return ToolResult.failure("path required")
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        return ToolResult.failure(f"no such path: {p}")
    r = _exec(["open", p], runner)
    return ToolResult.success(f"opened {p}") if r.returncode == 0 \
        else ToolResult.failure(r.stderr.strip() or f"couldn't open {p}")


def open_url(url: str = "", runner: Optional[Runner] = None) -> ToolResult:
    if not url.startswith(("http://", "https://")):
        return ToolResult.failure("provide a full http(s) URL")
    r = _exec(["open", url], runner)
    return ToolResult.success(f"opened {url}") if r.returncode == 0 \
        else ToolResult.failure(r.stderr.strip() or "couldn't open url")


def browser_search(query: str = "", browser: str = "Google Chrome",
                   runner: Optional[Runner] = None) -> ToolResult:
    if not query:
        return ToolResult.failure("query required")
    url = f"https://www.google.com/search?q={quote(query)}"
    r = _exec(["open", "-a", browser, url], runner)
    return ToolResult.success(f"searched '{query}' in {browser}") if r.returncode == 0 \
        else ToolResult.failure(r.stderr.strip() or "couldn't open browser")


def run_command(command: str = "", runner: Optional[Runner] = None, timeout: int = 60) -> ToolResult:
    """Run a shell command. OPT-IN (JARVIS_ALLOW_SHELL=1); the registry gates it via approval."""
    if os.environ.get("JARVIS_ALLOW_SHELL", "0") != "1":
        return ToolResult.failure("shell access is disabled. Enable with JARVIS_ALLOW_SHELL=1.")
    if not command.strip():
        return ToolResult.failure("command required")
    try:
        r = _exec(command, runner, shell=True, timeout=timeout)
    except Exception as e:
        return ToolResult.failure(f"{type(e).__name__}: {e}")
    out = (r.stdout or "")
    if getattr(r, "stderr", ""):
        out += ("\n[stderr] " + r.stderr)
    out = out.strip() or f"(exit {getattr(r, 'returncode', '?')})"
    return ToolResult.success(out[:2000])
