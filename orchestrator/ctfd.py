#!/usr/bin/env python3
"""Minimal CTFd client for the orchestrator.

Dependency-light (requests + bs4 + pyyaml). Supports token auth or
username/password session auth, challenge pulling, and flag submission.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests
import yaml
from bs4 import BeautifulSoup

requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/45.0.2454.85 Safari/537.36"
)  # noqa: E501

BLOCK_TAGS = (
    "p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "pre", "tr", "section", "article", "blockquote",
)


def slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r'[<>:"/\\|?*.\x00-\x1f]', "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "challenge"


def html_to_text(html: Optional[str]) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(BLOCK_TAGS):
        tag.append("\n")
    text = soup.get_text()
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def filename_from_url(url: str) -> str:
    path = urlparse(url).path
    return path.rstrip("/").rsplit("/", 1)[-1] or "file"


@dataclass
class SubmitResult:
    status: str  # correct | already_solved | incorrect | unknown
    message: str
    display: str

    @property
    def accepted(self) -> bool:
        return self.status in ("correct", "already_solved")


@dataclass
class CTFdClient:
    base_url: str = ""
    token: str = ""
    username: str = ""
    password: str = ""
    timeout: float = 30.0

    _session: requests.Session = field(default_factory=requests.Session, repr=False)
    _csrf: str = ""
    _logged_in: bool = False
    _challenge_ids: dict[str, int] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.base_url = (self.base_url or "").rstrip("/")
        if not self.base_url:
            raise ValueError("CTFdClient requires base_url")
        self._session.verify = False
        self._session.headers.update({"User-Agent": USER_AGENT})

    # -- auth -----------------------------------------------------------------

    def _login(self) -> None:
        if self._logged_in or self.token:
            return
        r = self._session.get(f"{self.base_url}/login", timeout=self.timeout)
        m = re.search(r'id="nonce"[^>]*value="([^"]+)"', r.text) or re.search(
            r'name="nonce"[^>]*value="([^"]+)"', r.text
        )
        if not m:
            raise RuntimeError("Could not find nonce on CTFd login page")
        r = self._session.post(
            f"{self.base_url}/login",
            data={
                "name": self.username,
                "password": self.password,
                "_submit": "Submit",
                "nonce": m.group(1),
            },
            timeout=self.timeout,
            allow_redirects=False,
        )
        if r.status_code == 200:
            raise RuntimeError("CTFd login failed — bad credentials")
        self._logged_in = True

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Token {self.token}"
        return h

    def _csrf_token(self) -> str:
        if self._csrf:
            return self._csrf
        r = self._session.get(f"{self.base_url}/challenges", timeout=self.timeout)
        m = re.search(r"csrfNonce':\s*\"([A-Fa-f0-9]+)\"", r.text)
        if not m:
            raise RuntimeError("Could not find csrfNonce on CTFd challenges page")
        self._csrf = m.group(1)
        return self._csrf

    # -- API ------------------------------------------------------------------

    def _get(self, path: str) -> Any:
        self._login()
        r = self._session.get(
            f"{self.base_url}/api/v1{path}", headers=self._headers(), timeout=self.timeout
        )
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict[str, Any]) -> Any:
        self._login()
        headers = self._headers()
        if not self.token:
            headers["CSRF-Token"] = self._csrf_token()
        r = self._session.post(
            f"{self.base_url}/api/v1{path}", json=body, headers=headers, timeout=self.timeout
        )
        if r.status_code == 403 and not self.token:
            self._csrf = ""
            headers["CSRF-Token"] = self._csrf_token()
            r = self._session.post(
                f"{self.base_url}/api/v1{path}", json=body, headers=headers, timeout=self.timeout
            )
        r.raise_for_status()
        return r.json()

    def verify(self) -> bool:
        r = self._session.get(
            f"{self.base_url}/api/v1/users/me",
            headers={"User-Agent": USER_AGENT, **self._headers()},
            timeout=self.timeout,
        )
        return r.status_code == 200 and r.json().get("success", False)

    def fetch_challenge_stubs(self) -> list[dict[str, Any]]:
        data = self._get("/challenges?per_page=500")
        return [c for c in data.get("data", []) if c.get("type") != "hidden"]

    def fetch_all_challenges(self) -> list[dict[str, Any]]:
        out = []
        for stub in self.fetch_challenge_stubs():
            try:
                out.append(self._get(f"/challenges/{stub['id']}")["data"])
            except Exception:  # noqa: BLE001
                continue
        return out

    def get_challenge_id(self, name: str) -> int:
        if name in self._challenge_ids:
            return self._challenge_ids[name]
        for c in self.fetch_challenge_stubs():
            self._challenge_ids[c["name"]] = c["id"]
        if name not in self._challenge_ids:
            raise RuntimeError(f'Challenge "{name}" not found in CTFd')
        return self._challenge_ids[name]

    def fetch_solved_names(self) -> set[str]:
        try:
            me = self._get("/users/me").get("data", {})
            team_id = me.get("team_id")
            if team_id:
                solves = self._get(f"/teams/{team_id}/solves")
            else:
                uid = me.get("id")
                if not uid:
                    return set()
                solves = self._get(f"/users/{uid}/solves")
            return {
                s["challenge"]["name"]
                for s in solves.get("data", [])
                if s.get("challenge", {}).get("name")
            }
        except Exception:  # noqa: BLE001
            print("WARN: could not fetch solved challenges", file=sys.stderr)
            return set()

    def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult:
        cid = self.get_challenge_id(challenge_name)
        resp = self._post(
            "/challenges/attempt", {"challenge_id": cid, "submission": flag}
        ).get("data", {})
        status = resp.get("status", "unknown")
        message = resp.get("message", "")
        return SubmitResult(status, message, f"{status.upper()} — {message}".strip())

    # -- pull to disk ---------------------------------------------------------

    def pull_challenge(self, challenge: dict[str, Any], output_dir: Path) -> Path:
        self._login()
        name = challenge.get("name", f"challenge-{challenge['id']}")
        ch_dir = Path(output_dir) / slugify(name)
        ch_dir.mkdir(parents=True, exist_ok=True)

        for raw_url in challenge.get("files") or []:
            url = (
                raw_url
                if raw_url.startswith("http")
                else f"{self.base_url}/{raw_url.lstrip('/')}"
            )
            dest = ch_dir / "distfiles" / filename_from_url(raw_url)
            if dest.exists():
                continue
            try:
                headers = (
                    self._headers()
                    if urlparse(url).hostname == urlparse(self.base_url).hostname
                    else {}
                )
                r = self._session.get(
                    url, headers=headers, timeout=60.0, allow_redirects=True
                )
                r.raise_for_status()
                dest.parent.mkdir(exist_ok=True)
                dest.write_bytes(r.content)
            except Exception as e:  # noqa: BLE001
                print(f"  WARN: failed to download {url}: {e}", file=sys.stderr)

        meta = {
            "version": "beta1",
            "name": name,
            "category": challenge.get("category", ""),
            "description": html_to_text(challenge.get("description") or ""),
            "value": challenge.get("value", 0),
            "solves": challenge.get("solves", 0),
            "connection_info": challenge.get("connection_info") or "",
            "tags": [
                t["value"] if isinstance(t, dict) else str(t)
                for t in (challenge.get("tags") or [])
            ],
        }
        hints = []
        for h in challenge.get("hints") or []:
            entry: dict[str, Any] = {"cost": h.get("cost", 0)}
            if h.get("content"):
                entry["content"] = h["content"]
            hints.append(entry)
        if hints:
            meta["hints"] = hints

        (ch_dir / "metadata.yml").write_text(
            yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return ch_dir


def client_from_env() -> CTFdClient:
    return CTFdClient(
        base_url=os.environ.get("CTFD_URL", ""),
        token=os.environ.get("CTFD_TOKEN", ""),
        username=os.environ.get("CTFD_USER", ""),
        password=os.environ.get("CTFD_PASS", ""),
    )


def _main() -> None:
    ap = argparse.ArgumentParser(description="CTFd helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pull", help="pull challenges to a directory")
    p.add_argument("--output", default=".")

    s = sub.add_parser("submit", help="submit a flag")
    s.add_argument("--challenge", required=True)
    s.add_argument("--flag", required=True)

    args = ap.parse_args()
    c = client_from_env()

    if args.cmd == "pull":
        for ch in c.fetch_all_challenges():
            d = c.pull_challenge(ch, Path(args.output))
            print(f"pulled [{ch.get('category','?')}] {ch.get('name')} -> {d}")
    elif args.cmd == "submit":
        res = c.submit_flag(args.challenge, args.flag)
        print(res.display)
        sys.exit(0 if res.accepted else 1)


if __name__ == "__main__":
    _main()
