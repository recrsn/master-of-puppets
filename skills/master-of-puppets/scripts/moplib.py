"""Shared state for the master-of-puppets helpers coordinator.py and puppet.py.

Both CLIs import this module. It holds the state paths, JSON I/O, the state lock,
the event log and ledger, machine and project config, the roster, the lease state
and memory budget, direct message delivery to Claude and Codex sessions, and the
read-only commands both CLIs offer (roster, whoami, memory list).

State lives in $MACHINE_LEASE_DIR (default ~/.local/state/machine-leases), not beside
these files, so every session that runs any copy shares one state.
"""
import datetime as dt
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import uuid

DIR = os.path.expanduser(os.environ.get("MACHINE_LEASE_DIR") or "~/.local/state/machine-leases")
STATE = os.path.join(DIR, "leases.json")
CONFIG = os.path.join(DIR, "config.json")
PROJECTS = os.path.join(DIR, "projects")
ROSTER = os.path.join(DIR, "roster.json")
LEDGER = os.path.join(DIR, "ledger.jsonl")
LIVE_MINUTES = 40
TOOLS = ("claude", "codex")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
PEAKS = os.path.join(DIR, "peaks")
LOCK = os.path.join(DIR, "lock")
LOG = os.path.join(DIR, "events.log")
INBOX = os.path.join(DIR, "inbox.jsonl")
CLASS_NAME = re.compile(r"^[A-Z][A-Z0-9_-]{0,23}$")
DEFAULT_REGISTRY = {
    "BUILD": {"description": "builds, typecheck, lint/format, tests, codegen", "defaultGiB": 10, "maxMinutes": 20, "settle": {}},
    "E2E": {"description": "local servers/stacks and interacting with them", "defaultGiB": 8, "maxMinutes": 45, "settle": {"BUILD": 60}},
}
MACHINE_DEFAULTS = {
    "reserveGiB": 6,
    "diskFloorGiB": 4,
    "maxSwapouts": 200,
    "swapIntervalS": 12,
    "loadPerCore": 2.5,
    "dashboardPort": 4720,
    "maxSlots": {},
}
PROJECT_DEFAULTS = {"baseBranch": "main", "mergeMethod": "squash", "leasesDefault": "off"}
SAMPLES_KEPT = 5
SAMPLES_TRUSTED = 3
MINUTES_KEPT = 10
MEMORY = os.path.join(DIR, "memory")


# ---------------------------------------------------------------- files and config


def read_json(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def load_machine():
    raw = read_json(CONFIG) or {}
    cfg = {**MACHINE_DEFAULTS, **raw}
    cfg["configured"] = bool(raw.get("configured"))
    return cfg


def registry(machine=None):
    """Lease classes: config.json "classes", else the default BUILD and E2E."""
    machine = machine or load_machine()
    return machine.get("classes") or json.loads(json.dumps(DEFAULT_REGISTRY))


def class_names(machine=None):
    return list(registry(machine))


def project_class_defaults(cls):
    reg = registry().get(cls, {})
    return {"maxMinutes": reg.get("maxMinutes", 20), "minutesMode": "fixed", "peakMode": "learn", "defaultGiB": reg.get("defaultGiB", 0)}


def project_key(root):
    """Slug of the main checkout plus a short hash, shared by every worktree of a repository."""
    root = os.path.abspath(os.path.expanduser(root))
    out = subprocess.run(["git", "-C", root, "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    base = root
    if out.returncode == 0 and out.stdout.strip():
        common = os.path.normpath(os.path.join(root, out.stdout.strip()))
        base = os.path.dirname(common) if os.path.basename(common) == ".git" else common
    slug = re.sub(r"[^a-z0-9]+", "-", os.path.basename(base).lower()).strip("-") or "project"
    return f"{slug}-{hashlib.sha256(base.encode()).hexdigest()[:6]}", base


def load_project(key, root=None):
    raw = read_json(os.path.join(PROJECTS, f"{key}.json")) or {}
    proj = {**PROJECT_DEFAULTS, "key": key, "root": root, **raw}
    proj["configured"] = bool(raw.get("configured"))
    stored = proj.get("classes", {})
    proj["classes"] = {c: {**project_class_defaults(c), "samples": [], "runMinutes": [], **stored.get(c, {})} for c in class_names()}
    return proj


def save_project(proj):
    write_json(os.path.join(PROJECTS, f"{proj['key']}.json"), proj)


def class_peak(proj, cls):
    """learn: max of the last 5 samples, the default a floor until 3 exist. fixed: the default."""
    c = proj["classes"][cls] if proj else project_class_defaults(cls)
    samples = c.get("samples", [])
    if c.get("peakMode") == "fixed":
        return c["defaultGiB"]
    if len(samples) >= SAMPLES_TRUSTED:
        return max(samples)
    return max([c["defaultGiB"], *samples])


def typical_minutes(proj, cls):
    """Median of recorded run minutes, once 3 exist; else None."""
    runs = sorted((proj["classes"][cls] if proj else {}).get("runMinutes", []))
    return runs[len(runs) // 2] if len(runs) >= SAMPLES_TRUSTED else None


def max_minutes(proj, cls):
    """learn: p90 of the last 10 runs plus 25%, at least 5, at most the configured maximum.
    fixed (or fewer than 3 runs): the configured maximum."""
    c = proj["classes"][cls] if proj else project_class_defaults(cls)
    runs = sorted(c.get("runMinutes", []))
    if c.get("minutesMode") != "learn" or len(runs) < SAMPLES_TRUSTED:
        return c["maxMinutes"]
    p90 = runs[max(0, -(-9 * len(runs) // 10) - 1)]
    return int(min(c["maxMinutes"], max(5, -(-p90 * 1.25 // 1))))


# ---------------------------------------------------------------- state, ledger and roster


def now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def lock():
    deadline = time.time() + 30
    while True:
        try:
            os.mkdir(LOCK)
            return
        except FileExistsError:
            if time.time() - os.path.getmtime(LOCK) > 60:
                os.rmdir(LOCK)
                continue
            if time.time() > deadline:
                sys.exit("state lock busy for 30 s")
            time.sleep(0.2)


def unlock():
    os.rmdir(LOCK)


def log(line):
    with open(LOG, "a") as f:
        f.write(f"{now().isoformat()} {line}\n")


def note(by, text, pr=None):
    rec = {"at": now().isoformat(), "by": by, "text": text}
    if pr:
        rec["pr"] = pr
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec) + "\n")


def load_roster():
    roster = json.load(open(ROSTER)) if os.path.exists(ROSTER) else {}
    roster.setdefault("leases", "off")
    roster.setdefault("coordinators", {})
    roster.setdefault("members", {})
    roster.setdefault("streams", {})
    return roster


def save_roster(roster):
    tmp = ROSTER + ".tmp"
    with open(tmp, "w") as f:
        json.dump(roster, f, indent=1)
    os.replace(tmp, ROSTER)


def live(coord):
    if not coord:
        return False
    age = now() - dt.datetime.fromisoformat(coord["heartbeat"])
    return age < dt.timedelta(minutes=LIVE_MINUTES)


def find_session(roster, session_id):
    for name, c in roster["coordinators"].items():
        if c.get("sessionId") == session_id:
            return {"role": "coordinator", "coordinator": name, "name": name, "live": live(c)}
    for coord, members in roster["members"].items():
        for m in members:
            if m.get("sessionId") == session_id:
                return {"role": "member", "coordinator": coord, "name": m["name"], "live": live(roster["coordinators"].get(coord))}
    return None


# ---------------------------------------------------------------- lease state and budget


def load():
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    queue = state.setdefault("queue", {})
    for c in class_names():
        state.setdefault(c, [])
        queue.setdefault(c, [])
    return state


def save(state, machine):
    state["budget"] = budget(state, machine)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE)


def total_gib():
    out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip()
    if out.isdigit():
        return int(out) / 2**30
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30


def known_projects():
    try:
        names = sorted(n[:-5] for n in os.listdir(PROJECTS) if n.endswith(".json"))
    except OSError:
        names = []
    return [load_project(n) for n in names]


def fleet_peak(cls):
    """Largest class peak over known projects, for the capacity display."""
    peaks = [class_peak(p, cls) for p in known_projects()]
    return max(peaks) if peaks else project_class_defaults(cls)["defaultGiB"]


def budget(state, machine):
    """Memory budget, plus per-class capacity = holders + how many more of that class fit now."""
    total = total_gib()
    limit = total - machine["reserveGiB"]
    names = class_names(machine)
    peaks = {c: fleet_peak(c) for c in names}
    held = sum(h["gib"] for c in names for h in state[c])
    free = limit - held
    capacity = {}
    for c in names:
        cap = machine["maxSlots"].get(c)
        if peaks[c] > 0:
            n = len(state[c]) + max(0, int(free // peaks[c]))
            capacity[c] = min(n, cap) if cap else n
        else:
            capacity[c] = cap  # None: not memory-bound and uncapped
    return {
        "totalGiB": round(total, 1),
        "reserveGiB": machine["reserveGiB"],
        "limitGiB": round(limit, 1),
        "heldGiB": round(held, 1),
        "freeGiB": round(free, 1),
        "peakGiB": peaks,
        "capacity": capacity,
    }


# ---------------------------------------------------------------- delivery


def say(sender, message, to=None):
    rec = {"at": now().isoformat(), "from": sender, "message": message}
    if to:
        rec["to"] = to
    with open(INBOX, "a") as f:
        f.write(json.dumps(rec) + "\n")


def claude_socket(session_id):
    """Inbox socket of a live Claude Code session, via `claude agents --json` (pid) and the
    socket directories Claude Code uses. None when the session is not running."""
    try:
        agents = json.loads(subprocess.run(["claude", "agents", "--json"], capture_output=True, text=True, timeout=20).stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    pid = next((a.get("pid") for a in agents if a.get("sessionId") == session_id), None)
    if not pid:
        return None
    bases = [os.environ.get("XDG_RUNTIME_DIR"), os.environ.get("CLAUDE_CODE_TMPDIR"), "/tmp", tempfile.gettempdir()]
    paths = [os.path.join(b, "cc-socks", f"{pid}.sock") for b in bases if b] + [f"/tmp/cc-socks-{os.getuid()}/{pid}.sock"]
    return next((p for p in paths if os.path.exists(p)), None)


def send_claude(session_id, text):
    """Write one user frame to the session's inbox socket. Protocol (reverse-engineered, not
    an Anthropic interface): https://github.com/PeterSR/claude-code-socket-transport#the-protocol
    Auth: only when posting to this process's own session (its exported socket and
    CLAUDE_CODE_MESSAGING_TOKEN). Another session's key file is never read: the receiver
    applies its normal inbound controls, so a session that bypasses permission prompts
    holds the message for the user's approval. session_id must be the receiver's current
    id; a /clear mints a new one, so the member must send JOIN again after it."""
    path = claude_socket(session_id)
    if not path:
        return "claude: session not running (inbox only)"
    frame = {"msgV": 1, "msg_id": str(uuid.uuid4()), "type": "user",
             "message": {"role": "user", "content": text}, "priority": "next", "session_id": session_id}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(path)
            own = os.environ.get("CLAUDE_CODE_MESSAGING_SOCKET")
            token = os.environ.get("CLAUDE_CODE_MESSAGING_TOKEN")
            if own and token and os.path.realpath(own) == os.path.realpath(path):
                sock.sendall((json.dumps({"type": "auth", "token": token}) + "\n").encode())
            sock.sendall((json.dumps(frame) + "\n").encode())
            sock.shutdown(socket.SHUT_WR)
    except OSError as exc:
        return f"claude: socket {path} failed: {exc} (inbox only)"
    return f"claude: written to {path} (the receiver may hold it for approval)"


def send_codex(thread_id, text):
    try:
        r = subprocess.run(["codex", "queue", "--thread", thread_id, "--message", text], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"codex: queue failed: {exc} (inbox only)"
    if r.returncode != 0:
        return f"codex: queue failed: {(r.stderr or r.stdout).strip()[:200]} (inbox only)"
    return f"codex: queued to thread {thread_id}"


def deliver(name, tool, session_id, text):
    if not session_id:
        return f"{name}: no session id (inbox only)"
    return f"{name}: {send_codex(session_id, text) if tool == 'codex' else send_claude(session_id, text)}"


def notify(to, message):
    """Tell coordinator `to` about a dashboard action: an inbox record from "dashboard", then direct delivery."""
    say("dashboard", message, to)
    c = load_roster()["coordinators"].get(to)
    if not c:
        return f"{to}: not a registered coordinator (inbox only)"
    return deliver(to, c.get("tool"), c.get("sessionId"), f"[dashboard] {message}")


# ---------------------------------------------------------------- read commands (coordinator.py and puppet.py)


READS = ("roster", "whoami", "memory")


def memory_path(project_root=None):
    name = project_key(project_root)[0] if project_root else "machine"
    return os.path.join(MEMORY, f"{name}.json"), name


def add_read_commands(sub, memory=None):
    """roster, whoami and memory list. Both CLIs offer them; coordinator.py passes its
    memory subparsers so add and remove sit beside list."""
    sub.add_parser("roster")
    wh = sub.add_parser("whoami")
    wh.add_argument("--session-id", required=True)
    if memory is None:
        memory = sub.add_parser("memory").add_subparsers(dest="mcmd", required=True)
    ml = memory.add_parser("list")
    ml.add_argument("--project-root")
    ml.add_argument("--json", action="store_true")


def read_cmd(args):
    """Read-only, so no lock."""
    roster = load_roster()
    if args.cmd == "whoami":
        me = find_session(roster, args.session_id)
        print(json.dumps(me or {"role": "none"}))
        return 0 if me else 3
    if args.cmd == "roster":
        for c in roster["coordinators"].values():
            c["live"] = live(c)
        print(json.dumps(roster, indent=1))
        return 0
    scopes = [memory_path()] + ([memory_path(args.project_root)] if args.project_root else [])
    out = {name: (read_json(path) or {}).get("entries", []) for path, name in scopes}
    if args.json:
        print(json.dumps(out, indent=1))
        return 0
    for name, entries in out.items():
        print(f"{'Machine' if name == 'machine' else 'Project ' + name}:")
        for x in entries:
            print(f"  - [{x['kind']}] {x['text']}  ({x['id']}, {x['by']}, {x['at'][:10]})")
        if not entries:
            print("  (none)")
    return 0
