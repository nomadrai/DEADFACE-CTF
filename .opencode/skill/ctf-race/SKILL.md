---
name: ctf-race
description: Race multiple free opencode models against CTF challenges in parallel using the local orchestrator. Use when asked to auto-solve challenges, spawn a solver swarm, race models, pull challenges from CTFd, or run the coordinator.
---

# CTF Race (opencode orchestrator)

A local, no-API-key replacement for a multi-model CTF solver swarm. It polls a
CTFd instance (or local folders), races several free `opencode/*-free` models on
each challenge via `opencode run --agent ctf-solver`, and auto-submits the first
flag found.

## Commands

- `python3 orchestrator/orchestrator.py status` — list challenges + solved state.
- `python3 orchestrator/orchestrator.py pull` — download/refresh challenges from CTFd.
- `python3 orchestrator/orchestrator.py run --max-challenges 5` — the race loop.
- `python3 orchestrator/orchestrator.py solve <challenge-dir>` — race one local folder.
- `python3 orchestrator/orchestrator.py submit --challenge "<name>" --flag "<flag>"` — submit manually.
- `python3 orchestrator/orchestrator.py msg "..."` — send an operator hint to the running coordinator (writes `logs/operator_inbox`).

## How a race works

1. Each challenge folder gets one `ctf-solver` process per model in the lineup
   (default: `deepseek-v4.1-flash-free`, `glm-5.3-flash-free`, `big-pickle`,
   `beam-free`, `mimo-v2.6-flash-free`).
2. A solver must write `./flag.txt` and print `FLAG: <value>`.
3. The first racer to produce a flag is accepted; the others are cancelled.
4. The flag is submitted to CTFd; on rejection the race retries with aggregated
   cross-model findings as an "insight" (up to `--attempts`).

## Configuration

Set in `.env` (git-ignored): `CTFD_URL`, `CTFD_TOKEN` (or `CTFD_USER`/`CTFD_PASS`).
Optional: `RACE_MODELS` (comma list), `RACE_PER_CHALLENGE`, `MAX_CHALLENGES`,
`MAX_ATTEMPTS`, `SOLVER_TIMEOUT`, `POLL_INTERVAL`.

## Rules

- Only attack challenge-provided targets and the CTFd API — never other players.
- One challenge per `<category>/<kebab-name>/` folder; keep all artifacts inside it.
- Auto-submit is on; do not brute-force or spam the submit endpoint.
