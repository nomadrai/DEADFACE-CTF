# DEADFACE-CTF environment setup

Reproduces the toolchain described in `../CTF-Playbook.md`.

This repo is shared: other collaborators run **Ubuntu natively**, so the tracked
setup files are Ubuntu-friendly. Windows/WSL-only helpers are git-ignored and
kept local to the Windows machine.

## Tracked files

| File | Purpose |
|---|---|
| `wsl-bootstrap.sh` | Installs the CTF toolchain. Works on native Ubuntu (the Windows path is skipped automatically). |
| `README.md` | This file. |

## Windows-only helpers (git-ignored, not shared)

`post-reboot.ps1`, `start-pwndbg-mcp.ps1` — specific to the Windows/WSL machine
that authored the repo. They are ignored via `setup/*.ps1`.

## Toolchain (Ubuntu)

Run from the repo root:

```bash
cd /path/to/DEADFACE-CTF
bash setup/wsl-bootstrap.sh
# Skip the large Ghidra + Burp downloads:
SKIP_BIG_TOOLS=1 bash setup/wsl-bootstrap.sh
```

It installs: apt CTF tools, the `ljagiello/ctf-skills` pip/gems/go/PAT backends,
`uv`, `pwndbg`, `pwndbg-mcp`, RsaCtfTool, theHarvester, jadx, stegsolve,
crypto-attacks, pycdc, and optionally Ghidra + Burp CE. Logs go to
`~/.ctf-tools/bootstrap-*.log`.

Verify afterwards:

```bash
bash ~/ctf-skills/scripts/install_ctf_tools.sh --verify
```

## Skills (OpenCode)

The 11 skills from `ljagiello/ctf-skills` (`solve-challenge`, `ctf-web`,
`ctf-pwn`, `ctf-crypto`, `ctf-reverse`, `ctf-forensics`, `ctf-osint`, `ctf-misc`,
`ctf-malware`, `ctf-writeup`, `ctf-ai-ml`) are discovered from
`~/.config/opencode/skills/`. To install them on another machine:

```bash
git clone --depth 1 https://github.com/ljagiello/ctf-skills ~/ctf-skills
mkdir -p ~/.config/opencode/skills
cp -r ~/ctf-skills/{solve-challenge,ctf-*} ~/.config/opencode/skills/
```

## pwndbg MCP

`../opencode.jsonc` registers a remote MCP server at `http://localhost:8780/mcp`.
Start it inside Ubuntu and check the connection:

```bash
~/.local/bin/pwndbg-mcp --transport http --host 0.0.0.0 --port 8780
opencode mcp list    # expect: pwndbg connected
```

## Notes

- Linux tooling lives in `~` (`~/tools`, `~/.ctf-tools`).
- The playbook's "Other skills" (`impeccable`, `customize-opencode`,
  `omnirush-*`) are **not** part of `ljagiello/ctf-skills`; ask if you want them
  authored.
