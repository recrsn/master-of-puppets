#!/usr/bin/env python3
"""Shared coordination state for master-of-puppets: roster, ledger, inbox and leases.

Lease classes are a registry in config.json: any shared action that sessions must
take turns on (builds, local stacks, one browser window, a shared tunnel, a test
database, a device). Leases are optional and machine-wide. Default registry:
  BUILD: builds (incl. setup scripts that build), typecheck, lint/format, test runs, codegen.
  E2E:   starting local servers/stacks and interacting with them.
Each class has a description, defaultGiB (0 = not memory-bound; then only maxSlots
limits it), maxMinutes and settle {OTHER: seconds} (after a grant of this class,
OTHER waits that long; E2E settles BUILD for 60 s by default). Names are upper-case.
No lease: a plain dependency install, source edits, reading code, browser-only work
against remote sites (unless a class or a project rule in `memory` covers it).
Use it or return it: a lease covers the granted commands and their resource cleanup.
No edits or repairs while holding one. When a check fails, clean up owned resources
(stop owned E2E servers), release promptly with the failure, repair without a lease,
then join the queue again at the back.

Capacity is adaptive. There is no fixed slot count. A grant is admitted when the
expected peak memory of all holders plus the request fits in the memory budget:
  sum(held GiB) + request GiB <= total RAM - reserve
A request's GiB defaults to its project's class peak. In learn mode that is the max
of the last 5 measured peaks (`measure-peak` writes peaks/<id>.gib; release
records it), with the default as a floor until 3 samples exist; in fixed mode it is
the default. Example: on a 24 GiB machine with a 6 GiB reserve, BUILD ~10 GiB and
E2E ~8 GiB admit one of each; 64 GiB admits more. A 0 GiB class uses no budget. Swap, load and disk are a
separate gate (`host-check`), run before every acquire.

Configuration (asked once through the skill's first-run setup):
  machine  $DIR/config.json             reserveGiB, diskFloorGiB, maxSwapouts, swapIntervalS,
                                        loadPerCore, dashboardPort, maxSlots, classes
  project  $DIR/projects/<key>.json     root, baseBranch, mergeMethod, leasesDefault and per
                                        class maxMinutes, peakMode (learn|fixed), defaultGiB, samples
The project key comes from the repository's git common dir, so all worktrees of one
repository share a file; nothing is written into the repository.

Admission is strict FIFO per class across coordinators: only the first ready
entry may acquire. An expired lease (past expiresAt) still holds its memory: its
holder releases it; a coordinator needs the user's approval for a takeover.

State lives in $MACHINE_LEASE_DIR (default ~/.local/state/machine-leases), not beside
this file, so every coordinator that runs any copy shares one state.

Usage: python3 -I lease.py <command> ...   (the skill's other file is server.py)

Leases (coordinators)
  status [--brief] | capacity
  wait CLASS --coordinator C --holder NAME --id ID [--minutes N] [--gib N] [--commands TEXT] [--worktree P] [--front]
       for an existing ID every flag is optional and only the given fields change
  acquire CLASS --coordinator C --holder NAME --id ID --worktree P --minutes N [--gib N]
          [--commands TEXT] [--measure]
       exit 0 granted, 3 queued behind another entry, at a slot cap or in a settle window
       (another class's grant settles this one), 4 over the memory budget.
       --commands records the granted scope; --measure starts measure-peak itself.
  release CLASS --id ID [--peak-gib N] | unwait | hold | ready CLASS --id ID
  extend CLASS --id ID --minutes N
  host-check                      admission gate; exit 0 CALM, 1 BUSY; prints disk_low=yes|no
  measure-peak --id ID --worktree P [--interval S]   run in the background after acquire
  drain-check --worktree P [--port N ...] [--process PATTERN ...]   exit 0 when nothing is left; never kills
  config show [--project-root P] | set-machine ... | set-project --root P ... | project-key P
       machine: --reserve-gib --disk-floor-gib --max-swapouts --swap-interval-s --load-per-core
                --dashboard-port --max-slots CLASS=N (N=0 removes the cap)
  config set-class NAME [--description T] [--default-gib N] [--max-minutes N] [--settle OTHER=S ...]
  config remove-class NAME        refused while the class has holders or queue entries
       project: --name --base-branch --merge-method merge|squash|rebase|auto --leases-default
                [--class CLASS --max-minutes N --minutes learn|fixed --peak learn|fixed --default-gib N]
       release records run minutes; with --minutes learn the limit is p90 of the last 10
       runs + 25% (at least 5, at most --max-minutes); config show prints maxMinutesEffective.

Roster and members (coordinators write; members send messages and release their own leases)
  roster | whoami --session-id ID
  coordinate --name C --tool claude|codex --session-id ID --focus TEXT [--pr N ...] [--takeover]
  heartbeat --name C [--focus TEXT] [--pr N ...] | resign --name C
  leases on|off --by C            machine-wide; only on the user's word
  enroll --coordinator C --task TEXT [--by MEMBER] [--name NAME] [--pr N ...]
       registers a task before it starts and prints the kickoff line for its prompt
  member add|update --coordinator C --name NAME [--tool] [--session-id] [--worktree] [--task]
       [--pr N ...] [--repo owner/repo] [--status] [--phase] [--kind] [--latest] [--session URL]
       updates the roster and the member's row in dashboard/<C>-state.json
  member remove --coordinator C --name NAME
  member stale --coordinator C [--minutes 30]   members (not done) with no update for N minutes
  decision add --by C --text TEXT [--task ID] [--href URL] | decision clear --by C (--task ID | --all)
  note --by C --text TEXT [--pr N]   shared ledger

Memory (the skill's own memory; coordinators write it, everyone reads it)
  memory add --by NAME --text TEXT [--kind rule|lesson|note] [--project-root P]
  memory list [--project-root P] [--json]      machine entries, then the project's
  memory remove --id ID [--project-root P]
       Machine scope: memory/machine.json. Project scope (with --project-root):
       memory/<project-key>.json, shared by every worktree of the repository.
       Project-specific rules (for example which git hooks need a lease) live here,
       not in the skill text.

Peer-coordinator messaging
  say --from NAME --message TEXT [--to NAME] [--no-direct]
       appends to inbox.jsonl, then delivers directly: a Claude session through its inbox
       socket (protocol: github.com/PeterSR/claude-code-socket-transport, reverse-engineered,
       not an Anthropic interface), a Codex thread through `codex queue`. --to names a
       registered coordinator; without it, every live peer coordinator. Only registered
       coordinators use say. A receiver that bypasses
       permission prompts holds a socket message for the user's approval.

Waiters (authorized sessions)
  await-grant CLASS --id ID [--timeout-min N] [--appear-timeout S]
       prints GRANTED or NOT-GRANTED <reason>. Exit 0 granted (the only grant);
       3 left the queue without a grant; 5 timeout while still queued; 6 never queued
       within --appear-timeout (default 600 s), so a member may start before the
       coordinator queues the ID it proposed
  calm-wait [--settle S] [--retry S]           one CALM line when the host is calm
  watch inbox --me C | watch expiry | watch prs --me C [--interval S]   Monitor sources
  install                                     copy this file into the state dir if absent

A coordinator is live while its heartbeat is newer than 40 minutes. coordinate and
heartbeat exit 3 when a PR is owned by another live coordinator; enroll and member
exit 3 when the coordinator is not live.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import uuid
import sys
import time

DIR = os.path.expanduser(os.environ.get("MACHINE_LEASE_DIR") or "~/.local/state/machine-leases")
os.makedirs(DIR, exist_ok=True)
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


def total_gib():
    out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip()
    if out.isdigit():
        return int(out) / 2**30
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30


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


def known_projects():
    try:
        names = sorted(n[:-5] for n in os.listdir(PROJECTS) if n.endswith(".json"))
    except OSError:
        names = []
    return [load_project(n) for n in names]


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


def config_cmd(args):
    machine = load_machine()
    if args.ccmd == "project-key":
        key, base = project_key(args.path)
        print(json.dumps({"key": key, "root": base}))
        return 0
    if args.ccmd == "set-machine":
        raw = read_json(CONFIG) or {}
        for flag, field in (("reserve_gib", "reserveGiB"), ("disk_floor_gib", "diskFloorGiB"), ("max_swapouts", "maxSwapouts"),
                            ("swap_interval_s", "swapIntervalS"), ("load_per_core", "loadPerCore"), ("dashboard_port", "dashboardPort")):
            if getattr(args, flag) is not None:
                raw[field] = getattr(args, flag)
        for item in args.max_slots or []:
            cls, _, n = item.partition("=")
            slots = raw.setdefault("maxSlots", {})
            if cls not in registry() or not n.isdigit():
                print(f"--max-slots wants CLASS=N, got {item}")
                return 2
            if int(n):
                slots[cls] = int(n)
            else:
                slots.pop(cls, None)
        raw["configured"] = True
        raw["updatedAt"] = now().isoformat()
        write_json(CONFIG, raw)
        log(f"config machine {json.dumps(raw)}")
        print(json.dumps(load_machine(), indent=1))
        return 0
    if args.ccmd in ("set-class", "remove-class"):
        if not CLASS_NAME.match(args.name):
            print("class names are upper-case, for example BROWSER or TEST-DB")
            return 2
        raw = read_json(CONFIG) or {}
        reg = raw.setdefault("classes", registry())
        if args.ccmd == "remove-class":
            state = load()
            if state.get(args.name) or state["queue"].get(args.name):
                print(f"{args.name} has holders or queue entries; release or unwait them first")
                return 3
            reg.pop(args.name, None)
            for other in reg.values():
                other.get("settle", {}).pop(args.name, None)
            raw.get("maxSlots", {}).pop(args.name, None)
        else:
            c = reg.setdefault(args.name, {"description": "", "defaultGiB": 0, "maxMinutes": 20, "settle": {}})
            for flag, field in (("description", "description"), ("default_gib", "defaultGiB"), ("max_minutes", "maxMinutes")):
                if getattr(args, flag) is not None:
                    c[field] = getattr(args, flag)
            for item in args.settle or []:
                other, _, secs = item.partition("=")
                if not secs.isdigit():
                    print(f"--settle wants OTHER=SECONDS, got {item}")
                    return 2
                if int(secs):
                    c.setdefault("settle", {})[other] = int(secs)
                else:
                    c.setdefault("settle", {}).pop(other, None)
        raw["updatedAt"] = now().isoformat()
        write_json(CONFIG, raw)
        log(f"config class {args.ccmd} {args.name}")
        print(json.dumps(reg, indent=1))
        return 0
    if args.ccmd == "set-project":
        key, base = project_key(args.root)
        proj = load_project(key, base)
        proj["root"] = base
        for flag, field in (("name", "name"), ("base_branch", "baseBranch"), ("merge_method", "mergeMethod"), ("leases_default", "leasesDefault")):
            if getattr(args, flag) is not None:
                proj[field] = getattr(args, flag)
        if args.pcls:
            c = proj["classes"][args.pcls]
            for flag, field in (("max_minutes", "maxMinutes"), ("minutes", "minutesMode"), ("peak", "peakMode"), ("default_gib", "defaultGiB")):
                if getattr(args, flag) is not None:
                    c[field] = getattr(args, flag)
        proj["configured"] = True
        proj["updatedAt"] = now().isoformat()
        save_project(proj)
        log(f"config project {key}")
        print(json.dumps(proj, indent=1))
        return 0
    out = {"machine": machine}
    missing = [] if machine["configured"] else ["machine"]
    if args.project_root:
        key, base = project_key(args.project_root)
        proj = load_project(key, base)
        for c in class_names():
            proj["classes"][c]["peakGiB"] = class_peak(proj, c)
            proj["classes"][c]["maxMinutesEffective"] = max_minutes(proj, c)
            proj["classes"][c]["typicalMinutes"] = typical_minutes(proj, c)
        out["project"] = proj
        if not proj["configured"]:
            missing.append("project")
    out["unconfigured"] = missing
    print(json.dumps(out, indent=1))
    return 3 if missing else 0


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
                sys.exit("lease lock busy for 30 s")
            time.sleep(0.2)


def unlock():
    os.rmdir(LOCK)


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


def log(line):
    with open(LOG, "a") as f:
        f.write(f"{now().isoformat()} {line}\n")


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
    r = subprocess.run(["codex", "queue", "--thread", thread_id, "--message", text], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return f"codex: queue failed: {(r.stderr or r.stdout).strip()[:200]} (inbox only)"
    return f"codex: queued to thread {thread_id}"


def say_cmd(args):
    """Append to inbox.jsonl (the record every coordinator watches), then deliver directly:
    Peer Claude coordinators through their inbox socket, Codex through `codex queue`."""
    roster = load_roster()
    coords = roster["coordinators"]
    if args.sender not in coords or (args.to and args.to not in coords):
        print("say is coordinator-to-coordinator only; use native direct messaging for members")
        return 2
    say(args.sender, args.message, args.to)
    print("inbox: appended")
    if args.no_direct:
        return 0
    targets = []
    if args.to:
        c = roster["coordinators"].get(args.to)
        if c:
            targets.append((args.to, c.get("tool"), c.get("sessionId")))
        if not targets:
            print(f"direct: no roster entry with a session id for {args.to} (inbox only)")
    else:
        targets = [(n, c.get("tool"), c.get("sessionId")) for n, c in roster["coordinators"].items() if n != args.sender and live(c)]
    text = f"[{args.sender} via lease.py say] {args.message}"
    for name, tool, sid in targets:
        if not sid:
            print(f"{name}: no session id (inbox only)")
        elif tool == "codex":
            print(f"{name}: {send_codex(sid, text)}")
        else:
            print(f"{name}: {send_claude(sid, text)}")
    return 0


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


def pr_conflicts(roster, name, prs):
    """PRs in prs already owned by another live coordinator."""
    return {
        n: other
        for other, c in roster["coordinators"].items()
        if other != name and live(c)
        for n in c.get("prs", [])
        if n in prs
    }


KICKOFF_MARK = "MASTER-OF-PUPPETS ENROLLED"


def kickoff_line(coord, name, parent):
    by = f", started by {parent}" if parent and parent != coord else ""
    return (
        f"{KICKOFF_MARK} — {coord} has enrolled you as member {name}{by}. "
        f"First action: run /puppet and send {coord} your JOIN message as {name}; "
        f"then follow {coord}'s directions."
    )


def find_session(roster, session_id):
    for name, c in roster["coordinators"].items():
        if c.get("sessionId") == session_id:
            return {"role": "coordinator", "coordinator": name, "name": name, "live": live(c)}
    for coord, members in roster["members"].items():
        for m in members:
            if m.get("sessionId") == session_id:
                return {"role": "member", "coordinator": coord, "name": m["name"], "live": live(roster["coordinators"].get(coord))}
    return None


def roster_cmd(args):
    roster = load_roster()
    coords = roster["coordinators"]
    if args.cmd == "whoami":
        me = find_session(roster, args.session_id)
        print(json.dumps(me or {"role": "none"}))
        return 0 if me else 3
    if args.cmd == "roster":
        for c in coords.values():
            c["live"] = live(c)
        print(json.dumps(roster, indent=1))
        return 0
    if args.cmd == "leases":
        roster["leases"] = args.mode
        save_roster(roster)
        log(f"leases {args.mode} by={args.by}")
        note(args.by, f"leases {args.mode}")
        return 0
    if args.cmd in ("coordinate", "heartbeat", "resign"):
        cur = coords.get(args.name)
        if args.cmd == "coordinate":
            if not SLUG.match(args.name):
                print("--name must be a lowercase slug, for example claude-scope-ux")
                return 2
            if live(cur) and cur["sessionId"] != args.session_id and not args.takeover:
                print(json.dumps({"live_coordinator": {args.name: cur}}))
                return 3
            clash = pr_conflicts(roster, args.name, args.pr or [])
            if clash:
                print(json.dumps({"owned_by_other": clash}))
                return 3
            coords[args.name] = {
                "tool": args.tool,
                "sessionId": args.session_id,
                "focus": args.focus,
                "prs": args.pr or [],
                "since": now().isoformat(),
                "heartbeat": now().isoformat(),
            }
            roster["members"].setdefault(args.name, [])
            save_roster(roster)
            log(f"coordinate {args.name} tool={args.tool} focus={args.focus!r}")
            note(args.name, f"coordinates: {args.focus}")
            print(json.dumps({"coordinator": coords[args.name], "leases": roster["leases"]}, indent=1))
            return 0
        if not cur:
            print(f"no coordinator named {args.name}")
            return 3
        if args.cmd == "heartbeat":
            if args.pr is not None:
                clash = pr_conflicts(roster, args.name, args.pr)
                if clash:
                    print(json.dumps({"owned_by_other": clash}))
                    return 3
                cur["prs"] = args.pr
            if args.focus:
                cur["focus"] = args.focus
            cur["heartbeat"] = now().isoformat()
            save_roster(roster)
            return 0
        coords.pop(args.name)
        save_roster(roster)
        log(f"resign {args.name}")
        note(args.name, "resigned")
        return 0
    cur = coords.get(args.coordinator)
    members = roster["members"].setdefault(args.coordinator, [])
    if not live(cur):
        alive = {n: c["focus"] for n, c in coords.items() if live(c)}
        print(json.dumps({"no_live_coordinator": args.coordinator, "live": alive}))
        return 3
    if args.cmd == "enroll":
        name = args.name or f"{re.sub(r'[^a-z0-9]+', '-', args.task.lower()).strip('-')[:24].strip('-')}-{os.urandom(2).hex()}"
        members[:] = [m for m in members if m["name"] != name]
        members.append({
            "name": name,
            "status": "pending",
            "parent": args.by or args.coordinator,
            "task": args.task,
            "prs": args.pr or [],
            "enrolledAt": now().isoformat(),
        })
        save_roster(roster)
        upsert_task(args.coordinator, name, {"name": args.task, "phase": "Enrolled, not started", "kind": "work"})
        note(args.coordinator, f"{name} enrolled (started by {args.by or args.coordinator}): {args.task}")
        print(kickoff_line(args.coordinator, name, args.by))
        return 0
    if args.cmd == "member" and args.mcmd == "stale":
        cutoff = now() - dt.timedelta(minutes=args.minutes)
        rows = []
        for x in members:
            if x.get("status") == "done":
                continue
            last = x.get("updatedAt") or x.get("joinedAt") or x.get("enrolledAt")
            when = dt.datetime.fromisoformat(last) if last else None
            if when is None or when < cutoff:
                age = int((now() - when).total_seconds() // 60) if when else None
                rows.append(f"{x['name']} {x.get('status', 'active')} last update {age if age is not None else '?'} min ago — {x.get('task', '')[:60]}")
        print("\n".join(rows) if rows else f"no member silent for {args.minutes} min")
        return 0
    m = next((x for x in members if x["name"] == args.name), None)
    if args.cmd == "member" and args.mcmd == "remove":
        members[:] = [x for x in members if x["name"] != args.name]
        save_roster(roster)
        remove_task(args.coordinator, args.name)
        note(args.coordinator, f"{args.name} left")
        return 0
    if args.mcmd == "add":
        if m is None:
            m = {"name": args.name, "joinedAt": now().isoformat()}
            members.append(m)
        m["status"] = "active"
        m.setdefault("joinedAt", now().isoformat())
    elif m is None:
        print(f"{args.name} is not a member of {args.coordinator}")
        return 3
    for flag, field in (("tool", "tool"), ("session_id", "sessionId"), ("worktree", "worktree"), ("task", "task"), ("status", "status")):
        if getattr(args, flag, None) is not None:
            m[field] = getattr(args, flag)
    if args.pr is not None:
        m["prs"] = args.pr
    m["updatedAt"] = now().isoformat()
    save_roster(roster)
    row = {}
    for flag, field in (("task", "name"), ("phase", "phase"), ("kind", "kind"), ("latest", "latest"), ("worktree", "worktree"), ("session", "session")):
        if getattr(args, flag, None) is not None:
            row[field] = getattr(args, flag)
    if args.pr is not None and args.repo:
        row["links"] = [{"label": f"PR #{n}", "href": f"https://github.com/{args.repo}/pull/{n}"} for n in args.pr]
    if args.mcmd == "add":
        row.setdefault("phase", "Joined")
    upsert_task(args.coordinator, args.name, row)
    if args.mcmd == "add":
        note(args.coordinator, f"{args.name} joined: {m.get('task', '')} (PRs {' '.join('#' + str(n) for n in m.get('prs', [])) or 'none'})")
    return 0


def state_path(coord):
    return os.path.join(DIR, "dashboard", f"{coord}-state.json")


def upsert_task(coord, task_id, fields):
    """Create or update the dashboard row for a member in dashboard/<coord>-state.json."""
    path = state_path(coord)
    data = read_json(path) or {}
    tasks = data.setdefault("tasks", [])
    row = next((t for t in tasks if t.get("id") == task_id), None)
    if row is None:
        row = {"id": task_id}
        tasks.append(row)
    row.update({k: v for k, v in fields.items() if v is not None})
    data["updated"] = now().strftime("%H:%MZ")
    write_json(path, data)


def remove_task(coord, task_id):
    path = state_path(coord)
    data = read_json(path) or {}
    data["tasks"] = [t for t in data.get("tasks", []) if t.get("id") != task_id]
    data["updated"] = now().strftime("%H:%MZ")
    write_json(path, data)


def brief(state):
    """One line per holder and per class queue, then the budget."""
    t = now()
    lines = []
    for c in class_names():
        for h in state[c]:
            left = int((dt.datetime.fromisoformat(h["expiresAt"]) - t).total_seconds() // 60)
            status = f"EXPIRED {-left} min ago" if left < 0 else f"{left} min left"
            lines.append(f"{c} held  {h['id']} ({h['coordinator']}, {h['gib']} GiB) {status} — {h['holder'][:60]}")
            if h.get("commands"):
                lines.append(f"           covers: {h['commands'][:120]}")
        q = state["queue"][c]
        ready = [x for x in q if not x.get("hold")]
        head = f"head {ready[0]['id']} ({ready[0]['coordinator']})" if ready else "no ready entry"
        lines.append(f"{c} queue {len(ready)} ready, {len(q) - len(ready)} on hold — {head}")
    b = state["budget"]
    lines.append(f"budget {b['freeGiB']} of {b['limitGiB']} GiB free · capacity {b['capacity']} · peaks {b['peakGiB']}")
    return "\n".join(lines)


MEMORY = os.path.join(DIR, "memory")


def memory_path(project_root=None):
    name = project_key(project_root)[0] if project_root else "machine"
    return os.path.join(MEMORY, f"{name}.json"), name


def memory_cmd(args):
    if args.mcmd == "list":
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
    path, name = memory_path(args.project_root)
    lock()
    try:
        data = read_json(path) or {"entries": []}
        if args.mcmd == "add":
            entry = {"id": f"m-{os.urandom(3).hex()}", "kind": args.kind, "text": args.text, "by": args.by, "at": now().isoformat()}
            data["entries"].append(entry)
            write_json(path, data)
            log(f"memory add {name} {entry['id']} by={args.by}")
            print(entry["id"])
            return 0
        before = len(data["entries"])
        data["entries"] = [x for x in data["entries"] if x["id"] != args.id]
        if len(data["entries"]) == before:
            print(f"no memory entry {args.id} in {name}")
            return 3
        write_json(path, data)
        log(f"memory remove {name} {args.id}")
        return 0
    finally:
        unlock()


def await_grant(args):
    """Poll without the lock. A member may start before the coordinator queues the
    entry, so the ID gets --appear-timeout to show up before it is judged. Prints
    one line, GRANTED or NOT-GRANTED <reason>; only exit 0 means granted."""
    start = time.time()
    seen = False
    while True:
        state = load()
        if any(h["id"] == args.id for h in state[args.cls]):
            print(f"GRANTED {args.cls} {args.id}")
            return 0
        entry = next((q for q in state["queue"][args.cls] if q["id"] == args.id), None)
        waited = time.time() - start
        if entry is not None:
            seen = True
        elif seen:
            print(f"NOT-GRANTED {args.cls} {args.id}: left the queue without a grant; ask your coordinator")
            return 3
        elif waited >= args.appear_timeout:
            print(f"NOT-GRANTED {args.cls} {args.id}: never queued within {args.appear_timeout:g} s; check the id with your coordinator")
            return 6
        if waited >= args.timeout_min * 60:
            ready = [q["id"] for q in state["queue"][args.cls] if not q.get("hold")]
            pos = ready.index(args.id) + 1 if args.id in ready else "on hold" if entry else "not queued"
            print(f"NOT-GRANTED {args.cls} {args.id}: timeout after {args.timeout_min:g} min; position {pos}; still queued, wait again")
            return 5
        time.sleep(args.interval)


def decision_cmd(args):
    path = os.path.join(DIR, "dashboard", f"{args.by}-state.json")
    data = read_json(path) or {}
    items = data.setdefault("decisions", [])
    if args.dcmd == "add":
        item = {"text": args.text}
        if args.task:
            item["task"] = args.task
        if args.href:
            item["href"] = args.href
        items.append(item)
    else:
        if not (args.task or args.all):
            print("decision clear needs --task ID or --all")
            return 2
        data["decisions"] = [] if args.all else [d for d in items if d.get("task") != args.task]
    data["updated"] = now().strftime("%H:%MZ")
    write_json(path, data)
    print(f"{len(data['decisions'])} decisions for {args.by}")
    return 0


# ---------------------------------------------------------------- host, waiters, watchers

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def swapouts():
    m = re.search(r"Swapouts:\s+(\d+)", run(["vm_stat"]))
    return int(m.group(1)) if m else 0


def host_check(interval=None):
    """Admission gate: two swap-out samples, then load and disk. Returns (calm, line)."""
    cfg = load_machine()
    interval = interval or int(os.environ.get("INTERVAL") or cfg["swapIntervalS"])
    max_swap = int(os.environ.get("MAX_SWAPOUTS") or cfg["maxSwapouts"])
    cores = os.cpu_count() or 1
    max_load = float(os.environ.get("MAX_LOAD") or cores * float(cfg["loadPerCore"]))
    floor = float(os.environ.get("DISK_FLOOR_GIB") or cfg["diskFloorGiB"])
    calm, parts = True, []
    for i in (1, 2):
        a = swapouts()
        time.sleep(interval)
        d = swapouts() - a
        parts.append(f"sample{i} swapouts/{interval}s={d}")
        calm = calm and d < max_swap
    load1 = os.getloadavg()[0]
    calm = calm and load1 < max_load
    free = shutil.disk_usage("/").free / 2**30
    m = re.search(r"(\d+)%", run(["memory_pressure", "-Q"]))
    parts += [
        f"load1={load1:.2f}", f"max_load={max_load:g}", f"disk_free_GiB={free:.0f}", f"disk_floor_GiB={floor:g}",
        f"disk_low={'yes' if free < floor else 'no'}", f"memory_free={m.group(1) + '%' if m else '?'}",
        f"verdict={'CALM' if calm else 'BUSY'}",
    ]
    return calm, " ".join(parts)


def host_check_cmd(args):
    calm, line = host_check()
    print(line)
    return 0 if calm else 1


def calm_wait_cmd(args):
    """Block until two calm samples, print one CALM line. Run in the background."""
    if args.settle:
        time.sleep(args.settle)
    while True:
        calm, line = host_check()
        if calm:
            print(f"CALM {time.strftime('%H:%M:%SZ', time.gmtime())} {line}", flush=True)
            return 0
        time.sleep(args.retry)


def worktree_pids(tree):
    tree = os.path.realpath(tree)
    pids, pid = set(), None
    for line in run(["lsof", "-nP", "-d", "cwd", "-Fpn"]).splitlines():
        if line.startswith("p"):
            pid = line[1:]
        elif line.startswith("n") and pid:
            path = line[1:]
            if path == tree or path.startswith(tree + "/"):
                pids.add(pid)
    return sorted(pids, key=int)


def measure_peak_cmd(args):
    """While ID holds a lease, sum RSS of processes working in the worktree; keep the max
    in peaks/<id>.gib for release. RSS counts shared pages twice, so it errs high."""
    os.makedirs(PEAKS, exist_ok=True)
    out = os.path.join(PEAKS, f"{args.id}.gib")
    peak = 0.0
    time.sleep(2)
    while any(h["id"] == args.id for c in class_names() for h in load()[c]):
        pids = worktree_pids(args.worktree)
        if pids:
            kib = sum(int(x) for x in run(["ps", "-o", "rss=", "-p", ",".join(pids)]).split() if x.isdigit())
            gib = round(kib / 2**20, 1)
            if gib > peak:
                peak = gib
                with open(out, "w") as f:
                    f.write(str(peak))
        time.sleep(args.interval)
    print(f"peak {args.id} {peak} GiB")
    return 0


def drain_check_cmd(args):
    """Report what a released lease left behind: processes working in the worktree (with
    their listeners), listeners on the given ports, and processes matching each
    --process pattern (for example a tunnel or a browser started for the run).
    Exit 0 when nothing is left, 1 otherwise. It only reports; it never kills."""
    left = 0
    pids = worktree_pids(args.worktree)
    for pid in pids:
        cmd = run(["ps", "-o", "command=", "-p", pid]).strip()[:100]
        if not cmd:
            continue
        left += 1
        ports = [l[1:] for l in run(["lsof", "-nP", "-a", "-p", pid, "-iTCP", "-sTCP:LISTEN", "-Fn"]).splitlines() if l.startswith("n")]
        print(f"  worktree {pid} {'[listen ' + ' '.join(ports) + '] ' if ports else ''}{cmd}")
    for port in args.port or []:
        for line in run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"]).splitlines():
            if line.startswith("p"):
                pid = line[1:]
                left += 1
                print(f"  port {port} {pid} {run(['ps', '-o', 'command=', '-p', pid]).strip()[:100]}")
    for pattern in args.process or []:
        for line in run(["pgrep", "-fl", pattern]).splitlines():
            left += 1
            print(f"  process {pattern}: {line[:110]}")
    print(f"{'drained' if not left else 'not drained'}: {left} left for {args.worktree}")
    return 0 if not left else 1


def follow(paths):
    """Yield (path, line) for lines appended to the files after start."""
    files = {}
    for p in paths:
        open(p, "a").close()
        f = open(p)
        f.seek(0, os.SEEK_END)
        files[p] = f
    while True:
        for p, f in files.items():
            for line in f.readlines():
                if line.strip():
                    yield p, line.strip()
        time.sleep(2)


def watch_inbox(me):
    """Messages to me or to all, and other coordinators' roster and lease events."""
    for path, line in follow([INBOX, LOG]):
        if path == INBOX:
            try:
                rec = json.loads(line)
            except ValueError:
                print(f"INBOX {line}", flush=True)
                continue
            if rec.get("from") != me and rec.get("to") in (None, me):
                print(f"INBOX {rec.get('from')}: {rec.get('message')}", flush=True)
            continue
        f = line.split()
        if len(f) < 3:
            continue
        own = (
            (f[1] in ("wait", "acquire", "refuse") and len(f) > 3 and f[3] == me)
            or (f[1] in ("release", "unwait", "hold", "ready", "extend") and f[3 if len(f) > 3 else -1].startswith(me + "-"))
            or (f[1] in ("coordinate", "resign") and f[2] == me)
            or f"by={me}" in f
        )
        if not own:
            print(f"EVENT {line}", flush=True)


def watch_expiry():
    """Each lease past its expiry, once. An expired lease still holds its slot."""
    seen = set()
    while True:
        t = now()
        state = load()
        for c in class_names():
            for h in state[c]:
                key = (c, h["id"])
                if key not in seen and dt.datetime.fromisoformat(h["expiresAt"]) < t:
                    seen.add(key)
                    print(f'{c} {h["id"]} ({h["coordinator"]}) expired at {h["expiresAt"][11:16]}Z holder={h["holder"][:60]}', flush=True)
        time.sleep(60)


def watch_prs(me, interval):
    """State changes of the PRs listed in prs-<me>.txt ("owner/repo#123" per line)."""
    path = os.path.join(DIR, f"prs-{me}.txt")
    open(path, "a").close()
    last = {}
    fields = "state,baseRefName,isDraft,mergeStateStatus,autoMergeRequest,reviewDecision,mergeCommit"
    while True:
        for raw in open(path).read().splitlines():
            ref = raw.split()[0] if raw.split() else ""
            if not ref or ref.startswith("#") or "#" not in ref:
                continue
            repo, num = ref.rsplit("#", 1)
            r = subprocess.run(["gh", "pr", "view", num, "--repo", repo, "--json", fields], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if r.returncode != 0:
                line = "error " + " ".join(r.stderr.split())[:200]
            else:
                d = json.loads(r.stdout)
                sha = f" sha={d['mergeCommit']['oid'][:12]}" if d.get("mergeCommit") else ""
                line = (f"{d['state']} base={d['baseRefName']} draft={str(d['isDraft']).lower()} merge={d['mergeStateStatus']} "
                        f"automerge={'on' if d.get('autoMergeRequest') else 'off'} review={d.get('reviewDecision') or 'none'}{sha}")
            if last.get(ref) != line:
                print(f"PR {ref} {line}", flush=True)
                last[ref] = line
        time.sleep(interval)


def watch_cmd(args):
    try:
        if args.what == "inbox":
            watch_inbox(args.me)
        elif args.what == "expiry":
            watch_expiry()
        else:
            watch_prs(args.me, args.interval)
    except KeyboardInterrupt:
        return 0
    return 0


def install_cmd(args):
    """Copy this lease.py into the state dir when absent; never overwrite a different live copy."""
    dst = os.path.join(DIR, "lease.py")
    src = os.path.abspath(__file__)
    if os.path.abspath(dst) == src:
        print("this is the live copy")
        return 0
    new = open(src).read()
    if not os.path.exists(dst):
        with open(dst, "w") as f:
            f.write(new)
        print(f"installed {dst}")
        return 0
    old = open(dst).read()
    if old == new:
        print(f"up to date {dst}")
        return 0
    import difflib
    print(f"DIFFERS {dst} (not overwritten; agree the change with the other coordinators first)")
    sys.stdout.writelines(difflib.unified_diff(old.splitlines(True), new.splitlines(True), dst, src, n=1))
    return 2


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("status")
    st.add_argument("--brief", action="store_true")
    ag = sub.add_parser("await-grant")
    ag.add_argument("cls", metavar="CLASS")
    ag.add_argument("--id", required=True)
    ag.add_argument("--timeout-min", type=float, default=30)
    ag.add_argument("--appear-timeout", type=float, default=600, help="seconds the ID may take to be queued")
    ag.add_argument("--interval", type=float, default=10)
    dc = sub.add_parser("decision")
    dsub = dc.add_subparsers(dest="dcmd", required=True)
    da = dsub.add_parser("add")
    da.add_argument("--by", required=True)
    da.add_argument("--text", required=True)
    da.add_argument("--task")
    da.add_argument("--href")
    dl = dsub.add_parser("clear")
    dl.add_argument("--by", required=True)
    dl.add_argument("--task")
    dl.add_argument("--all", action="store_true")
    sub.add_parser("capacity")
    a = sub.add_parser("acquire")
    a.add_argument("cls", metavar="CLASS")
    a.add_argument("--coordinator", required=True)
    a.add_argument("--holder", required=True)
    a.add_argument("--id", required=True)
    a.add_argument("--worktree", required=True)
    a.add_argument("--minutes", type=int, required=True)
    a.add_argument("--gib", type=float, help="expected peak GiB; default: queue entry estimate, then class peak")
    a.add_argument("--commands", help="the exact granted commands; default: the queue entry's")
    a.add_argument("--measure", action="store_true", help="start measure-peak in the background for this lease")
    r = sub.add_parser("release")
    r.add_argument("cls", metavar="CLASS")
    r.add_argument("--id", required=True)
    r.add_argument("--peak-gib", type=float, help="measured peak; default: peaks/<id>.gib from measure-peak")
    w = sub.add_parser("wait")
    w.add_argument("cls", metavar="CLASS")
    w.add_argument("--coordinator", help="required for a new entry")
    w.add_argument("--holder", help="required for a new entry; an existing entry keeps its holder text unless given")
    w.add_argument("--id", required=True)
    w.add_argument("--minutes", type=int)
    w.add_argument("--gib", type=float)
    w.add_argument("--commands", help="the exact commands the lease would cover")
    w.add_argument("--worktree", help="sets the project whose class peak applies")
    w.add_argument("--front", action="store_true", help="re-queue at the head (only for a run aborted by the coordinator)")
    u = sub.add_parser("unwait")
    u.add_argument("cls", metavar="CLASS")
    u.add_argument("--id", required=True)
    x = sub.add_parser("extend")
    x.add_argument("cls", metavar="CLASS")
    x.add_argument("--id", required=True)
    x.add_argument("--minutes", type=int, required=True)
    for name in ("hold", "ready"):
        h = sub.add_parser(name)
        h.add_argument("cls", metavar="CLASS")
        h.add_argument("--id", required=True)
    cf = sub.add_parser("config")
    csub = cf.add_subparsers(dest="ccmd", required=True)
    cs = csub.add_parser("show")
    cs.add_argument("--project-root")
    cm = csub.add_parser("set-machine")
    cm.add_argument("--reserve-gib", type=float)
    cm.add_argument("--disk-floor-gib", type=float)
    cm.add_argument("--max-swapouts", type=int)
    cm.add_argument("--swap-interval-s", type=int)
    cm.add_argument("--load-per-core", type=float)
    cm.add_argument("--dashboard-port", type=int)
    cm.add_argument("--max-slots", action="append", help="CLASS=N hard cap; N=0 removes it")
    cpj = csub.add_parser("set-project")
    cpj.add_argument("--root", required=True)
    cpj.add_argument("--name")
    cpj.add_argument("--base-branch")
    cpj.add_argument("--merge-method", choices=("merge", "squash", "rebase", "auto"),
                     help="auto: run gh pr merge --auto with no method flag (merge queue or repository default)")
    cpj.add_argument("--leases-default", choices=("on", "off"))
    cpj.add_argument("--class", dest="pcls", metavar="CLASS")
    cpj.add_argument("--max-minutes", type=int)
    cpj.add_argument("--minutes", choices=("learn", "fixed"), help="learn: adapt the limit to recorded run times, capped by --max-minutes")
    cpj.add_argument("--peak", choices=("learn", "fixed"))
    cpj.add_argument("--default-gib", type=float)
    sc = csub.add_parser("set-class")
    sc.add_argument("name", metavar="CLASS")
    sc.add_argument("--description")
    sc.add_argument("--default-gib", type=float, help="expected peak; 0 = not memory-bound")
    sc.add_argument("--max-minutes", type=int)
    sc.add_argument("--settle", action="append", help="OTHER=SECONDS: after a grant of this class, OTHER waits (0 removes)")
    rc = csub.add_parser("remove-class")
    rc.add_argument("name", metavar="CLASS")
    ck = csub.add_parser("project-key")
    ck.add_argument("path")
    m = sub.add_parser("say")
    m.add_argument("--from", dest="sender", required=True)
    m.add_argument("--message", required=True)
    m.add_argument("--to", help="coordinator or member name; omit to reach every live coordinator")
    m.add_argument("--no-direct", action="store_true", help="append to inbox.jsonl only")
    me = sub.add_parser("memory")
    mesub = me.add_subparsers(dest="mcmd", required=True)
    ma = mesub.add_parser("add")
    ma.add_argument("--by", required=True)
    ma.add_argument("--text", required=True)
    ma.add_argument("--kind", choices=("rule", "lesson", "note"), default="rule")
    ma.add_argument("--project-root")
    ml = mesub.add_parser("list")
    ml.add_argument("--project-root")
    ml.add_argument("--json", action="store_true")
    mr2 = mesub.add_parser("remove")
    mr2.add_argument("--id", required=True)
    mr2.add_argument("--project-root")
    nt = sub.add_parser("note")
    nt.add_argument("--by", required=True)
    nt.add_argument("--text", required=True)
    nt.add_argument("--pr", type=int)
    sub.add_parser("roster")
    co = sub.add_parser("coordinate")
    co.add_argument("--name", required=True)
    co.add_argument("--tool", choices=TOOLS, required=True)
    co.add_argument("--session-id", required=True)
    co.add_argument("--focus", required=True)
    co.add_argument("--pr", type=int, action="append")
    co.add_argument("--takeover", action="store_true", help="replace a live coordinator of the same name (user approval only)")
    hb = sub.add_parser("heartbeat")
    hb.add_argument("--name", required=True)
    hb.add_argument("--focus")
    hb.add_argument("--pr", type=int, action="append")
    rs = sub.add_parser("resign")
    rs.add_argument("--name", required=True)
    ls = sub.add_parser("leases")
    ls.add_argument("mode", choices=("on", "off"))
    ls.add_argument("--by", required=True)
    mb = sub.add_parser("member")
    msub = mb.add_subparsers(dest="mcmd", required=True)
    for name in ("add", "update"):
        mx = msub.add_parser(name)
        mx.add_argument("--coordinator", required=True)
        mx.add_argument("--name", required=True)
        mx.add_argument("--tool", choices=TOOLS)
        mx.add_argument("--session-id")
        mx.add_argument("--worktree")
        mx.add_argument("--task")
        mx.add_argument("--pr", type=int, action="append", help="replaces the PR list")
        mx.add_argument("--repo", help="owner/repo, for PR links on the dashboard")
        mx.add_argument("--status", choices=("pending", "active", "paused", "done"))
        mx.add_argument("--phase")
        mx.add_argument("--kind", choices=("ok", "work", "warn", "done"))
        mx.add_argument("--latest")
        mx.add_argument("--session", help="deep link for the dashboard")
    mr = msub.add_parser("remove")
    mr.add_argument("--coordinator", required=True)
    mr.add_argument("--name", required=True)
    ms = msub.add_parser("stale")
    ms.add_argument("--coordinator", required=True)
    ms.add_argument("--minutes", type=int, default=30)
    en = sub.add_parser("enroll")
    en.add_argument("--coordinator", required=True)
    en.add_argument("--by", help="member that asked for the task; default: the coordinator")
    en.add_argument("--task", required=True)
    en.add_argument("--name")
    en.add_argument("--pr", type=int, action="append")
    wh = sub.add_parser("whoami")
    wh.add_argument("--session-id", required=True)
    sub.add_parser("host-check")
    cw = sub.add_parser("calm-wait")
    cw.add_argument("--settle", type=int, default=0, help="seconds to wait first, e.g. while a stack starts")
    cw.add_argument("--retry", type=int, default=20)
    mp = sub.add_parser("measure-peak")
    mp.add_argument("--id", required=True)
    mp.add_argument("--worktree", required=True)
    mp.add_argument("--interval", type=float, default=15)
    dr = sub.add_parser("drain-check")
    dr.add_argument("--worktree", required=True)
    dr.add_argument("--port", type=int, action="append", help="also check for listeners on this port")
    dr.add_argument("--process", action="append", help="also count processes matching this pattern (pgrep -f)")
    wa = sub.add_parser("watch")
    wa.add_argument("what", choices=("inbox", "expiry", "prs"))
    wa.add_argument("--me", help="coordinator name (inbox, prs)")
    wa.add_argument("--interval", type=int, default=180, help="seconds between PR polls")
    sub.add_parser("install")
    args = p.parse_args()
    for attr in ("cls", "pcls"):
        name = getattr(args, attr, None)
        if name and name not in registry():
            p.error(f"unknown lease class {name}; known: {', '.join(class_names())} (add one with config set-class)")

    if args.cmd == "say":
        return say_cmd(args)
    if args.cmd == "note":
        note(args.by, args.text, args.pr)
        return 0
    if args.cmd == "memory":
        return memory_cmd(args)
    if args.cmd == "await-grant":
        return await_grant(args)
    unlocked = {"host-check": host_check_cmd, "calm-wait": calm_wait_cmd, "measure-peak": measure_peak_cmd,
                "drain-check": drain_check_cmd, "watch": watch_cmd, "install": install_cmd}
    if args.cmd in unlocked:
        if args.cmd == "watch" and args.what != "expiry" and not args.me:
            p.error("watch inbox|prs needs --me <coordinator>")
        return unlocked[args.cmd](args)
    if args.cmd == "decision":
        return decision_cmd(args)

    lock()
    try:
        if args.cmd in ("roster", "coordinate", "heartbeat", "resign", "leases", "member", "enroll", "whoami"):
            return roster_cmd(args)
        if args.cmd == "config":
            return config_cmd(args)
        state = load()
        machine = load_machine()
        if args.cmd == "status":
            state["budget"] = budget(state, machine)
            if args.brief:
                print(brief(state))
            else:
                print(json.dumps(state, indent=1))
            return 0
        if args.cmd == "capacity":
            print(json.dumps(budget(state, machine), indent=1))
            return 0
        queue = state["queue"][args.cls]
        if args.cmd == "wait":
            existing = next((q for q in queue if q["id"] == args.id), None)
            if existing:
                if args.minutes:
                    existing["minutes"] = args.minutes
                if args.gib:
                    existing["gib"] = args.gib
                if args.holder:
                    existing["holder"] = args.holder
                if args.commands:
                    existing["commands"] = args.commands
                if args.worktree:
                    existing["project"] = project_key(args.worktree)[0]
            else:
                if not (args.coordinator and args.holder):
                    print("a new queue entry needs --coordinator and --holder")
                    return 2
                entry = {"coordinator": args.coordinator, "holder": args.holder, "id": args.id, "since": now().isoformat()}
                if args.minutes:
                    entry["minutes"] = args.minutes
                if args.gib:
                    entry["gib"] = args.gib
                if args.commands:
                    entry["commands"] = args.commands
                if args.worktree:
                    entry["project"] = project_key(args.worktree)[0]
                if args.front:
                    queue.insert(0, entry)
                else:
                    queue.append(entry)
                log(f"wait {args.cls} {args.coordinator} {args.id} {args.holder}")
            save(state, machine)
            print(f"position {[q['id'] for q in queue].index(args.id) + 1}")
            return 0
        if args.cmd == "extend":
            for h in state[args.cls]:
                if h["id"] == args.id:
                    h["expiresAt"] = (now() + dt.timedelta(minutes=args.minutes)).isoformat()
                    save(state, machine)
                    log(f"extend {args.cls} {args.id} until {h['expiresAt']}")
                    return 0
            print(f"{args.cls} not held by {args.id}")
            return 3
        if args.cmd in ("hold", "ready"):
            for q in queue:
                if q["id"] == args.id:
                    q["hold"] = args.cmd == "hold"
            save(state, machine)
            log(f"{args.cmd} {args.cls} {args.id}")
            return 0
        if args.cmd == "unwait":
            state["queue"][args.cls] = [q for q in queue if q["id"] != args.id]
            save(state, machine)
            log(f"unwait {args.cls} {args.id}")
            return 0
        holders = state[args.cls]
        if args.cmd == "acquire":
            if any(h["id"] == args.id for h in holders):
                print("already held")
                return 0
            ready = [q for q in queue if not q.get("hold")]
            if ready and ready[0]["id"] != args.id:
                print(json.dumps({"queued_ahead": ready[0]}))
                return 3
            cap = machine["maxSlots"].get(args.cls)
            if cap and len(holders) >= cap:
                print(json.dumps({"max_slots": cap, "held": holders}))
                return 3
            for other, spec in registry(machine).items():
                secs = (spec.get("settle") or {}).get(args.cls, 0)
                for h in state[other] if secs else []:
                    left = secs - (now() - dt.datetime.fromisoformat(h["grantedAt"])).total_seconds()
                    if left > 0:
                        print(json.dumps({"settling": int(left), "after": h["id"], "class": other}))
                        return 3
            entry = next((q for q in queue if q["id"] == args.id), {})
            key = entry.get("project") or project_key(args.worktree)[0]
            gib = args.gib or entry.get("gib") or class_peak(load_project(key), args.cls)
            b = budget(state, machine)
            if gib > b["freeGiB"]:
                why = f"needs {gib} GiB, {b['freeGiB']} GiB free of {b['limitGiB']} GiB budget"
                print(json.dumps({"memory": why, "held": [h["id"] for c in class_names(machine) for h in state[c]]}))
                log(f"refuse {args.cls} {args.coordinator} {args.id} {why}")
                return 4
            state["queue"][args.cls] = [q for q in queue if q["id"] != args.id]
            t = now()
            holders.append({
                "coordinator": args.coordinator,
                "holder": args.holder,
                "id": args.id,
                "worktree": args.worktree,
                "project": key,
                "gib": gib,
                "commands": args.commands or entry.get("commands"),
                "grantedAt": t.isoformat(),
                "expiresAt": (t + dt.timedelta(minutes=args.minutes)).isoformat(),
            })
            if args.measure:
                os.makedirs(PEAKS, exist_ok=True)
                proc = subprocess.Popen(
                    [sys.executable, "-I", os.path.abspath(__file__), "measure-peak", "--id", args.id, "--worktree", args.worktree],
                    stdin=subprocess.DEVNULL, stdout=open(os.path.join(PEAKS, f"{args.id}.log"), "a"), stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                holders[-1]["measurePid"] = proc.pid
            save(state, machine)
            log(f"acquire {args.cls} {args.coordinator} {args.id} {args.holder} until {holders[-1]['expiresAt']} ({gib} GiB, {round(b['freeGiB'] - gib, 1)} GiB left)")
            return 0
        if not any(h["id"] == args.id for h in holders):
            print(f"{args.cls} not held by {args.id}: {json.dumps(holders)}")
            return 3
        peak = args.peak_gib
        peak_file = os.path.join(PEAKS, f"{args.id}.gib")
        if peak is None and os.path.exists(peak_file):
            try:
                peak = float(open(peak_file).read().strip())
            except ValueError:
                peak = None
        held = next(h for h in holders if h["id"] == args.id)
        key = held["project"]
        ran = round((now() - dt.datetime.fromisoformat(held["grantedAt"])).total_seconds() / 60, 1)
        if key:
            proj = load_project(key, held.get("worktree"))
            c = proj["classes"][args.cls]
            if peak:
                c["samples"].append(round(peak, 1))
                del c["samples"][:-SAMPLES_KEPT]
            c["runMinutes"].append(ran)
            del c["runMinutes"][:-MINUTES_KEPT]
            save_project(proj)
        if os.path.exists(peak_file):
            os.remove(peak_file)
        state[args.cls] = [h for h in holders if h["id"] != args.id]
        save(state, machine)
        log(f"release {args.cls} {args.id} ran {ran} min" + (f" peak {round(peak, 1)} GiB" if peak else ""))
        return 0
    finally:
        unlock()


if __name__ == "__main__":
    sys.exit(main())
