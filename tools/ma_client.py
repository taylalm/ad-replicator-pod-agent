#!/usr/bin/env python3
"""Minimal client for the BytePlus ModelArk Managed Agents API (data plane, API-key auth).

Endpoints verified against https://docs.byteplus.com/en/docs/modelark/<page> on 20 Oct 2026:
  get-agent-api / update-agent-api / list-agent-versions-api      /agents/{id}[/versions]
  create-skill-api / create-skill-version-api / list-skill-versions-api  /skills[/{id}/versions]
  create-session-api / get-session-api                             /sessions[/{id}]
  send-event-api / list-events-api / stream-events-api             /sessions/{id}/events[/stream]
  list-files-api (scope_id = session id, download_url per file)    /files?scope_id=...

Auth: `Authorization: Bearer $ARK_API_KEY` (docs: base-url-and-authentication).
The key is read from the ARK_API_KEY environment variable. If that is unset, the key stored by
`arkcli` for its default platform profile (~/.arkcli-bp/config.yaml) is used. The key is never
printed or written anywhere by this tool.

Your agent, environment and vault: MA_AGENT_ID, MA_ENV_ID and MA_VAULT_ID, from the terminal's environment or from a
`.env` file at the repository root (copy `.env.example`), or as --agent-id, --env-id, --vault-id. A variable set in the
terminal wins over `.env`. There are no built-in ids; a command that needs a missing one stops and names it.
`.env` is read for these ids only: the API key never goes into a file.

Only the Python standard library is used (works with python3.9+).
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_BASE = "https://ark.ap-southeast.bytepluses.com/api/v3"
# Your agent, environment and vault come only from these environment variables, the repository's .env file, or the
# --agent-id / --env-id / --vault-id options. There are no built-in ids: a missing one stops the command with a clear message.
ID_VARS = ("MA_AGENT_ID", "MA_ENV_ID", "MA_VAULT_ID")
TERMINAL_EVENTS = {"session.status_idle", "session.status_terminated", "session.deleted"}
REPO = Path(__file__).resolve().parent.parent


SETTINGS_FILE = REPO / ".env"


def load_settings_file(path=SETTINGS_FILE):
    """Copies MA_AGENT_ID / MA_ENV_ID / MA_VAULT_ID from `path` (KEY=value lines, `export` and quotes allowed) into
    os.environ when they are not already set there. Every other line is ignored, so a key written there is never used."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if not m or m.group(1) not in ID_VARS:
            continue
        value = m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        if value and not value.endswith("...") and not configured_id(m.group(1)):  # "agent-..." = example left unedited
            os.environ[m.group(1)] = value


class MissingSetting(Exception):
    """A required id (MA_AGENT_ID, MA_ENV_ID or MA_VAULT_ID) is not set."""


def configured_id(var):
    """The id in environment variable `var`, or None when it is unset or empty."""
    return (os.environ.get(var) or "").strip() or None


def missing_ids():
    """Names of the id variables that are not set."""
    return [v for v in ID_VARS if not configured_id(v)]


def require_id(value, var):
    """`value` if given, else the id from environment variable `var`; raises MissingSetting when neither is set."""
    value = (value or "").strip() or configured_id(var)
    if not value:
        raise MissingSetting(f"{var} is not set. Put your own id in .env at the repository root (copy .env.example) "
                             f"or export it, e.g. `export {var}=<id>` (see the build guide, 'Your values').")
    return value


load_settings_file()


# --------------------------------------------------------------------------- auth / http
def resolve_api_key() -> str:
    key = os.environ.get("ARK_API_KEY")
    if key:
        return key
    cfg = Path.home() / ".arkcli-bp" / "config.yaml"
    if cfg.exists():
        default_profile = None
        profile = None
        for line in cfg.read_text().splitlines():
            m = re.match(r"^default_profile:\s*(\S+)", line)
            if m:
                default_profile = m.group(1)
            m = re.match(r"^  (\S+):\s*$", line)
            if m:
                profile = m.group(1)
            m = re.match(r"^\s+api_key:\s*(\S+)", line)
            if m and profile == default_profile:
                return m.group(1)
    sys.exit("ARK_API_KEY is not set and no arkcli platform profile key was found")


class ApiError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} for {url}: {body[:800]}")
        self.status, self.body, self.url = status, body, url


class Client:
    def __init__(self, base_url: str = DEFAULT_BASE, api_key: str | None = None, timeout: int = 120):
        self.base = base_url.rstrip("/")
        self.key = api_key or resolve_api_key()
        self.timeout = timeout

    def _request(self, method: str, path: str, *, params=None, json_body=None, data=None,
                 headers=None, stream=False, timeout=None):
        url = self.base + path
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        hdrs = {"Authorization": f"Bearer {self.key}"}
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdrs["Content-Type"] = "application/json"
        elif data is not None:
            body = data
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as e:
            raise ApiError(e.code, e.read().decode(errors="replace"), url) from None
        if stream:
            return resp
        try:
            raw = resp.read()
        except Exception as e:  # http.client.IncompleteRead on large event pages
            raise ApiError(0, f"read error: {type(e).__name__}: {e}", url) from None
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw.decode(errors="replace")}

    def get(self, path, **params):
        return self._request("GET", path, params=params or None)

    def post(self, path, body):
        return self._request("POST", path, json_body=body)

    def delete(self, path):
        return self._request("DELETE", path)

    def post_multipart(self, path, fields: list[tuple[str, str]], files: list[tuple[str, str, bytes]]):
        """files: list of (field_name, filename, content)."""
        boundary = "----ma-client-" + uuid.uuid4().hex
        out = bytearray()
        for name, value in fields:
            out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode()
        for name, filename, content in files:
            ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
                    f"filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()
            out += content + b"\r\n"
        out += f"--{boundary}--\r\n".encode()
        return self._request("POST", path, data=bytes(out),
                             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                             timeout=300)

    # ----------------------------------------------------------------- agents
    def get_agent(self, agent_id=None):
        agent_id = require_id(agent_id, "MA_AGENT_ID")
        return self.get(f"/agents/{agent_id}")

    def agent_versions(self, agent_id=None, limit=20):
        agent_id = require_id(agent_id, "MA_AGENT_ID")
        return self.get(f"/agents/{agent_id}/versions", limit=limit)

    def update_agent(self, agent_id=None, **fields):
        """Posts the given fields with the current version number (optimistic lock per docs)."""
        agent_id = require_id(agent_id, "MA_AGENT_ID")
        current = self.get_agent(agent_id)
        body = {"version": current["version"], **fields}
        return self.post(f"/agents/{agent_id}", body)

    # ----------------------------------------------------------------- skills
    def list_skills(self, limit=100):
        return self.get("/skills", limit=limit)

    def skill_versions(self, skill_id, limit=50):
        return self.get(f"/skills/{skill_id}/versions", limit=limit)

    @staticmethod
    def _collect_skill_files(folder: Path) -> list[tuple[str, str, bytes]]:
        files = []
        for p in sorted(folder.rglob("*")):
            if p.is_dir() or "__pycache__" in p.parts or p.name.startswith("."):
                continue
            # the API requires every file to sit under one top-level directory (the skill name)
            rel = folder.name + "/" + p.relative_to(folder).as_posix()
            files.append(("files[]", rel, p.read_bytes()))
        if not any(f[1] == folder.name + "/SKILL.md" for f in files):
            raise SystemExit(f"{folder} has no SKILL.md at its root")
        return files

    def create_skill(self, folder: Path, display_title: str | None = None):
        files = self._collect_skill_files(folder)
        fields = [("display_title", display_title or folder.name)]
        return self.post_multipart("/skills", fields, files)

    def create_skill_version(self, skill_id: str, folder: Path, display_title: str | None = None):
        files = self._collect_skill_files(folder)
        fields = [("display_title", display_title)] if display_title else []
        return self.post_multipart(f"/skills/{skill_id}/versions", fields, files)

    # ----------------------------------------------------------------- sessions
    def create_session(self, agent_id=None, env_id=None, vault_ids=None, title=None, agent_version=None):
        agent_id = require_id(agent_id, "MA_AGENT_ID")
        env_id = require_id(env_id, "MA_ENV_ID")
        vault_ids = [v for v in (vault_ids or []) if v] or [require_id(None, "MA_VAULT_ID")]
        agent: dict | str = agent_id
        if agent_version is not None:
            agent = {"id": agent_id, "version": agent_version}
        body = {"agent": agent, "environment_id": env_id, "vault_ids": list(vault_ids)}
        if title:
            body["title"] = title
        return self.post("/sessions", body)

    def get_session(self, session_id):
        return self.get(f"/sessions/{session_id}")

    def send_message(self, session_id, text: str, system: str | None = None):
        events = [{"type": "user.message", "content": [{"type": "text", "text": text}]}]
        if system:
            events.append({"type": "system.message", "content": [{"type": "text", "text": system}]})
        return self.post(f"/sessions/{session_id}/events", {"events": events})

    def interrupt(self, session_id):
        return self.post(f"/sessions/{session_id}/events", {"events": [{"type": "user.interrupt"}]})

    def list_events(self, session_id, limit=100, page=None, created_after=None, types=None):
        params = {"limit": limit, "order": "asc"}
        if page:
            params["page"] = page
        if created_after:
            params["created_at[gt]"] = created_after
        if types:
            params["types"] = types
        return self.get(f"/sessions/{session_id}/events", **params)

    def all_events(self, session_id, created_after=None):
        """Every event after the cursor. Pages with large tool results (MBs) sometimes break mid-read
        (IncompleteRead): the same page is retried with a smaller page size."""
        out, page, limit = [], None, 100
        while True:
            for attempt in range(5):
                try:
                    d = self.list_events(session_id, limit=limit, page=page, created_after=created_after)
                    break
                except ApiError as e:
                    if e.status != 0 or attempt == 4:
                        raise
                    limit = max(5, limit // 2)
                    time.sleep(1 + attempt)
            out.extend(d.get("data", []))
            page = d.get("next_page")
            if not page:
                return out

    def stream_events(self, session_id, event_deltas=None):
        """Yields parsed event dicts from the SSE stream (comments/heartbeats are skipped)."""
        params = {"event_deltas": event_deltas} if event_deltas else None
        resp = self._request("GET", f"/sessions/{session_id}/events/stream", params=params,
                             stream=True, timeout=120)
        for raw in resp:
            line = raw.decode(errors="replace").rstrip("\r\n")
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                payload = line[5:].strip()
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    yield {"type": "raw", "raw": payload}

    def wait_idle(self, session_id, poll=5, timeout=3 * 3600, on_event=None, since=None):
        """Polls the event list until a terminal status event arrives after `since`.
        The cursor advances to the last event's processed_at after every poll, so each request
        only returns new events. Returns the list of events seen. `on_event` is called per event."""
        seen, events, deadline = set(), [], time.time() + timeout
        started = False
        cursor = since
        while time.time() < deadline:
            try:
                batch = self.all_events(session_id, created_after=cursor)
            except Exception as e:  # ApiError, URLError, IncompleteRead, timeouts: all transient here
                print(f"[wait] transient error: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
                time.sleep(poll)
                continue
            new = [e for e in batch if e.get("id") not in seen]
            for e in new:
                seen.add(e.get("id"))
                events.append(e)
                if on_event:
                    on_event(e)
                if e.get("type") == "session.status_running":
                    started = True
                if e.get("type") in TERMINAL_EVENTS and started:
                    return events
            if batch and batch[-1].get("processed_at"):
                cursor = batch[-1]["processed_at"]
            time.sleep(poll)
        raise TimeoutError(f"session {session_id} did not go idle within {timeout}s")


    # ----------------------------------------------------------------- uploads (Files API + session resources)
    def upload_file(self, path, purpose="user_data"):
        """Uploads a local image/video/audio/document to the Files API (docs: upload-files-api)."""
        p = Path(path)
        return self.post_multipart("/files", [("purpose", purpose)], [("file", p.name, p.read_bytes())])

    def wait_file_active(self, file_id, timeout=120):
        deadline = time.time() + timeout
        while time.time() < deadline:
            d = self.get(f"/files/{file_id}")
            if d.get("status") == "active":
                return d
            if d.get("status") == "failed":
                raise ApiError(0, f"file {file_id} failed: {d.get('error')}", "/files")
            time.sleep(3)
        raise TimeoutError(f"file {file_id} not active after {timeout}s")

    def add_resource(self, session_id, file_id, mount_path=None):
        """Mounts a Files API file read-only under /mnt/session/uploads/ (docs: add-resource-api)."""
        body = {"type": "file", "file_id": file_id}
        if mount_path:
            body["mount_path"] = mount_path
        return self.post(f"/sessions/{session_id}/resources", body)

    # ----------------------------------------------------------------- files
    def session_files(self, session_id, limit=100):
        out, after = [], None
        while True:
            params = {"scope_id": session_id, "limit": limit}
            if after:
                params["after"] = after
            d = self.get("/files", **params)
            out.extend(d.get("data", []))
            if not d.get("has_more"):
                return out
            after = d.get("last_id")

    def download_session_files(self, session_id, dest: Path, pattern: str | None = None, newer_than=0):
        dest.mkdir(parents=True, exist_ok=True)
        saved, names = [], {}
        for f in self.session_files(session_id):
            name = f.get("filename") or f["id"]
            if pattern and not re.search(pattern, name):
                continue
            if f.get("created_at", 0) < newer_than:
                continue
            url = f.get("download_url")
            if not url or f.get("status") != "active":
                continue
            # the file list is newest-first; keep the newest copy of a repeated name, suffix older ones
            if name in names:
                stem, ext = os.path.splitext(name)
                name = f"{stem}__{f['id'][-5:]}{ext}"
            names[name] = f["id"]
            path = dest / name
            if path.exists() and path.stat().st_size == f.get("bytes"):
                saved.append((name, f["id"], "cached"))
                continue
            with urllib.request.urlopen(url, timeout=300) as r, open(path, "wb") as out:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            saved.append((name, f["id"], f.get("bytes")))
        return saved


# --------------------------------------------------------------------------- summaries
def text_of(content) -> str:
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    return str(content or "")


def summarize(events: list[dict]) -> dict:
    tool_calls, errors, messages, steps = [], [], [], []
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
    results_by_id = {}
    for e in events:
        if e.get("type") == "agent.tool_result":
            results_by_id[e.get("tool_use_id")] = e
    for e in events:
        t = e.get("type")
        if t == "agent.tool_use":
            inp = e.get("input", {})
            brief = inp.get("command") or inp.get("file_path") or inp.get("url") or inp.get("pattern") or json.dumps(inp)[:120]
            res = results_by_id.get(e.get("id"))
            tool_calls.append({"id": e.get("id"), "name": e.get("name"), "input": str(brief)[:300],
                               "is_error": bool(res and res.get("is_error")),
                               "result": text_of(res.get("content"))[:300] if res else None,
                               "at": e.get("processed_at")})
        elif t == "agent.message":
            txt = text_of(e.get("content"))
            messages.append({"at": e.get("processed_at"), "text": txt})
            for m in re.finditer(r"STEP\s+(\d+)/(\d+)\s*:\s*([^\n]+?)\s+-\s+(started|done|failed|skipped)\b[^\n]*", txt, re.I):
                steps.append({"n": int(m.group(1)), "of": int(m.group(2)), "name": m.group(3).strip(),
                              "status": m.group(4).lower(), "at": e.get("processed_at")})
        elif t == "session.error":
            errors.append(e.get("error"))
        elif t == "span.model_request_end":
            for k in usage:
                usage[k] += (e.get("model_usage") or {}).get(k, 0)
            if e.get("is_error"):
                errors.append({"model_request_error": e.get("id")})
        elif t == "agent.tool_result" and e.get("is_error"):
            pass
    status = next((e.get("stop_reason") for e in reversed(events) if e.get("type") == "session.status_idle"), None)
    return {"n_events": len(events), "tool_calls": len(tool_calls), "tool_errors": sum(1 for c in tool_calls if c["is_error"]),
            "errors": errors, "usage": usage, "steps": steps, "last_stop_reason": status,
            "final_message": messages[-1]["text"] if messages else None, "tools": tool_calls}


def print_summary(s: dict, full=False):
    print(f"events={s['n_events']} tool_calls={s['tool_calls']} tool_errors={s['tool_errors']} "
          f"usage={s['usage']} stop={s['last_stop_reason']}")
    for c in s["tools"] if full else s["tools"][-15:]:
        flag = "ERR " if c["is_error"] else "ok  "
        print(f"  {flag}{c['name']:<10} {c['input'][:110]}")
    if s["steps"]:
        print("steps:")
        for st in s["steps"]:
            print(f"  STEP {st['n']}/{st['of']} {st['name']} - {st['status']}")
    if s["errors"]:
        print("errors:", json.dumps(s["errors"])[:1000])
    print("final message:\n" + (s["final_message"] or "(none)"))


def save_events(session_id: str, events: list[dict], extra: dict | None = None) -> Path:
    runs = REPO / "runs"
    runs.mkdir(exist_ok=True)
    path = runs / f"{session_id}.json"
    data = {"session_id": session_id, "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "events": events}
    if extra:
        data.update(extra)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    return path


def live_printer(e: dict):
    t = e.get("type")
    at = (e.get("processed_at") or "")[11:19]
    if t == "agent.message":
        print(f"[{at}] agent: {text_of(e.get('content'))[:600]}")
    elif t == "agent.tool_use":
        inp = e.get("input", {})
        print(f"[{at}] tool {e.get('name')}: {str(inp.get('command') or inp.get('file_path') or inp.get('url') or json.dumps(inp))[:200]}")
    elif t == "agent.tool_result":
        txt = text_of(e.get("content"))
        print(f"[{at}]   -> {'ERROR ' if e.get('is_error') else ''}{txt[:200].replace(chr(10), ' | ')}")
    elif t in ("session.error",):
        print(f"[{at}] ERROR {json.dumps(e.get('error'))[:500]}")
    elif t in TERMINAL_EVENTS or t.startswith("session.status"):
        print(f"[{at}] {t} {json.dumps(e.get('stop_reason')) if e.get('stop_reason') else ''}")
    sys.stdout.flush()


# --------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=os.environ.get("ARK_BASE_URL", DEFAULT_BASE))
    ap.add_argument("--agent-id", help="default: $MA_AGENT_ID (required for agent, session create and run)")
    ap.add_argument("--env-id", help="default: $MA_ENV_ID (required for session create and run)")
    ap.add_argument("--vault-id", help="default: $MA_VAULT_ID (required for session create and run)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("agent", help="get | versions | set-system | set-skills")
    s.add_argument("action", choices=["get", "versions", "set-system", "set-skills", "set-model"])
    s.add_argument("--file", help="set-system: path to the system prompt (markdown/text)")
    s.add_argument("--skill", action="append", default=[], help="set-skills: skill_id[=version] (repeatable); replaces the whole list")
    s.add_argument("--model", help="set-model: model id")
    s.add_argument("--save", help="get: write the JSON here")

    s = sub.add_parser("skill", help="list | versions | create | upload")
    s.add_argument("action", choices=["list", "versions", "create", "upload"])
    s.add_argument("--skill-id")
    s.add_argument("--dir", help="skill folder containing SKILL.md")
    s.add_argument("--title")

    s = sub.add_parser("session", help="create | get | send | wait | events | files | tail | interrupt")
    s.add_argument("action", choices=["create", "get", "send", "wait", "events", "files", "tail", "interrupt", "summary"])
    s.add_argument("session_id", nargs="?")
    s.add_argument("--title")
    s.add_argument("--text")
    s.add_argument("--file", help="send: read the message from this file")
    s.add_argument("--system", help="send: optional system.message appended after the user message")
    s.add_argument("--wait", action="store_true", help="send: poll until idle and print the summary")
    s.add_argument("--timeout", type=int, default=3 * 3600)
    s.add_argument("--poll", type=int, default=6)
    s.add_argument("--download", help="files: destination directory")
    s.add_argument("--pattern", help="files: only names matching this regex")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--full", action="store_true", help="summary: list every tool call")

    s = sub.add_parser("run", help="create a session, send a prompt, wait, save runs/<id>.json, download outputs")
    s.add_argument("--prompt-file", required=True)
    s.add_argument("--title")
    s.add_argument("--download", help="destination dir for the session's output files")
    s.add_argument("--timeout", type=int, default=3 * 3600)
    s.add_argument("--poll", type=int, default=6)
    s.add_argument("--quiet", action="store_true")

    a = ap.parse_args(argv)
    c = Client(a.base_url)

    try:
        if a.cmd == "agent":
            if a.action == "get":
                d = c.get_agent(a.agent_id)
                if a.save:
                    Path(a.save).write_text(json.dumps(d, indent=1, ensure_ascii=False))
                    print(f"saved {a.save} (version {d['version']})")
                else:
                    print(json.dumps(d, indent=1, ensure_ascii=False))
            elif a.action == "versions":
                for v in c.agent_versions(a.agent_id).get("data", []):
                    print(v.get("version"), v.get("updated_at"),
                          [(sk.get("display_name"), sk.get("version")) for sk in v.get("skills", [])])
            elif a.action == "set-system":
                text = Path(a.file).read_text()
                d = c.update_agent(a.agent_id, system=text)
                print(f"agent {d['id']} now version {d['version']} (system prompt {len(text)} chars)")
            elif a.action == "set-skills":
                skills = []
                for item in a.skill:
                    sid, _, ver = item.partition("=")
                    entry = {"type": "custom", "skill_id": sid}
                    if ver:
                        entry["version"] = ver
                    skills.append(entry)
                d = c.update_agent(a.agent_id, skills=skills)
                print(f"agent {d['id']} now version {d['version']}; skills:",
                      [(sk.get("display_name"), sk.get("version")) for sk in d.get("skills", [])])
            elif a.action == "set-model":
                d = c.update_agent(a.agent_id, model={"id": a.model})
                print(f"agent {d['id']} now version {d['version']} model {d.get('model')}")

        elif a.cmd == "skill":
            if a.action == "list":
                for sk in c.list_skills().get("data", []):
                    print(sk["id"], f"v{sk.get('latest_version')}", sk.get("name"), "|", sk.get("display_title"))
            elif a.action == "versions":
                for v in c.skill_versions(a.skill_id).get("data", []):
                    print(v.get("version"), v.get("id"), v.get("created_at"))
            elif a.action == "create":
                d = c.create_skill(Path(a.dir), a.title)
                print(json.dumps(d, indent=1))
            elif a.action == "upload":
                d = c.create_skill_version(a.skill_id, Path(a.dir), a.title)
                print(json.dumps(d, indent=1))

        elif a.cmd == "session":
            if a.action == "create":
                d = c.create_session(a.agent_id, a.env_id, [a.vault_id], title=a.title)
                print(d["id"])
            elif a.action == "get":
                d = c.get_session(a.session_id)
                d.get("agent", {}).pop("system", None)
                print(json.dumps(d, indent=1))
            elif a.action == "send":
                text = Path(a.file).read_text() if a.file else a.text
                if not text:
                    sys.exit("--text or --file required")
                since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2))
                d = c.send_message(a.session_id, text, a.system)
                print("accepted:", [e.get("id") for e in d.get("data", [])])
                if a.wait:
                    events = c.wait_idle(a.session_id, poll=a.poll, timeout=a.timeout,
                                         on_event=None if a.quiet else live_printer, since=since)
                    all_ev = c.all_events(a.session_id)
                    path = save_events(a.session_id, all_ev)
                    print(f"saved {path}")
                    print_summary(summarize(events))
            elif a.action == "wait":
                events = c.wait_idle(a.session_id, poll=a.poll, timeout=a.timeout,
                                     on_event=None if a.quiet else live_printer)
                all_ev = c.all_events(a.session_id)
                path = save_events(a.session_id, all_ev, {"summary": {k: v for k, v in summarize(all_ev).items() if k != "tools"}})
                print(f"saved {path}")
                print_summary(summarize(events))
                if a.download:
                    for name, fid, size in c.download_session_files(a.session_id, Path(a.download), a.pattern):
                        print(f"downloaded {name} ({size})")
            elif a.action in ("events", "summary"):
                events = c.all_events(a.session_id)
                path = save_events(a.session_id, events)
                print(f"saved {path} ({len(events)} events)")
                print_summary(summarize(events), full=a.full)
            elif a.action == "files":
                if a.download:
                    for name, fid, size in c.download_session_files(a.session_id, Path(a.download), a.pattern):
                        print(f"{name}  {fid}  {size}")
                else:
                    for f in c.session_files(a.session_id):
                        print(f["id"], f.get("filename"), f.get("bytes"), f.get("status"), f.get("created_at"))
            elif a.action == "tail":
                for e in c.stream_events(a.session_id):
                    live_printer(e)
                    if e.get("type") in TERMINAL_EVENTS:
                        break
            elif a.action == "interrupt":
                print(c.interrupt(a.session_id))

        elif a.cmd == "run":
            text = Path(a.prompt_file).read_text()
            title = a.title or Path(a.prompt_file).stem
            d = c.create_session(a.agent_id, a.env_id, [a.vault_id], title=title)
            sid = d["id"]
            print(f"session {sid} ({title})")
            t0 = time.time()
            since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0 - 2))
            c.send_message(sid, text)
            events = c.wait_idle(sid, poll=a.poll, timeout=a.timeout,
                                 on_event=None if a.quiet else live_printer, since=since)
            all_ev = c.all_events(sid)
            summary = summarize(events)
            summary.pop("tools")
            path = save_events(sid, all_ev, {"title": title, "prompt_file": a.prompt_file,
                                            "elapsed_s": round(time.time() - t0), "summary": summary})
            print(f"saved {path}; elapsed {round(time.time() - t0)}s")
            print_summary(summarize(events))
            if a.download:
                for name, fid, size in c.download_session_files(sid, Path(a.download)):
                    print(f"downloaded {name} ({size})")
    except ApiError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(2)
    except MissingSetting as e:
        print(f"Setup: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
