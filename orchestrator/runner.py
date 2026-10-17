#!/usr/bin/env python3
"""Racer — one autonomous solver process driving `opencode run`.

Each Racer runs the project `ctf-solver` agent on a single challenge folder with
a specific model and watches for a flag, so the orchestrator can race several
models and cancel the losers as soon as one wins.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

FLAG_RE = re.compile(r"[A-Za-z0-9_]{2,32}\{[^}\n]{1,200}\}")
PLACEHOLDER = re.compile(
    r"^(og)?(ctf|flag|test|example|placeholder|fake|dummy|sample|todo|redacted)[^a-z0-9]*$",
    re.IGNORECASE,
)


def extract_flag(text: str) -> str | None:
    """Return the first plausible flag in text, skipping obvious placeholders."""
    for m in FLAG_RE.finditer(text or ""):
        flag = m.group(0)
        inner = flag[flag.index("{") + 1 : -1]
        prefix = flag[: flag.index("{")]
        if PLACEHOLDER.match(prefix) and PLACEHOLDER.match(inner):
            continue
        if PLACEHOLDER.match(inner):
            continue
        return flag
    return None


@dataclass
class SolverResult:
    model: str
    status: str  # flag | gave_up | error | timeout | cancelled
    flag: str | None
    findings: str
    log_path: str
    duration: float

    @property
    def won(self) -> bool:
        return self.status == "flag" and bool(self.flag)


def build_prompt(challenge_dir: Path, meta: dict, repo_root: Path) -> str:
    dist = sorted(
        p.name for p in (challenge_dir / "distfiles").glob("*") if p.is_file()
    ) if (challenge_dir / "distfiles").exists() else []

    lines = [
        "Solve this CTF challenge and find the real flag.",
        "",
        f"Challenge : {meta.get('name', 'Unknown')}",
        f"Category  : {meta.get('category', 'Unknown')}",
        f"Points    : {meta.get('value', '?')}",
    ]
    if meta.get("tags"):
        lines.append(f"Tags      : {', '.join(meta['tags'])}")
    lines += ["", "Description:", meta.get("description") or "_(none)_", ""]

    if meta.get("connection_info"):
        lines += [
            "Service connection (connect FIRST):",
            "```",
            str(meta["connection_info"]).strip(),
            "```",
            "",
        ]

    if dist:
        lines.append("Distfiles (relative to cwd):")
        lines += [f"- distfiles/{n}" for n in dist]
        lines.append("")

    if meta.get("hints"):
        lines.append("Hints:")
        for h in meta["hints"]:
            if h.get("content"):
                lines.append(f"- {h['content']}")
        lines.append("")

    lines += [
        f"Your challenge folder (absolute): {challenge_dir}",
        "Use ABSOLUTE paths under that folder for every read/write (file tools may",
        "resolve relative paths against the repo root). Prefer bash with absolute",
        "paths, e.g. `cat " + str(challenge_dir / 'distfiles') + "/...`.",
        "route via the `solve-challenge` skill, and work until you have the flag.",
        "",
        "You may self-verify a candidate before finishing:",
        f'  python3 "{repo_root / "orchestrator" / "ctfd.py"}" submit '
        f'--challenge "{meta.get("name", "")}" --flag "<FLAG>"',
        "",
        f"MANDATORY when found: write it to {challenge_dir / 'flag.txt'} "
        "(absolute path, single line) AND print `FLAG: <value>`.",
    ]
    return "\n".join(lines)


class Racer:
    def __init__(
        self,
        model: str,
        challenge_dir: Path,
        prompt: str,
        log_path: Path,
        repo_root: Path,
        timeout: int = 1800,
    ) -> None:
        self.model = model
        self.challenge_dir = Path(challenge_dir)
        self.prompt = prompt
        self.log_path = Path(log_path)
        self.repo_root = Path(repo_root)
        self.timeout = timeout
        self.proc: asyncio.subprocess.Process | None = None
        self.result: SolverResult | None = None
        self._watcher: asyncio.Task | None = None
        self.flag_found = asyncio.Event()
        self.done_event = asyncio.Event()
        self._transcript: list[str] = []
        self._flag: str | None = None

    async def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["ORCHESTRATOR_ROOT"] = str(self.repo_root)
        cmd = [
            "opencode",
            "run",
            "-m",
            self.model,
            "--agent",
            "ctf-solver",
            "--format",
            "json",
            "--auto",
            self.prompt,
        ]
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.challenge_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            limit=1024 * 1024,
        )
        self._watcher = asyncio.create_task(self._watch())

    async def _watch(self) -> None:
        assert self.proc and self.proc.stdout
        t0 = time.monotonic()
        with open(self.log_path, "w", encoding="utf-8", errors="replace") as log:
            try:
                while True:
                    remaining = self.timeout - (time.monotonic() - t0)
                    if remaining <= 0:
                        break
                    try:
                        raw = await asyncio.wait_for(
                            self.proc.stdout.readline(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        break
                    if not raw:
                        break
                    line = raw.decode("utf-8", "replace")
                    log.write(line)
                    log.flush()
                    self._transcript.append(line)
                    if self._flag is None:
                        f = extract_flag(line)
                        if f:
                            self._flag = f
                            self.flag_found.set()
            finally:
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=30)
                except asyncio.TimeoutError:
                    self.proc.kill()

        if self._flag is None:
            self._flag = self._flag_from_file()
        self.result = self._finish(time.monotonic() - t0)
        self.done_event.set()

    def _flag_from_file(self) -> str | None:
        fp = self.challenge_dir / "flag.txt"
        if fp.exists():
            return extract_flag(fp.read_text(errors="replace").strip())
        return None

    async def wait(self) -> SolverResult:
        await self.done_event.wait()
        if self.result is None:
            self.result = self._finish(0.0)
        return self.result

    def cancel(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass

    def _finish(self, duration: float) -> SolverResult:
        transcript = "".join(self._transcript)
        log_tail = transcript[-4000:]
        if self._flag:
            return SolverResult(
                self.model, "flag", self._flag, log_tail, str(self.log_path), duration
            )
        if self.proc and self.proc.returncode not in (0, -15, None):
            status = "error"
        else:
            status = "gave_up"
        return SolverResult(self.model, status, None, log_tail, str(self.log_path), duration)
