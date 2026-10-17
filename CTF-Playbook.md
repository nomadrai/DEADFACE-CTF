# CTF Playbook

## Available Tooling
- Harness tools: `apply_patch`, `bash`, `read`, `glob`, `grep`, `question`, `skill`, `task`, `todowrite`, `webfetch`, `multi_tool_use.parallel`.
- Automatic routing: `solve-challenge` detects category and routes to `ctf-web`, `ctf-pwn`, `ctf-crypto`, `ctf-reverse`, `ctf-forensics`, `ctf-osint`, `ctf-misc`, `ctf-malware`, `ctf-writeup`, or `ctf-ai-ml`; do not hand-pick unless routing is wrong.
- Other skills: `impeccable`, `customize-opencode`, `omnirush-{build,debug,feature,handoff,performance,refactor,review,setup,test}`.
- MCP: pwndbg provides a persistent live GDB session for pwn/rev when exposed; do not recreate it manually.
- Already Available (before installs): `bash`, `sh`, coreutils, `grep`, `awk`, `sed`, `find`, `xargs`, `ssh`, `scp`, `sftp`, `curl`, `wget`, `jq`, `file`, `strings`, `tar`, `zip`, `unzip`, `openssl`, `gpg`, `base64`, `md5sum`, `sha256sum`, `python3`, `pip3`, `pipx`, `node`, `npm`, `perl`, `gcc`, `make`, `objdump`, `readelf`, `nm`, `ldd`, `git`; Go/cargo shims were non-functional.
- Already Available runtimes: Python 3.11.2, Node 22.23.3, GCC 12.2.0.
- Installed now: web `nmap`, `masscan`, `ffuf`, `gobuster`, `sqlmap`, `httpie`, `hydra`, `smbclient`, `ldap-utils`, `mitmproxy`; crypto `hashcat`, `john`, `hashid`, `pari-gp`, `cryptography`, `PyCryptodome`, `sympy`, `z3`, `numpy`, `scipy`, `gmpy2`.
- Installed now: forensics `binwalk`, `exiftool`, `foremost`, `scalpel`, `sleuthkit`, `testdisk`, `yara`, `tshark`, `tcpdump`, `poppler-utils`, `pngcheck`, `p7zip`, `scapy`, `Pillow`, `xxd`, `hexdump`; reverse/pwn `gdb`, `gdbserver`, `ltrace`, `strace`, `patchelf`, `checksec`, `qemu-user`, `nasm`, `pwntools`, `ROPgadget`, `capstone`, `unicorn`, `libc6-dbg`.
- Installed now: OSINT/stego/misc `whois`, `dnsutils`, `recon-ng`, `steghide`, `outguess`, `qrencode`, `zbar-tools`, ImageMagick, `ffmpeg`, `nc`, `socat`, `rlwrap`, `tmux`; runtimes Go, Rust/Cargo, Ruby, Java, PHP, SQLite, Redis CLI.
- Installed locally: `.ctf-bin/zsteg` (use `GEM_HOME=.ctf-gems GEM_PATH=.ctf-gems:/usr/lib/ruby/vendor_ruby`); `.ctf-venv/bin/vol` for Volatility 3 (use `HOME=.ctf-home`).
- Owner-provided tool paths: `~/tools/ghidra/ghidraRun`, `~/tools/pwndbg`, `java -jar ~/tools/stegsolve/Stegsolve.jar`, `~/tools/jadx/bin/jadx`, `~/tools/RsaCtfTool`, `cd ~/tools/theHarvester && uv run theHarvester -h`.
- Burp CE: `/opt/BurpSuiteCommunity/BurpSuiteCommunity` if present; verify before use. Host paths/MCP are not mounted in this shell, so do not reinstall them based on a local miss.

## Repo Structure
- Root categories: `web/`, `crypto/`, `forensics/`, `reverse/`, `pwn/`, `osint/`, `stego/`, `misc/`; add categories only when needed.
- One challenge per `<category>/<lowercase-kebab-case>/` folder.
- Keep downloads, references, scripts, extracted data, and notes inside that challenge folder only.
- Solved challenges require `WRITEUP.md`, max ~30 lines: name, category, vuln/trick, key commands, flag, `author:nomadrai`.

## Workflow Rules
- Triage first; take the easiest/highest-value challenges. If stuck too long, switch and return later.
- Stay in scope: attack only challenge-provided targets; never touch the platform or other participants.
- Find the flag, then submit it immediately; submit before writing up and never batch submissions.
- Submit through the platform API or browser automation. Ask once for a needed token/credential; store it only in git-ignored `.env`; never commit secrets.
- Confirm acceptance before marking solved. Rejected flags mean keep working and report the rejection.
- Do not brute-force or spam flag submissions; follow event rules.

## Writeup Template
```md
# <challenge name>
- Category: <category>
- Trick/vuln: <one sentence>
- Steps: `<command>`; `<command>`
- Flag: `<flag>`
- author:nomadrai
```
