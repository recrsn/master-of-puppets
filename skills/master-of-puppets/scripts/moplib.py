"""Shared state for the master-of-puppets helpers coordinator.py and puppet.py.

Both CLIs import this module. It holds the state paths, JSON I/O, the state lock,
the event log and ledger, machine and project config, the roster, the lease state
and memory budget, the drain check, direct message delivery to Claude and Codex
sessions, and the read-only commands both CLIs offer (roster, whoami, memory list,
inbox, ledger, events, who, sizes).

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
MEMBER_TOOLS = TOOLS + ("coderabbit",)  # a CodeRabbit cloud task: tracked, never messaged
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
PEAKS = os.path.join(DIR, "peaks")
LOCK = os.path.join(DIR, "lock")
LOG = os.path.join(DIR, "events.log")
INBOX = os.path.join(DIR, "inbox.jsonl")
FILES = ("moplib.py", "coordinator.py", "puppet.py")  # the live helpers that install copies
OBSOLETE = ("lease.py",)  # helpers that earlier versions installed; install removes them
SOURCE = os.path.join(DIR, "source.json")  # the skill copy that install last copied from
CLASS_NAME = re.compile(r"^[A-Z][A-Z0-9_-]{0,23}$")
DEFAULT_REGISTRY = {
    "BUILD": {"description": "builds, typecheck, lint/format, tests, codegen", "defaultGiB": 0, "defaultCpus": 0, "maxMinutes": 0, "settle": {}},
    "E2E": {"description": "local servers/stacks and interacting with them", "defaultGiB": 0, "defaultCpus": 0, "maxMinutes": 0, "settle": {"BUILD": 60}},
}
MACHINE_DEFAULTS = {
    "reserveGiB": 6,
    "reserveCpus": 2,
    "sizeMargin": 0.25,
    "diskFloorGiB": 4,
    "diskAlarmGiB": 10,
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
    """Lease classes: config.json "classes", else the default BUILD and E2E. A stored class
    takes the default registry's fields it lacks (a custom class: defaultCpus 0)."""
    machine = machine or load_machine()
    stored = machine.get("classes") or DEFAULT_REGISTRY
    return {n: json.loads(json.dumps({"defaultCpus": 0, **DEFAULT_REGISTRY.get(n, {}), **c})) for n, c in stored.items()}


def class_names(machine=None):
    return list(registry(machine))


def project_class_defaults(cls):
    reg = registry().get(cls, {})
    return {"maxMinutes": reg.get("maxMinutes", 0), "minutesMode": "fixed", "peakMode": "learn",
            "defaultGiB": reg.get("defaultGiB", 0), "defaultCpus": reg.get("defaultCpus", 0)}


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
    proj["classes"] = {c: {**project_class_defaults(c), "samples": [], "cpuSamples": [], "runMinutes": [], **stored.get(c, {})} for c in class_names()}
    return proj


def save_project(proj):
    write_json(os.path.join(PROJECTS, f"{proj['key']}.json"), proj)


RESOURCES = {"gib": ("samples", "defaultGiB"), "cpus": ("cpuSamples", "defaultCpus")}


def class_peak(proj, cls, kind="gib"):
    """Expected peak GiB (kind gib) or cores (kind cpus) of a class run. GiB, learn: max of
    the last 5 samples, the default a floor until 3 exist; fixed: the default. Cores: always
    the set default (0 = no core charge); core samples only inform the coordinators' vote."""
    c = proj["classes"][cls] if proj else project_class_defaults(cls)
    samples_key, default_key = RESOURCES[kind]
    samples = c.get(samples_key, [])
    if kind == "cpus" or c.get("peakMode") == "fixed":
        return c[default_key]
    if len(samples) >= SAMPLES_TRUSTED:
        return max(samples)
    return max([c[default_key], *samples])


def observed_peak(proj, cls, kind="gib"):
    """The coordinator's own observation: max of the last 5 measured samples once 3
    exist in learn mode; else None (a default is a rule, not an observation)."""
    c = proj["classes"][cls] if proj else {}
    samples = c.get(RESOURCES[kind][0], [])
    if c.get("peakMode") == "fixed" or len(samples) < SAMPLES_TRUSTED:
        return None
    return max(samples)


def undersized(cls, key, gib, margin):
    """Refusal text when a requested GiB is below the observed peak of the class in project
    key by more than margin (a fraction), else None. A request without GiB is not checked:
    the coordinator charges its own figure. Cores are not checked: observed cores only
    inform the coordinators' vote on defaultCpus."""
    proj = load_project(key) if key else None
    seen = observed_peak(proj, cls)
    if not (gib and seen and gib < seen * (1 - margin)):
        return None
    return (f"undersized {cls}: {gib:g} GiB asked, {seen:g} GiB observed (margin {margin:.0%}); ask for at least "
            "the observed peak, or tell your coordinator why this run is smaller")


def typical_minutes(proj, cls):
    """Median of recorded run minutes, once 3 exist; else None."""
    runs = sorted((proj["classes"][cls] if proj else {}).get("runMinutes", []))
    return runs[len(runs) // 2] if len(runs) >= SAMPLES_TRUSTED else None


def suggested_minutes(proj, cls):
    """learn: p90 of the last 10 runs plus 25%, at least 5, at most the configured maximum (0: no maximum).
    A reference for members; it never limits a lease or sets its length. fixed (or fewer than 3 runs): None."""
    c = proj["classes"][cls] if proj else project_class_defaults(cls)
    runs = sorted(c.get("runMinutes", []))
    if c.get("minutesMode") != "learn" or len(runs) < SAMPLES_TRUSTED:
        return None
    p90 = runs[max(0, -(-9 * len(runs) // 10) - 1)]
    suggested = int(max(5, -(-p90 * 1.25 // 1)))
    return min(c["maxMinutes"], suggested) if c["maxMinutes"] else suggested


def length_limit(cls, key):
    """Max lease minutes of class cls in project key: the configured maximum (the registry
    default without one); 0 means no limit. Learned run times never lower it: runs cannot
    outlast the limit, so a limit learned from them could only shrink."""
    proj = load_project(key) if key else None
    return (proj["classes"][cls] if proj else project_class_defaults(cls))["maxMinutes"]


def over_limit(cls, key, minutes):
    """Refusal text when minutes is over the class limit, else None."""
    limit = length_limit(cls, key)
    if limit and minutes > limit:
        return f"{minutes} min is over the {limit}-min {cls} limit; split the run into parts of at most {limit} min"
    return None


def extension_refusal(held, cls, minutes):
    """Refusal text when held, expiring minutes from now, would run longer than the class
    limit, else None."""
    expires = now() + dt.timedelta(minutes=minutes)
    total = (expires - dt.datetime.fromisoformat(held["grantedAt"])).total_seconds() / 60
    limit = length_limit(cls, held.get("project"))
    if limit and total > limit:
        return f"the lease would run {total:.0f} min, over the {limit}-min {cls} limit; release it and queue the rest"
    return None


def extend_lease(held, cls, minutes):
    """Set held's expiry to minutes from now. The caller holds the lock, saves and logs.
    Returns (exit, text): 0 with the new expiry, 2 when the lease would then run
    longer than the class limit."""
    why = extension_refusal(held, cls, minutes)
    if why:
        return 2, why
    held["expiresAt"] = (now() + dt.timedelta(minutes=minutes)).isoformat()
    return 0, held["expiresAt"]


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


def id_owner(lease_id, names):
    """The coordinator whose name prefixes lease_id ("<coordinator>-q-..."), longest name
    first, so claude-kb-q-x belongs to claude-kb, not to claude. None when none does."""
    for n in sorted(names, key=len, reverse=True):
        if lease_id.startswith(n + "-"):
            return n
    return None


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


def order(queue):
    """Higher priority first. The sort is stable, so entries of one priority keep their order (FIFO)."""
    queue.sort(key=lambda q: -q.get("priority", 0))


def task_priority(roster, coord, holder):
    """Priority of the member that a queue entry's holder names (its first word), else 0."""
    name = holder.partition(" ")[0]
    m = next((x for x in roster["members"].get(coord, []) if x["name"] == name), None)
    return (m or {}).get("priority", 0)


def queue_entry(state, roster, cls, id, coordinator=None, holder=None, minutes=None, gib=None, cpus=None,
                commands=None, worktree=None, priority=None, front=False, by=None, changed_by=None):
    """Add queue entry id to class cls, or change the given fields of an existing one, and
    re-order the queue. The caller holds the lock and saves. changed_by names the
    coordinator in a priority change's event. Returns (exit, text):
    0 with the position, 2 when minutes is over the class limit, gib or cpus is over the
    whole budget, or a new entry lacks coordinator and holder."""
    queue = state["queue"][cls]
    existing = next((q for q in queue if q["id"] == id), None)
    b = budget(state, load_machine())
    for asked, limit, unit in ((gib, b["limitGiB"], "GiB"), (cpus, b["limitCpus"], "cores")):
        if asked and asked > limit:
            return 2, f"{asked:g} {unit} is over the whole {limit:g}-{unit} budget; split the run into smaller parts"
    if minutes:
        key = project_key(worktree)[0] if worktree else (existing or {}).get("project")
        why = over_limit(cls, key, minutes)
        if why:
            return 2, why
    if existing:
        if minutes:
            existing["minutes"] = minutes
        if gib:
            existing["gib"] = gib
        if cpus:
            existing["cpus"] = cpus
        if holder:
            existing["holder"] = holder
        if commands:
            existing["commands"] = commands
        if worktree:
            existing["project"] = project_key(worktree)[0]
        if priority is not None and priority != existing.get("priority", 0):
            existing["priority"] = priority
            log(f"priority {cls} {id} {priority}" + (f" by={changed_by}" if changed_by else ""))
            if changed_by and changed_by != existing["coordinator"]:
                say(changed_by, f"PRIORITY {cls} {id} {priority} by={changed_by}", existing["coordinator"])
        if by:
            log(f"request {cls} {existing['coordinator']} {id} changed {existing['holder']} by={by}")
            say(by, f"REQUEST {cls} {id} changed {existing['holder']}: check it and grant it with acquire when the host and budget allow",
                existing["coordinator"])
    else:
        if not (coordinator and holder):
            return 2, "a new queue entry needs --coordinator and --holder"
        if priority is None:
            priority = task_priority(roster, coordinator, holder)
        entry = {"coordinator": coordinator, "holder": holder, "id": id, "priority": priority,
                 "since": now().isoformat()}
        if minutes:
            entry["minutes"] = minutes
        if gib:
            entry["gib"] = gib
        if cpus:
            entry["cpus"] = cpus
        if commands:
            entry["commands"] = commands
        if worktree:
            entry["project"] = project_key(worktree)[0]
        if front:
            entry["priority"] = max([priority] + [q.get("priority", 0) for q in queue])
            queue.insert(0, entry)
        else:
            queue.append(entry)
        # A member's own request logs "request" and lands in its coordinator's inbox.
        verb = "request" if by else "wait"
        log(f"{verb} {cls} {coordinator} {id} {holder}" + (f" priority={entry['priority']}" if entry["priority"] else "")
            + (f" by={by}" if by else ""))
        if by:
            say(by, f"REQUEST {cls} {id} {holder}" + (f" priority {entry['priority']}" if entry["priority"] else "")
                + ": check it and grant it with acquire when the host and budget allow", coordinator)
    order(queue)
    return 0, f"position {[q['id'] for q in queue].index(id) + 1}"


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


def fleet_peak(cls, kind="gib"):
    """Largest class peak over known projects, for the capacity display."""
    peaks = [class_peak(p, cls, kind) for p in known_projects()]
    return max(peaks) if peaks else project_class_defaults(cls)[RESOURCES[kind][1]]


def budget(state, machine):
    """Memory and core budgets, plus per-class capacity = holders + how many more of that
    class fit both budgets now."""
    total, cores = total_gib(), os.cpu_count() or 1
    limit, cpu_limit = total - machine["reserveGiB"], cores - machine["reserveCpus"]
    names = class_names(machine)
    peaks = {c: fleet_peak(c) for c in names}
    cpu_peaks = {c: fleet_peak(c, "cpus") for c in names}
    held = sum(h["gib"] for c in names for h in state[c])
    held_cpus = sum(h["cpus"] for c in names for h in state[c])
    free, free_cpus = limit - held, cpu_limit - held_cpus
    capacity = {}
    for c in names:
        cap = machine["maxSlots"].get(c)
        fits = [int(f // p) for f, p in ((free, peaks[c]), (free_cpus, cpu_peaks[c])) if p > 0]
        if fits:
            n = len(state[c]) + max(0, min(fits))
            capacity[c] = min(n, cap) if cap else n
        else:
            capacity[c] = cap  # None: uses neither budget and uncapped
    return {
        "totalGiB": round(total, 1),
        "reserveGiB": machine["reserveGiB"],
        "limitGiB": round(limit, 1),
        "heldGiB": round(held, 1),
        "freeGiB": round(free, 1),
        "peakGiB": peaks,
        "totalCpus": cores,
        "reserveCpus": machine["reserveCpus"],
        "limitCpus": cpu_limit,
        "heldCpus": round(held_cpus, 1),
        "freeCpus": round(free_cpus, 1),
        "peakCpus": cpu_peaks,
        "capacity": capacity,
    }


# ---------------------------------------------------------------- processes and drain


SHELLS = {"sh", "bash", "zsh", "fish", "dash", "ksh", "tcsh", "login"}
AGENTS = {"claude", "codex", "disclaimer"}  # session programs; disclaimer is the Claude app's launcher


def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


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


def session_pids():
    """Processes that belong to agent sessions, not to a run: this process and its
    ancestors, its own process group (the pipeline of the command that runs it; each
    agent shell command gets its own group), agent programs (claude, codex), their
    direct children that are not shells (MCP servers and helpers), and every bare shell.
    A heuristic: a run that an earlier command started is a shell child or deeper, in
    another process group, so it still counts."""
    procs, group = {}, str(os.getpgid(0))
    for line in run(["ps", "-axo", "pid=,ppid=,pgid=,comm="]).splitlines():
        f = line.split(None, 3)
        if len(f) == 4:
            procs[f[0]] = (f[1], f[2], os.path.basename(f[3]).lstrip("-"))
    skip, pid = set(), str(os.getpid())
    while pid in procs and pid not in skip:
        skip.add(pid)
        pid = procs[pid][0]
    for pid, (ppid, pgid, comm) in procs.items():
        parent = procs.get(ppid, ("", "", ""))[2]
        if pgid == group or comm in AGENTS or comm in SHELLS or (parent in AGENTS and comm not in SHELLS):
            skip.add(pid)
    return skip


def drain(worktree, ports=(), patterns=()):
    """What a run left behind: processes working in the worktree (except session
    processes), listeners on the given ports, processes matching each pattern.
    Returns a list of report lines, one per process left. It only reports; it never kills."""
    lines, skip = [], session_pids()
    for pid in worktree_pids(worktree):
        if pid in skip:
            continue
        cmd = run(["ps", "-o", "command=", "-p", pid]).strip()[:100]
        if not cmd:
            continue
        listen = [l[1:] for l in run(["lsof", "-nP", "-a", "-p", pid, "-iTCP", "-sTCP:LISTEN", "-Fn"]).splitlines() if l.startswith("n")]
        lines.append(f"worktree {pid} {'[listen ' + ' '.join(listen) + '] ' if listen else ''}{cmd}")
    for port in ports:
        for line in run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"]).splitlines():
            if line.startswith("p"):
                lines.append(f"port {port} {line[1:]} {run(['ps', '-o', 'command=', '-p', line[1:]]).strip()[:100]}")
    for pattern in patterns:
        for line in run(["pgrep", "-fl", pattern]).splitlines():
            if line.split()[0] not in skip:  # the caller's own command line names the pattern
                lines.append(f"process {pattern}: {line[:110]}")
    return lines


# ---------------------------------------------------------------- helper versions


def helpers_differ(src):
    """Names of the live helpers that differ from (or are missing beside) the copy in src."""
    def read(path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None
    return [n for n in FILES if read(os.path.join(src, n)) is None or read(os.path.join(src, n)) != read(os.path.join(DIR, n))]


def version_warning():
    """Tell the session on stderr when an update of the live helpers is due: the skill copy
    differs from the live copies, or an obsolete helper is still in the state dir."""
    here = os.path.dirname(os.path.realpath(__file__))
    if here == os.path.realpath(DIR):
        try:
            with open(SOURCE) as f:
                src = json.load(f)["path"]
        except (OSError, ValueError, KeyError, TypeError):
            return
    else:
        src = here
    if not os.path.isdir(src):
        return
    differ = helpers_differ(src)
    obsolete = [n for n in OBSOLETE if os.path.exists(os.path.join(DIR, n))]
    if differ:
        print(f"warning: an update is due: the live {', '.join(differ)} in {DIR} {'differs' if len(differ) == 1 else 'differ'} from the skill copy in {src}. "
              f"Check python3 -I {os.path.join(src, 'coordinator.py')} update status; with no open proposal, run "
              f"python3 -I {os.path.join(src, 'coordinator.py')} update propose --by <you>", file=sys.stderr)
    if obsolete:
        print(f"warning: obsolete {', '.join(obsolete)} in {DIR}: do not run it; "
              f"python3 -I {os.path.join(src, 'coordinator.py')} install removes it", file=sys.stderr)


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


READS = ("roster", "whoami", "memory", "inbox", "ledger", "events", "who", "sizes")
AGO = re.compile(r"^(\d+)([smhd])$")
AGO_UNITS = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}


def memory_path(project_root=None):
    name = project_key(project_root)[0] if project_root else "machine"
    return os.path.join(MEMORY, f"{name}.json"), name


def since_time(text):
    """--since: an ISO time, or an age such as 90s, 30m, 2h or 1d."""
    m = AGO.match(text)
    if m:
        return now() - dt.timedelta(**{AGO_UNITS[m.group(2)]: int(m.group(1))})
    t = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def add_read_commands(sub, memory=None):
    """roster, whoami, memory list, inbox, ledger, events and who. Both CLIs offer them;
    coordinator.py passes its memory subparsers so add and remove sit beside list."""
    sub.add_parser("roster")
    wh = sub.add_parser("whoami")
    wh.add_argument("--session-id", required=True)
    if memory is None:
        memory = sub.add_parser("memory").add_subparsers(dest="mcmd", required=True)
    ml = memory.add_parser("list")
    ml.add_argument("--project-root")
    ml.add_argument("--json", action="store_true")
    for name, what in (("inbox", "coordinator messages (inbox.jsonl)"), ("ledger", "the shared ledger (ledger.jsonl)"),
                       ("events", "lease and roster events (events.log)")):
        r = sub.add_parser(name, help=what)
        r.add_argument("--since", help="ISO time or an age: 90s, 30m, 2h, 1d")
        r.add_argument("--grep", help="case-insensitive text match")
        r.add_argument("-n", type=int, default=20, help="the last N matches (0: all)")
        r.add_argument("--json", action="store_true", help="the raw records")
        if name == "inbox":
            r.add_argument("--from", dest="sender")
            r.add_argument("--to", help="messages C receives: sent to C or to every coordinator")
        elif name == "ledger":
            r.add_argument("--by")
            r.add_argument("--pr", type=int)
        else:
            r.add_argument("--id", help="lease or queue ID")
            r.add_argument("--class", dest="lcls", metavar="CLASS")
            r.add_argument("--coordinator", help="C's grants, queue entries, lease IDs and actions")
    w = sub.add_parser("who", help="who owns a PR, worktree, repository or task")
    g = w.add_mutually_exclusive_group(required=True)
    g.add_argument("--pr", type=int)
    g.add_argument("--worktree")
    g.add_argument("--repo", help="owner/repo")
    g.add_argument("--text", help="case-insensitive match on names, tasks, focus, labels and goals")
    sz = sub.add_parser("sizes", help="a project's recorded run sizes per class: the figures to size a lease from")
    sz.add_argument("--worktree", required=True)
    sz.add_argument("--class", dest="lcls", metavar="CLASS")


def event_coordinator(f, names):
    """The coordinator an events.log line (split into fields) is about, or None."""
    if len(f) > 3 and f[1] in ("wait", "request", "acquire", "refuse"):
        return f[3]
    for x in f:
        if x.startswith("coordinator="):
            return x.partition("=")[2]
    if len(f) > 3 and f[1] in ("release", "unwait", "hold", "ready", "extend", "priority", "up"):
        return id_owner(f[3], names)
    if f[1] in ("coordinate", "resign", "active", "idle"):
        return f[2]
    return None


def log_cmd(args):
    """inbox, ledger and events: filter, then print the last -n matches."""
    since = since_time(args.since) if args.since else None
    grep = args.grep.lower() if args.grep else None
    names = list(load_roster()["coordinators"])
    rows = []
    path = {"inbox": INBOX, "ledger": LEDGER, "events": LOG}[args.cmd]
    try:
        lines = open(path).read().splitlines()
    except OSError:
        lines = []
    for line in lines:
        if not line.strip() or (grep and grep not in line.lower()):
            continue
        if args.cmd == "events":
            f = line.split()
            try:
                at = dt.datetime.fromisoformat(f[0])
            except (ValueError, IndexError):
                continue
            if ((since and at < since) or (args.id and args.id not in f[2:5])
                    or (args.lcls and (len(f) < 3 or f[2] != args.lcls))
                    or (args.coordinator and event_coordinator(f, names) != args.coordinator and f"by={args.coordinator}" not in f)):
                continue
            rows.append((line, line))
            continue
        try:
            rec = json.loads(line)
            at = dt.datetime.fromisoformat(rec["at"])
        except (ValueError, KeyError, TypeError):
            continue
        if since and at < since:
            continue
        if args.cmd == "inbox":
            if (args.sender and rec.get("from") != args.sender) or (args.to and rec.get("to") not in (args.to, None, "all")):
                continue
            text = f"{rec['at'][:19]}Z {rec.get('from')} -> {rec.get('to') or 'all'}: {rec.get('message')}"
        else:
            if (args.by and rec.get("by") != args.by) or (args.pr and rec.get("pr") != args.pr):
                continue
            text = f"{rec['at'][:19]}Z {rec.get('by')}{' #' + str(rec['pr']) if rec.get('pr') else ''}: {rec.get('text')}"
        rows.append((line, text))
    for raw, text in rows[-args.n:] if args.n else rows:
        print(raw if args.json else text)
    return 0


def who_cmd(args):
    """Owners of a PR, worktree, repository or text, from the roster, the PR and cloud
    watch lists, and the lease state. Exit 3 when nothing matches."""
    roster, state = load_roster(), load()
    hits = []

    def match(*fields):
        if args.text:
            return any(args.text.lower() in str(x or "").lower() for x in fields)
        return False

    tree = os.path.realpath(os.path.expanduser(args.worktree)) if args.worktree else None

    def same_tree(path):
        return bool(tree and path and (os.path.realpath(os.path.expanduser(path)) + "/").startswith(tree + "/"))
    for name, c in roster["coordinators"].items():
        if (args.pr and args.pr in c.get("prs", [])) or match(name, c.get("focus")):
            hits.append(f"coordinator {name} ({'live' if live(c) else 'not live'}): {c.get('focus', '')}")
    for coord, members in roster["members"].items():
        for m in members:
            if ((args.pr and args.pr in m.get("prs", [])) or (args.repo and m.get("repo") == args.repo)
                    or same_tree(m.get("worktree")) or match(m["name"], m.get("task"), m.get("sessionId"))):
                hits.append(f"member {coord}/{m['name']} ({m.get('status', 'active')}): {m.get('task', '')}"
                            + (f" · {m['repo']}" if m.get("repo") else "") + (f" · PRs {' '.join('#' + str(n) for n in m['prs'])}" if m.get("prs") else ""))
    for slug, s in roster["streams"].items():
        if (args.pr and args.pr in s.get("prs", [])) or match(slug, s.get("label"), s.get("goal")):
            hits.append(f"stream {slug} ({s.get('coordinator')}, {s.get('status')}): {s.get('label', '')}")
    for kind in ("prs", "cloud"):
        for path in sorted(p for p in os.listdir(DIR) if p.startswith(kind + "-") and p.endswith(".txt")) if os.path.isdir(DIR) else []:
            coord = path[len(kind) + 1:-4]
            for raw in open(os.path.join(DIR, path)).read().splitlines():
                ref = raw.split()[0] if raw.split() else ""
                repo, _, num = ref.rpartition("#")
                if ((args.pr and num == str(args.pr)) or (args.repo and repo == args.repo) or match(raw)):
                    hits.append(f"{kind} watch of {coord}: {raw.strip()}")
    for c in class_names():
        for h in state[c] + state["queue"][c]:
            if same_tree(h.get("worktree")) or match(h["id"], h.get("holder")):
                hits.append(f"{c} {'held' if h in state[c] else 'queued'} {h['id']} ({h['coordinator']}): {h.get('holder', '')[:60]}")
    print("\n".join(dict.fromkeys(hits)) if hits else "no owner")
    return 0 if hits else 3


def sizes_cmd(args):
    """Per class of the worktree's project: limits, defaults, the recorded samples, the
    peaks the coordinator charges and checks against, and the run-minute figures."""
    if args.lcls and args.lcls not in class_names():
        print(f"unknown lease class {args.lcls}; known: {', '.join(class_names())}")
        return 2
    key = project_key(args.worktree)[0]
    proj, margin = load_project(key), load_machine()["sizeMargin"]
    out = {}
    for cls in [args.lcls] if args.lcls else class_names():
        c = proj["classes"][cls]
        out[cls] = {
            "maxMinutes": c["maxMinutes"], "suggestedMinutes": suggested_minutes(proj, cls),
            "typicalMinutes": typical_minutes(proj, cls), "runMinutes": c["runMinutes"],
            "peakMode": c["peakMode"], "defaultGiB": c["defaultGiB"], "defaultCpus": c["defaultCpus"],
            "gibSamples": c["samples"], "cpuSamples": c["cpuSamples"],
            "chargedGiB": class_peak(proj, cls), "chargedCpus": class_peak(proj, cls, "cpus"),
            "observedGiB": observed_peak(proj, cls), "observedCpus": observed_peak(proj, cls, "cpus"),
        }
    print(json.dumps({"project": key, "sizeMargin": margin, "classes": out}, indent=1))
    return 0


def read_cmd(args):
    """Read-only, so no lock."""
    if args.cmd in ("inbox", "ledger", "events"):
        return log_cmd(args)
    if args.cmd == "who":
        return who_cmd(args)
    if args.cmd == "sizes":
        return sizes_cmd(args)
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
