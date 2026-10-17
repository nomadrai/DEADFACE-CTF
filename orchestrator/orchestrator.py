#!/usr/bin/env python3
"""CTF orchestrator — no-API-key multi-model race built on `opencode run`.

Polls CTFd (or local folders), races several free opencode models on each
challenge via the project `ctf-solver` agent, and auto-submits the first flag.

    python3 orchestrator/orchestrator.py status
    python3 orchestrator/orchestrator.py pull
    python3 orchestrator/orchestrator.py run --max-challenges 4
    python3 orchestrator/orchestrator.py solve web/my-challenge
    python3 orchestrator/orchestrator.py submit --challenge my-challenge --flag 'flag{...}'
    python3 orchestrator/orchestrator.py msg "hint text for the coordinator"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import yaml

from runner import Racer, SolverResult, build_prompt
from ctfd import CTFdClient

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = REPO_ROOT / ".orchestrator_state.json"
LOG_DIR = REPO_ROOT / "logs"
OPERATOR_INBOX = LOG_DIR / "operator_inbox"

DEFAULT_MODELS = [
    "opencode/deepseek-v4.1-flash-free",
    "opencode/glm-5.3-flash-free",
    "opencode/big-pickle",
    "opencode/beam-free",
    "opencode/mimo-v2.6-flash-free",
]


# --------------------------------------------------------------------------- #
# env / config
# --------------------------------------------------------------------------- #

def load_env() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


class Config:
    def __init__(self, args: argparse.Namespace) -> None:
        self.models: list[str] = (
            [m.strip() for m in args.models.split(",") if m.strip()]
            if getattr(args, "models", None)
            else [m.strip() for m in os.environ.get("RACE_MODELS", "").split(",") if m.strip()]
            or DEFAULT_MODELS
        )
        self.race_per_challenge = args.race or int(os.environ.get("RACE_PER_CHALLENGE", "0")) or len(self.models)
        self.race_per_challenge = max(1, min(self.race_per_challenge, len(self.models)))
        self.max_challenges = args.max_challenges or int(os.environ.get("MAX_CHALLENGES", "4"))
        self.max_attempts = args.attempts or int(os.environ.get("MAX_ATTEMPTS", "3"))
        self.timeout = args.timeout or int(os.environ.get("SOLVER_TIMEOUT", "1800"))
        self.poll = args.poll or int(os.environ.get("POLL_INTERVAL", "15"))
        self.no_submit = args.no_submit
        self.coordinator_model = args.coordinator_model


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def load_meta(ch_dir: Path) -> dict:
    f = ch_dir / "metadata.yml"
    if f.exists():
        return yaml.safe_load(f.read_text()) or {}
    return {}


def local_challenges() -> list[Path]:
    """Find challenge folders (containing metadata.yml) under category dirs."""
    found = []
    for meta in REPO_ROOT.glob("*/*/metadata.yml"):
        if ".opencode" in meta.parts or "orchestrator" in meta.parts:
            continue
        found.append(meta.parent)
    return sorted(found)


def aggregate_insights(results: list[SolverResult]) -> str:
    parts = []
    for r in results:
        if r.findings:
            parts.append(f"[model {r.model}] {r.findings[-1200:]}")
    notes = ""
    for p in parts:
        notes += p + "\n\n"
    return notes.strip()


async def synthesize_insight(model: str, ch_name: str, results: list[SolverResult]) -> str:
    """Ask a coordinator model to turn failed attempts into concrete next steps."""
    summary = aggregate_insights(results)
    prompt = (
        f"Challenge '{ch_name}' was attacked by multiple agents and none found the "
        "flag. Here are their logs. Produce 3-6 concrete, technical next approaches "
        "(exact commands/tools/ideas). Be terse.\n\n" + summary[:20000]
    )
    proc = await asyncio.create_subprocess_exec(
        "opencode", "run", "-m", model, "--format", "json", "--auto", prompt,
        cwd=str(REPO_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", "replace")
    try:
        chunks = []
        for line in text.splitlines():
            try:
                ev = json.loads(line)
            except Exception:  # noqa: BLE001
                chunks.append(line)
                continue
            for key in ("text", "content"):
                v = ev.get(key)
                if isinstance(v, str):
                    chunks.append(v)
        text = "\n".join(chunks) or text
    except Exception:  # noqa: BLE001
        pass
    return text[-6000:]


# --------------------------------------------------------------------------- #
# orchestrator
# --------------------------------------------------------------------------- #

class Orchestrator:
    def __init__(self, cfg: Config, client: CTFdClient | None) -> None:
        self.cfg = cfg
        self.client = client
        self.state = load_state()

    # -- local path state -----------------------------------------------------

    def _entry(self, name: str) -> dict:
        return self.state.setdefault(name, {"attempts": 0, "solved": False, "exhausted": False})

    def mark_solved(self, name: str) -> None:
        e = self._entry(name)
        e["solved"] = True
        e["exhausted"] = True
        save_state(self.state)

    # -- race -----------------------------------------------------------------

    async def race(
        self, ch_name: str, ch_dir: Path, insight: str | None
    ) -> tuple[SolverResult | None, list[SolverResult]]:
        meta = load_meta(ch_dir)
        models = self.cfg.models[: self.cfg.race_per_challenge]

        prompt = build_prompt(ch_dir, meta, REPO_ROOT)
        if insight:
            prompt += "\n\n## Prior failed attempts — do NOT repeat these\n" + insight

        racers = [
            Racer(
                model=m,
                challenge_dir=ch_dir,
                prompt=prompt,
                log_path=LOG_DIR / ch_name / f"{m.split('/')[-1]}.log",
                repo_root=REPO_ROOT,
                timeout=self.cfg.timeout,
            )
            for m in models
        ]

        for r in racers:
            await r.start()
        print(f"  race {ch_name}: {', '.join(m.split('/')[-1] for m in models)}")

        winner = await self._wait_for_winner(racers)
        results = [await r.wait() for r in racers]

        win_result = winner.result if (winner and winner.result and winner.result.flag) else None
        return win_result, results

    async def _wait_for_winner(self, racers: list[Racer]) -> Racer | None:
        while True:
            for r in racers:
                if r.flag_found.is_set():
                    for other in racers:
                        if other is not r:
                            other.cancel()
                    return r
            if all(r.done_event.is_set() for r in racers):
                return None
            await asyncio.sleep(0.5)

    # -- one challenge end-to-end --------------------------------------------

    async def handle(self, ch_name: str, ch_dir: Path, remote: dict | None) -> None:
        entry = self._entry(ch_name)
        insight: str | None = None

        while entry["attempts"] < self.cfg.max_attempts and not entry["solved"]:
            entry["attempts"] += 1
            save_state(self.state)
            attempt = entry["attempts"]
            print(f"\n[attempt {attempt}/{self.cfg.max_attempts}] {ch_name}")

            result, results = await self.race(ch_name, ch_dir, insight)

            if result and result.flag:
                print(f"  FLAG ({result.model}): {result.flag}")
                (ch_dir / "flag.txt").write_text(result.flag + "\n")
                if self.cfg.no_submit or remote is None:
                    print("  (no submit — local/dry-run)")
                    self.mark_solved(ch_name)
                    self._writeup(ch_dir, ch_name, result.flag)
                    return
                if await self._submit(ch_name, result.flag):
                    self.mark_solved(ch_name)
                    self._writeup(ch_dir, ch_name, result.flag)
                    return
                print("  flag rejected by CTFd — continuing")
                insight = f"The candidate flag '{result.flag}' was REJECTED. Find the real one."
            else:
                insight = aggregate_insights(results) or self._rollout_insight(ch_name)
                if self.cfg.coordinator_model:
                    try:
                        extra = await synthesize_insight(self.cfg.coordinator_model, ch_name, results)
                        if extra:
                            insight = f"COORDINATOR SUGGESTIONS:\n{extra}\n\nLOGS:\n{insight}"
                    except Exception as e:  # noqa: BLE001
                        print(f"  WARN: coordinator synthesis failed: {e}", file=sys.stderr)

            await asyncio.sleep(1)

        entry["exhausted"] = True
        save_state(self.state)
        print(f"  exhausted {ch_name} after {entry['attempts']} attempt(s)")

    def _rollout_insight(self, ch_name: str) -> str:
        logs = sorted((LOG_DIR / ch_name).glob("*.log"))
        chunks = []
        for lg in logs:
            tail = lg.read_text(errors="replace")[-1500:]
            chunks.append(f"[{lg.stem}] {tail}")
        return "\n\n".join(chunks)

    async def _submit(self, ch_name: str, flag: str) -> bool:
        assert self.client is not None
        res = await asyncio.to_thread(self.client.submit_flag, ch_name, flag)
        print(f"  submit: {res.display}")
        return res.accepted

    def _writeup(self, ch_dir: Path, ch_name: str, flag: str) -> None:
        out = ch_dir / "WRITEUP.md"
        if out.exists():
            return
        meta = load_meta(ch_dir)
        out.write_text(
            f"# {meta.get('name', ch_name)}\n"
            f"- Category: {meta.get('category', '?')}\n"
            "- Trick/vuln: _see logs/_\n"
            "- Steps: _see logs/_\n"
            f"- Flag: `{flag}`\n"
            "- author:nomadrai\n",
            encoding="utf-8",
        )

    # -- loops ----------------------------------------------------------------

    async def run_ctfd(self, once: bool) -> None:
        assert self.client is not None
        sem = asyncio.Semaphore(self.cfg.max_challenges)
        active: dict[str, asyncio.Task] = {}

        while True:
            try:
                challenges = await asyncio.to_thread(self.client.fetch_all_challenges)
                solved = await asyncio.to_thread(self.client.fetch_solved_names)
            except Exception as e:  # noqa: BLE001
                print(f"WARN: CTFd poll failed: {e}", file=sys.stderr)
                await asyncio.sleep(self.cfg.poll)
                continue

            wake = False
            for ch in challenges:
                name = ch.get("name", "")
                if not name or name in solved or name in active:
                    continue
                entry = self._entry(name)
                if entry.get("solved") or entry.get("exhausted"):
                    continue
                if len(active) >= self.cfg.max_challenges:
                    break

                async def _run(ch=ch, name=name):
                    async with sem:
                        ch_dir = await asyncio.to_thread(
                            self.client.pull_challenge, ch, REPO_ROOT
                        )
                        await self.handle(name, Path(ch_dir), ch)

                active[name] = asyncio.create_task(_run())
                active[name].add_done_callback(lambda _t, n=name: active.pop(n, None))
                wake = True

            if once and not active:
                break
            if once and active:
                await asyncio.sleep(1)
                continue
            await asyncio.sleep(self.cfg.poll)

        if active:
            await asyncio.gather(*active.values(), return_exceptions=True)

    async def run_local(self, theme: str | None, once: bool) -> None:
        while True:
            for ch_dir in local_challenges():
                name = ch_dir.name
                if theme and theme not in str(ch_dir):
                    continue
                entry = self._entry(name)
                if entry.get("solved") or entry.get("exhausted"):
                    continue
                await self.handle(name, ch_dir, None)
            if once:
                break
            await asyncio.sleep(self.cfg.poll)

    async def solve_dir(self, ch_dir: Path) -> None:
        await self.handle(ch_dir.name, ch_dir, None)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_client(args: argparse.Namespace) -> CTFdClient | None:
    url = args.ctfd_url or os.environ.get("CTFD_URL", "")
    if not url:
        return None
    return CTFdClient(
        base_url=url,
        token=args.ctfd_token or os.environ.get("CTFD_TOKEN", ""),
        username=os.environ.get("CTFD_USER", ""),
        password=os.environ.get("CTFD_PASS", ""),
    )


def cmd_status(orchestrator: Orchestrator) -> None:
    if orchestrator.client:
        try:
            chs = orchestrator.client.fetch_all_challenges()
            solved = orchestrator.client.fetch_solved_names()
        except Exception as e:  # noqa: BLE001
            print(f"CTFd error: {e}", file=sys.stderr)
            chs, solved = [], set()
    else:
        chs = []
        for d in local_challenges():
            m = load_meta(d)
            chs.append({"name": d.name, "category": m.get("category", ""), "value": m.get("value", 0)})
        solved = set()

    print(f"{'STATUS':8} {'CATEGORY':12} {'PTS':>4}  NAME")
    for ch in sorted(chs, key=lambda c: c.get("value", 0)):
        name = ch.get("name", "?")
        st = "SOLVED" if name in solved else "open"
        print(f"{st:8} {str(ch.get('category',''))[:12]:12} {str(ch.get('value','')):>4}  {name}")
    print(f"\n{len(solved)}/{len(chs)} solved")


def cmd_pull(orchestrator: Orchestrator) -> None:
    if not orchestrator.client:
        print("No CTFD_URL configured.", file=sys.stderr)
        sys.exit(1)
    for ch in orchestrator.client.fetch_all_challenges():
        d = orchestrator.client.pull_challenge(ch, REPO_ROOT)
        print(f"pulled [{ch.get('category','?')}] {ch.get('name')} -> {d}")


def main() -> None:
    load_env()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ctfd-url")
    common.add_argument("--ctfd-token")
    common.add_argument("--models", help="comma-separated model specs (override lineup)")
    common.add_argument("--race", type=int, help="models raced per challenge")
    common.add_argument("--max-challenges", type=int, help="max simultaneous challenges")
    common.add_argument("--attempts", type=int, help="max attempts per challenge")
    common.add_argument("--timeout", type=int, help="solver timeout seconds")
    common.add_argument("--poll", type=int, help="poll interval seconds")
    common.add_argument("--coordinator-model", help="free model to synthesize retry insights")
    common.add_argument("--no-submit", action="store_true", help="never submit to CTFd")
    common.add_argument("--once", action="store_true", help="single sweep, then exit")

    ap = argparse.ArgumentParser(description="opencode CTF orchestrator")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("status", parents=[common])
    sub.add_parser("pull", parents=[common])
    sub.add_parser("run", parents=[common])
    sub.add_parser("local", parents=[common])
    sp = sub.add_parser("solve", parents=[common])
    sp.add_argument("dir")
    ss = sub.add_parser("submit", parents=[common])
    ss.add_argument("--challenge", required=True)
    ss.add_argument("--flag", required=True)
    sm = sub.add_parser("msg", parents=[common])
    sm.add_argument("text")

    args = ap.parse_args()
    cfg = Config(args)
    client = build_client(args)
    orch = Orchestrator(cfg, client)

    if args.cmd == "status":
        cmd_status(orch)
    elif args.cmd == "pull":
        cmd_pull(orch)
    elif args.cmd == "submit":
        if not client:
            print("No CTFD_URL configured.", file=sys.stderr)
            sys.exit(1)
        res = client.submit_flag(args.challenge, args.flag)
        print(res.display)
        sys.exit(0 if res.accepted else 1)
    elif args.cmd == "msg":
        OPERATOR_INBOX.parent.mkdir(exist_ok=True)
        with open(OPERATOR_INBOX, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {args.text}\n")
        print("queued")
    elif args.cmd == "solve":
        asyncio.run(orch.solve_dir(Path(args.dir).resolve()))
    elif args.cmd == "local":
        asyncio.run(orch.run_local(theme=None, once=args.once))
    elif args.cmd == "run":
        if client is None:
            print("No CTFD_URL configured; use `local` or set it in .env.", file=sys.stderr)
            sys.exit(1)
        asyncio.run(orch.run_ctfd(once=args.once))
    else:
        ap.print_help()


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    main()
