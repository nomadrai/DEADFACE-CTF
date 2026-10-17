#!/usr/bin/env bash
# =============================================================================
# DEADFACE-CTF :: WSL2 Ubuntu bootstrap
#
# Reproduces the CTF-Playbook.md toolchain inside Ubuntu on WSL2:
#   - base packages (git, python, build tools, Go, Rust, Ruby, Java, PHP, ...)
#   - ljagiello/ctf-skills toolchain installer (pip/gems/go/PAT backends)
#   - uv, pwndbg, pwndbg-mcp  (for the MCP debugger)
#   - owner tools: RsaCtfTool, theHarvester, jadx, stegsolve, crypto-attacks, pycdc
#   - optional big tools: Ghidra, Burp Suite Community (SKIP_BIG_TOOLS=1 to skip)
#
# Idempotent: safe to re-run. Logs to ~/.ctf-tools/bootstrap-<timestamp>.log
#
# Usage (inside Ubuntu):
#   bash /mnt/c/Users/vista/OneDrive/Desktop/CTF/DEADFACE-CTF/setup/wsl-bootstrap.sh
#   SKIP_BIG_TOOLS=1 bash setup/wsl-bootstrap.sh
# =============================================================================
set -uo pipefail

LOG_DIR="$HOME/.ctf-tools"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/bootstrap-$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
echo "==> DEADFACE-CTF bootstrap; log: $LOG"

export DEBIAN_FRONTEND=noninteractive
export PATH="$HOME/.local/bin:$HOME/go/bin:$PATH"
SKIP_BIG_TOOLS="${SKIP_BIG_TOOLS:-0}"
SKILLS_REPO="$HOME/ctf-skills"
CTF_SKILLS_URL="https://github.com/ljagiello/ctf-skills.git"
PWNDBG_MCP_URL="https://github.com/RocketMaDev/pwndbg-mcp.git"
WIN_OPENCODE_SKILLS="/mnt/c/Users/vista/.config/opencode/skills"
TOOLS="$HOME/tools"
CTF_VENV="$HOME/.ctf-tools/venv"

step() { echo; echo "======================== $* ========================"; }
have() { command -v "$1" >/dev/null 2>&1; }
gh_latest_asset() { # $1=owner/repo  $2=regex on asset name
  curl -fsSL "https://api.github.com/repos/$1/releases/latest" \
    | jq -r --arg re "$2" '.assets[] | select(.name|test($re)) | .browser_download_url' | head -n1
}
apt_install() {
  sudo apt-get install -y -q "$@" || echo "WARN: apt install failed for: $*"
}

# ---------------------------------------------------------------------------
step "1/9 base packages"
sudo apt-get update -y
apt_install git curl wget unzip zip tar xz-utils p7zip-full build-essential cmake \
  pkg-config python3 python3-pip python3-venv pipx jq file xxd bsdextrautils \
  libgmp-dev libffi-dev libssl-dev

step "2/9 language runtimes"
apt_install golang-go rustc cargo ruby-full php-cli default-jdk-headless sqlite3 redis-tools

step "3/9 CTF tools (apt)"
apt_install nmap masscan sqlmap httpie hydra smbclient ldap-utils mitmproxy \
  hashcat john hashid pari-gp \
  binwalk foremost scalpel sleuthkit testdisk yara tshark tcpdump poppler-utils \
  pngcheck libimage-exiftool-perl \
  gdb gdbserver ltrace strace patchelf checksec qemu-user qemu-user-static \
  nasm binutils binutils-multiarch libc6-dbg radare2 apktool upx \
  whois dnsutils recon-ng steghide outguess qrencode zbar-tools imagemagick \
  ffmpeg netcat-openbsd socat rlwrap tmux

# ---------------------------------------------------------------------------
step "4/9 ctf-skills + toolchain installer (pip/gems/go/pat/manual; apt done above)"
if [ -d "$SKILLS_REPO/.git" ]; then
  git -C "$SKILLS_REPO" pull --ff-only || echo "WARN: git pull failed; using existing checkout"
else
  git clone --depth 1 "$CTF_SKILLS_URL" "$SKILLS_REPO" || { echo "FATAL: clone failed"; exit 1; }
fi
cd "$SKILLS_REPO"
bash scripts/install_ctf_tools.sh --skip apt,brew all || echo "WARN: installer reported failures (check the log)"

# Extra pip tools into the same venv the installer uses.
if [ -f "$CTF_VENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$CTF_VENV/bin/activate"
  pip install -q hashid scipy requests 2>/dev/null || echo "WARN: extra pip tools failed"
fi

# ---------------------------------------------------------------------------
step "5/9 uv"
if ! have uv; then curl -LsSf https://astral.sh/uv/install.sh | sh; fi
uv --version || echo "WARN: uv not on PATH"

# ---------------------------------------------------------------------------
step "6/9 pwndbg + pwndbg-mcp"
mkdir -p "$TOOLS"
if [ ! -d "$TOOLS/pwndbg/.git" ]; then
  git clone https://github.com/pwndbg/pwndbg.git "$TOOLS/pwndbg" || echo "WARN: pwndbg clone failed"
fi
if [ -d "$TOOLS/pwndbg" ]; then ( cd "$TOOLS/pwndbg" && ./setup.sh ) || echo "WARN: pwndbg setup.sh returned non-zero"; fi
if [ ! -d "$TOOLS/pwndbg-mcp/.git" ]; then
  git clone "$PWNDBG_MCP_URL" "$TOOLS/pwndbg-mcp" || echo "WARN: pwndbg-mcp clone failed"
fi
if [ -d "$TOOLS/pwndbg-mcp" ]; then
  uv tool install --force "$TOOLS/pwndbg-mcp" || echo "WARN: uv tool install pwndbg-mcp failed"
fi
"$HOME/.local/bin/pwndbg-mcp" --help >/dev/null 2>&1 \
  && echo "OK: pwndbg-mcp at $HOME/.local/bin/pwndbg-mcp" || echo "WARN: pwndbg-mcp --help failed"

# ---------------------------------------------------------------------------
step "7/9 owner tools (RsaCtfTool, theHarvester, jadx, stegsolve, crypto-attacks, pycdc)"
if [ ! -d "$TOOLS/RsaCtfTool/.git" ]; then
  git clone --depth 1 https://github.com/RsaCtfTool/RsaCtfTool.git "$TOOLS/RsaCtfTool" || true
fi
if [ -d "$TOOLS/RsaCtfTool" ]; then
  ( cd "$TOOLS/RsaCtfTool" && pip install -q -r requirements.txt 2>/dev/null \
      || pip install -q . 2>/dev/null || echo "WARN: RsaCtfTool deps not installed" ) || true
fi
if [ ! -d "$TOOLS/theHarvester/.git" ]; then
  git clone --depth 1 https://github.com/laramies/theHarvester.git "$TOOLS/theHarvester" || true
fi
if [ ! -x "$TOOLS/jadx/bin/jadx" ]; then
  jadx_url="$(gh_latest_asset skylot/jadx 'jadx-[0-9.]+\.zip$')"
  if [ -n "${jadx_url:-}" ]; then
    mkdir -p "$TOOLS/jadx" && curl -fsSL "$jadx_url" -o /tmp/jadx.zip \
      && unzip -oq /tmp/jadx.zip -d "$TOOLS/jadx" && chmod +x "$TOOLS/jadx/bin/"*.sh 2>/dev/null || true
  else echo "WARN: could not resolve jadx release"; fi
fi
if [ ! -f "$TOOLS/stegsolve/Stegsolve.jar" ]; then
  mkdir -p "$TOOLS/stegsolve"
  curl -fsSL "https://github.com/eugenekolo/sec-tools/raw/master/stego/stegsolve/stegsolve.jar" \
    -o "$TOOLS/stegsolve/Stegsolve.jar" || echo "WARN: stegsolve jar download failed"
fi
if [ ! -d "$HOME/.ctf-tools/crypto-attacks/.git" ]; then
  git clone --depth 1 https://github.com/jvdsn/crypto-attacks "$HOME/.ctf-tools/crypto-attacks" || true
fi
if [ ! -x "$TOOLS/pycdc/pycdas" ]; then
  git clone --depth 1 https://github.com/zrax/pycdc "$TOOLS/pycdc" \
    && ( cd "$TOOLS/pycdc" && cmake . >/dev/null 2>&1 && make -j"$(nproc)" >/dev/null 2>&1 ) \
    || echo "WARN: pycdc build failed"
fi

# ---------------------------------------------------------------------------
step "8/9 big tools (Ghidra, Burp CE)"
if [ "$SKIP_BIG_TOOLS" = "1" ]; then
  echo "SKIP_BIG_TOOLS=1 -> skipping Ghidra and Burp"
else
  if [ ! -x "$TOOLS/ghidra/ghidraRun" ]; then
    ghidra_url="$(gh_latest_asset NationalSecurityAgency/ghidra 'ghidra_.*_PUBLIC_.*\.zip$')"
    if [ -n "${ghidra_url:-}" ]; then
      curl -fsSL "$ghidra_url" -o /tmp/ghidra.zip \
        && unzip -oq /tmp/ghidra.zip -d "$TOOLS" \
        && mv "$TOOLS"/ghidra_*_PUBLIC "$TOOLS/ghidra" 2>/dev/null || true
      chmod +x "$TOOLS/ghidra/ghidraRun" 2>/dev/null || true
      echo "Ghidra at $TOOLS/ghidra/ghidraRun"
    else echo "WARN: could not resolve Ghidra release"; fi
  fi
  if [ ! -x /opt/BurpSuiteCommunity/BurpSuiteCommunity ]; then
    burp_url="$(curl -fsSL 'https://portswigger.net/burp/releases/community/latest' \
      | grep -oiE 'https://portswigger-cdn[^"]*community[^"]*linux[^"]*' | head -n1)"
    if [ -n "${burp_url:-}" ]; then
      sudo mkdir -p /opt/BurpSuiteCommunity \
        && curl -fsSL "$burp_url" -o /tmp/burp.sh && sudo chmod +x /tmp/burp.sh \
        && sudo /tmp/burp.sh -q -dir /opt/BurpSuiteCommunity || echo "WARN: Burp install failed"
    else echo "NOTE: could not resolve Burp URL; install manually if needed"; fi
  fi
fi

# ---------------------------------------------------------------------------
step "9/9 PAT for the Windows-side OpenCode skill copy (best effort)"
if [ -d "$WIN_OPENCODE_SKILLS/ctf-web" ] && [ ! -d "$WIN_OPENCODE_SKILLS/ctf-web/payloads/PayloadsAllTheThings" ]; then
  mkdir -p "$WIN_OPENCODE_SKILLS/ctf-web/payloads"
  git clone --depth 1 https://github.com/swisskyrepo/PayloadsAllTheThings.git \
    "$WIN_OPENCODE_SKILLS/ctf-web/payloads/PayloadsAllTheThings" || echo "WARN: PAT clone to Windows skills copy failed"
fi

echo
echo "==> Bootstrap finished. Log: $LOG"
echo "==> Start the pwndbg MCP with:  $HOME/.local/bin/pwndbg-mcp"
