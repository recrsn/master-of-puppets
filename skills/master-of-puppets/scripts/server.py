#!/usr/bin/env python3
"""The one shared master-of-puppets dashboard: renders the page and serves it live.

Usage: python3 -I server.py [port]   (default: dashboardPort in config.json, else 4720)
Run it in the background. There is one dashboard per machine: when a dashboard
already answers on the port, this prints "already serving" and exits 0.

Inputs ($MACHINE_LEASE_DIR, default ~/.local/state/machine-leases):
  leases.json, roster.json, ledger.jsonl, config.json, projects/*.json and
  dashboard/<coordinator>-state.json (one per coordinator).
The page is rendered in memory when an input changes and every 30 s (ETAs and
heartbeat age). Every 5 s the server samples the host (CPU, load, memory, swap, disk).
  /            the page (shell: dashboard.html). Desk mode: host values in the header,
               "Needs you" first (grouped, alarms first), the work list, then the lease
               lanes; coordinators and the ledger open in a drawer. Wall mode: the
               same, large, for a shared screen (add ?mode=wall to the URL)
  POST /park   {"action": "park"|"unpark", "coord", "name", "until"?} from the Park and Unpark
               buttons: runs `coordinator.py park|unpark ... --notify`, so the coordinator is told.
  POST /queue  {"action": "up"|"unwait", "cls", "id"} from the page's Move up and Cancel
               buttons: runs `coordinator.py <action> CLASS --id ID --notify`, which tells each
               affected coordinator.
  POST /decide {"coord", "id", "choice"} from a decision's option buttons: runs
               `coordinator.py decision answer --by C --id ID --choice N --notify`, so the
               coordinator gets the user's answer. Only the option number crosses the post.
  Posts: same-origin JSON with X-Requested-By only.
  /events      text/event-stream: `update` (page changed) and `host` (JSON sample)
  /host.json   the latest host sample
  /health      "ok <version>"
"""
import datetime as dt
import glob
import hashlib
import html
import http.server
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request

DIR = os.path.expanduser(os.environ.get("MACHINE_LEASE_DIR") or "~/.local/state/machine-leases")
DEFAULT_REGISTRY = {
    "BUILD": {"description": "builds, typecheck, lint/format, tests, codegen", "defaultGiB": 0, "defaultCpus": 0, "maxMinutes": 0, "settle": {}},
    "E2E": {"description": "local servers/stacks and interacting with them", "defaultGiB": 0, "defaultCpus": 0, "maxMinutes": 0, "settle": {"BUILD": 60}},
}
RUNNING = '<span class="dot ontrack live" role="img" aria-label="Running"></span>'  # queue-position slot of a running lease
LIVE_MINUTES = 40
FORCE_EVERY = 30
HOST_EVERY = 5
e = html.escape


def load(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def machine_config():
    return load(os.path.join(DIR, "config.json"), {})


def configured_port():
    try:
        return int(machine_config().get("dashboardPort", 4720))
    except (TypeError, ValueError):
        return 4720


PORT = int(sys.argv[1]) if len(sys.argv) > 1 else configured_port()


# ---------------------------------------------------------------- host sampling

def run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def swapouts():
    m = re.search(r"Swapouts:\s+(\d+)", run(["vm_stat"]))
    return int(m.group(1)) if m else None


def sample_host(prev_swapouts, interval):
    """One host sample from macOS tools; a missing value is None."""
    cfg = machine_config()
    out = {"at": time.strftime("%H:%M:%S")}
    cores = os.cpu_count() or 1
    m = re.search(r"([\d.]+)% idle", run(["top", "-l", "2", "-n", "0", "-s", "1"]).split("CPU usage")[-1])
    out["cpuPct"] = round(100 - float(m.group(1)), 1) if m else None
    out["load1"] = round(os.getloadavg()[0], 2)
    out["maxLoad"] = round(cores * float(cfg.get("loadPerCore", 2.5)), 1)
    out["cores"] = cores
    total = int(run(["sysctl", "-n", "hw.memsize"]).strip() or 0) / 2**30
    m = re.search(r"(\d+)%", run(["memory_pressure", "-Q"]))
    free_pct = int(m.group(1)) if m else None
    out["memTotalGiB"] = round(total, 1)
    out["memFreePct"] = free_pct
    out["memUsedGiB"] = round(total * (100 - free_pct) / 100, 1) if free_pct is not None else None
    out["reserveGiB"] = cfg.get("reserveGiB", 6)
    m = re.search(r"total = ([\d.]+)M\s+used = ([\d.]+)M", run(["sysctl", "-n", "vm.swapusage"]))
    out["swapTotalGiB"] = round(float(m.group(1)) / 1024, 1) if m else None
    out["swapUsedGiB"] = round(float(m.group(2)) / 1024, 1) if m else None
    cur = swapouts()
    out["swapoutsPer12s"] = round((cur - prev_swapouts) * 12 / interval) if cur is not None and prev_swapouts is not None else None
    out["maxSwapouts"] = cfg.get("maxSwapouts", 200)
    du = shutil.disk_usage("/")
    out["diskFreeGiB"] = round(du.free / 2**30, 1)
    out["diskTotalGiB"] = round(du.total / 2**30, 1)
    out["diskFloorGiB"] = cfg.get("diskFloorGiB", 4)
    out["diskAlarmGiB"] = cfg.get("diskAlarmGiB", 10)
    return out, cur


SEV_ORDER = {"critical": 0, "serious": 1, "warning": 2, "ok": 3}
STALE_MINUTES = 30
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
KIND_LABEL = {"warn": "Blocked", "work": "In progress", "ok": "On track", "done": "Done"}
KIND_DOT = {"warn": "blocked", "work": "progress", "ok": "ontrack", "done": "done"}
# Needs you groups, in order: key, label, wall label, dot, color of the "ago" time
NEED_GROUPS = [("alarm", "Alarms", "alarms", "blocked", "danger"), ("decision", "Decisions", "decisions", "decision", "t2"),
               ("blocked", "Blocked", "blocked", "blocked", "t2"), ("stale", "Stale ({}+ min)", "stale", "stale", "warn"),
               ("revisit", "Revisit", "revisit", "stale", "warn")]
NEED_CAP = 8  # rows shown per Needs you group before "Show N more" (alarms are never capped)
WALL_ROWS = 8


def fmt(v, unit=""):
    return "?" if v is None else f"{v:g}{unit}" if isinstance(v, (int, float)) else f"{v}{unit}"


def host_tiles(h):
    """Four host tiles: id, label, value, short value, sub, meter percent, severity. Sent with each host event."""
    if not h or h.get("error"):
        why = (h or {}).get("error", "waiting for the first sample")
        return [{"id": k, "label": label, "value": "…", "short": "…", "sub": why, "pct": 0, "sev": "ok"}
                for k, label in (("cpu", "CPU"), ("memory", "Memory"), ("swap", "Swap"), ("disk", "Disk"))]

    f = fmt
    load_ratio = (h["load1"] / h["maxLoad"]) if h.get("maxLoad") else 0
    mem_pct = 100 - h["memFreePct"] if h.get("memFreePct") is not None else 0
    swap_pct = 100 * h["swapUsedGiB"] / h["swapTotalGiB"] if h.get("swapTotalGiB") else 0
    disk_pct = 100 * (1 - h["diskFreeGiB"] / h["diskTotalGiB"]) if h.get("diskTotalGiB") else 0
    outs, max_outs = h.get("swapoutsPer12s"), h.get("maxSwapouts", 200)
    return [
        {"id": "cpu", "label": "CPU", "value": f(h.get("cpuPct"), "%"), "pct": h.get("cpuPct") or 0,
         "short": f(h.get("cpuPct"), "%"),
         "sub": f"load {f(h['load1'])} of {f(h['maxLoad'])} · {h['cores']} cores",
         "sev": "critical" if load_ratio >= 1 else "warning" if load_ratio >= 0.8 else "ok"},
        {"id": "memory", "label": "Memory", "value": f"{f(h.get('memUsedGiB'))} GiB", "pct": mem_pct,
         "short": f"{mem_pct:.0f}%",
         "sub": f"of {f(h['memTotalGiB'])} GiB · {f(h.get('memFreePct'), '%')} free · reserve {f(h['reserveGiB'])} GiB",
         "sev": "critical" if mem_pct >= 90 else "warning" if mem_pct >= 80 else "ok"},
        {"id": "swap", "label": "Swap", "value": f"{f(h.get('swapUsedGiB'))} GiB", "pct": swap_pct,
         "short": f"{swap_pct:.0f}%",
         "sub": f"of {f(h.get('swapTotalGiB'))} GiB · {f(outs)} swap-outs/12 s (max {max_outs})",
         "sev": "critical" if outs is not None and outs >= max_outs else "warning" if outs is not None and outs >= max_outs / 2 else "ok"},
        {"id": "disk", "label": "Disk", "value": f"{f(h['diskFreeGiB'])} GiB free", "pct": disk_pct,
         "short": f"{f(h['diskFreeGiB'])}G free",
         "sub": f"of {f(h['diskTotalGiB'])} GiB · alarm below {f(h['diskAlarmGiB'])} · blocks below {f(h['diskFloorGiB'])} GiB",
         "sev": "critical" if h["diskFreeGiB"] < h["diskFloorGiB"]
                else "warning" if h["diskFreeGiB"] < h["diskAlarmGiB"] else "ok"},
    ]


# ---------------------------------------------------------------- rendering

# Lucide-style 24 px stroke icons for the lease request line
ICON = {
    "time": '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
    "cpus": '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/>'
            '<path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>',
    "gib": '<path d="M2 7a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2Z"/><path d="M6 19v-3M10 19v-3M14 19v-3M18 19v-3M7 9v3M12 9v3M17 9v3"/>',
}


def icon(name, label):
    return (f'<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round" role="img" aria-label="{label}"><title>{label}</title>{ICON[name]}</svg>')


def local(t):
    return t.astimezone().strftime("%H:%M")


def parse(iso):
    return dt.datetime.fromisoformat(iso)


def holders(leases, cls):
    return leases.get(cls) or []


def since(t, now):
    mins = int((now - t).total_seconds() // 60)
    return f"{mins} min" if mins < 90 else f"{mins // 60} h {mins % 60} min"


def ago(t, now):
    return since(t, now) + " ago"


def ago_short(t, now):
    mins = int((now - t).total_seconds() // 60)
    return "now" if mins < 1 else f"{mins}m" if mins < 60 else f"{mins // 60}h {mins % 60}m"


def link(item):
    return f'<a href="{e(item["href"])}">{e(item["label"])}</a>'


def dom_id(*parts):
    """A stable element id; the page script keeps open rows open across body swaps by it."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", "-".join(str(p) for p in parts))


def clamp(pct):
    return max(0.0, min(100.0, float(pct)))


def host_mini(t):
    """Compact host value for the header; the page script repaints it on each host event."""
    return (
        f'<span class="hs" data-host="{t["id"]}" data-sev="{t["sev"]}" title="{e(t["label"] + " " + t["value"] + " · " + t["sub"])}">'
        f'<span class="t3">{e(t["label"])}</span><span class="hv" data-k="short">{e(t["short"])}</span></span>'
    )


def host_wall(t):
    """Large host tile for wall mode."""
    return (
        f'<div class="wtile" data-host="{t["id"]}" data-sev="{t["sev"]}" title="{e(t["label"] + " " + t["value"] + " · " + t["sub"])}">'
        f'<div class="wtile-h"><span class="wl">{e(t["label"])}</span><span class="hv" data-k="value">{e(t["value"])}</span></div>'
        f'<div class="hbar"><i class="fill" style="width:{clamp(t["pct"]):.1f}%"></i></div></div>'
    )


def open_button(href):
    if not href or href.startswith("#"):
        return ""
    label = ("Open session" if href.startswith(("claude://", "codex://"))
             else "Open task" if "/code/tasks/" in href else "Open")
    return f'<a class="btn" href="{e(href)}">{label}</a>'


def meta_line(*parts):
    parts = [p for p in parts if p]
    return f'<span class="row-m">{" · ".join(e(p) for p in parts)}</span>' if parts else ""


def actions(html_):
    return f'<div class="acts">{html_}</div>' if html_ else ""


def render_page(host):
    now = dt.datetime.now(dt.timezone.utc)
    sources = {
        os.path.basename(p)[: -len("-state.json")]: load(p, {})
        for p in sorted(glob.glob(os.path.join(DIR, "dashboard", "*-state.json")))
    }
    leases = load(os.path.join(DIR, "leases.json"), {})
    roster = load(os.path.join(DIR, "roster.json"), {})
    registry = machine_config().get("classes") or DEFAULT_REGISTRY
    classes = list(registry)
    budget = leases.get("budget") or {}
    capacity = budget.get("capacity") or {}  # None for a class = unbounded
    queue = leases.get("queue", {})
    projects = {os.path.basename(p)[:-5]: load(p, {}) for p in glob.glob(os.path.join(DIR, "projects", "*.json"))}
    coords = roster.get("coordinators", {})
    members = roster.get("members", {})

    def est_minutes(cls, q):
        """Entry estimate, else the project's median recorded run (3+ runs), else the class maximum."""
        if q.get("minutes"):
            return q["minutes"]
        runs = sorted(((projects.get(q.get("project") or "") or {}).get("classes", {}).get(cls) or {}).get("runMinutes", []))
        return runs[len(runs) // 2] if len(runs) >= 3 else (registry[cls].get("maxMinutes") or 20)  # 0: no limit; 20 min only for the ETA

    eta = {}
    for cls in classes:
        cur = holders(leases, cls)
        ends = sorted(max(now, parse(h["expiresAt"])) for h in cur)
        out = {h["id"]: ("running", None, max(now, parse(h["expiresAt"]))) for h in cur}
        clock = now
        for q in queue.get(cls, []):
            if q.get("hold"):
                out[q["id"]] = ("hold", None, None)
                continue
            while capacity.get(cls) is not None and len(ends) >= max(1, capacity[cls]):
                clock = max(clock, ends.pop(0))
            start = max(now, clock)
            end = start + dt.timedelta(minutes=est_minutes(cls, q))
            ends = sorted(ends + [end])
            out[q["id"]] = ("queued", start, end)
        eta[cls] = out

    def eta_text(cls, entry_id):
        kind, start, end = eta[cls].get(entry_id, (None, None, None))
        if kind == "running":
            return f"ends by {local(end)}"
        if kind == "hold":
            return "on hold"
        if kind == "queued":
            return f"~{local(start)}–{local(end)}"
        return ""

    def task_eta(task_id):
        parts = []
        for cls in classes:
            for h in holders(leases, cls) + queue.get(cls, []):
                name = h.get("holder", "")
                if task_id and (name == task_id or name.startswith(task_id + " ")):
                    parts.append(f"{cls} {eta_text(cls, h['id'])}")
        return "; ".join(parts)

    def settle_left(cls):
        return max([0] + [
            secs - (now - parse(h["grantedAt"])).total_seconds()
            for other, spec in registry.items()
            for secs in [(spec.get("settle") or {}).get(cls, 0)] if secs
            for h in holders(leases, other)
        ])

    def coord_live(c):
        return bool(c.get("heartbeat") and now - parse(c["heartbeat"]) < dt.timedelta(minutes=LIVE_MINUTES))

    def session_of(coord, task_id):
        src = sources.get(coord, {})
        row = next((t for t in src.get("tasks", []) if t.get("id") == task_id), {})
        return row.get("session", "")

    def row(rid, dot, title, when, body, ago_cls="t3", title_cls="t1"):
        """One quiet 36 px row; a click opens its detail. A <details id> so it stays open across body swaps."""
        ago_html = (f'<span class="row-ago {ago_cls}" title="last change {local(when)}">{ago_short(when, now)}</span>'
                    if when else "")
        return (f'<details class="row" id="{rid}"><summary class="row-h"><span class="dot {dot}"></span>'
                f'<span class="row-t {title_cls}">{e(title)}</span>{ago_html}</summary><div class="row-b">{body}</div></details>')

    tasks = {(coord, t.get("id", "")): t for coord, src in sources.items() for t in src.get("tasks", [])}
    member_of = {(coord, m.get("name")): m for coord, mlist in members.items() for m in mlist}

    today = dt.datetime.now().date()

    def park_state(coord, name):
        """None unless parked; else the deadline (a date or None) and whether it has passed."""
        m = member_of.get((coord, name)) or {}
        if m.get("status") != "paused":
            return None
        try:
            until = dt.date.fromisoformat(m["parkedUntil"]) if m.get("parkedUntil") else None
        except ValueError:
            until = None
        return {"until": until, "revisit": bool(until and today > until)}

    def parked_away(coord, name):
        """Parked with no deadline, or before it: kept out of Needs you and the work board."""
        p = park_state(coord, name)
        return bool(p and not p["revisit"])

    def kind_of(t):
        return t.get("kind") if t.get("kind") in ("warn", "work", "ok", "done") else "work"

    def last_update(coord, name):
        m = member_of.get((coord, name)) or {}
        last = m.get("updatedAt") or m.get("joinedAt") or m.get("enrolledAt")
        return parse(last) if last else None

    def priority_of(coord, task_id):
        return (member_of.get((coord, task_id)) or {}).get("priority", 0)

    streams = roster.get("streams", {})

    def stream_of(coord, task_id):
        t = tasks.get((coord, task_id)) or {}
        return t.get("stream") or (member_of.get((coord, task_id)) or {}).get("stream") or ""

    def stream_label(slug):
        return (streams.get(slug) or {}).get("label") or slug

    # ---- needs you: everything that needs a person, one row per task, grouped by why
    needs = {}

    def need(key, sev, reason, **card):
        n = needs.get(key)
        if n is None:
            n = needs[key] = {"sev": sev, "reasons": [], "asks": [], "id": "", "title": "", "status": "", "coord": "", "when": None,
                              "href": "", "stream": ""}
            n.update(card)
        elif SEV_ORDER[sev] < SEV_ORDER[n["sev"]]:
            n["sev"] = sev
        if reason not in n["reasons"]:
            n["reasons"].append(reason)
        return n

    def task_need(coord, task_id, sev, reason):
        t = tasks[(coord, task_id)]
        return need(("task", coord, task_id), sev, reason, id=task_id, title=t.get("name", ""), status=t.get("latest", ""),
                    coord=coord, when=last_update(coord, task_id), href=t.get("session", ""), stream=stream_of(coord, task_id))

    tiles = host_tiles(host)
    for t in tiles:
        if t["sev"] != "ok":
            need(("host", t["id"]), t["sev"], f"Host {t['label'].lower()}", title=f"Host {t['label'].lower()} {t['value']}", status=t["sub"])
    for cls in classes:
        for h in holders(leases, cls):
            if parse(h["expiresAt"]) < now:
                need(("lease", h["id"]), "critical", f"Expired {cls} lease",
                     id=h["id"], title=f"Expired {cls} lease · {h.get('holder', '')}", coord=h.get("coordinator", ""),
                     when=parse(h["expiresAt"]))
    for cls, hold in (leases.get("admission") or {}).items():
        need(("admission", cls), "serious", f"{cls} admission hold",
             title=f"{cls} admission hold · {hold.get('reason', '')}", coord=hold.get("by", ""), when=parse(hold["at"]))
    for name, c in coords.items():
        if not coord_live(c) and c.get("status") != "idle":
            hb = f"Last heartbeat {ago(parse(c['heartbeat']), now)}" if c.get("heartbeat") else "No heartbeat"
            need(("coord", name), "critical", "Stale coordinator", title=f"Stale coordinator {name}", status=hb, coord=name,
                 href=(sources.get(name, {}).get("coordinator") or {}).get("href", ""),
                 when=parse(c["heartbeat"]) if c.get("heartbeat") else None)
    for (coord, task_id), t in tasks.items():
        if kind_of(t) == "warn" and not parked_away(coord, task_id):
            task_need(coord, task_id, "warning", f"Blocked · {t['phase']}" if t.get("phase") else "Blocked")
    for coord, src in sources.items():
        for i, d in enumerate(src.get("decisions", [])):
            if isinstance(d, str):
                task, sep, text = d.partition(":")
                d = {"task": task.strip(), "text": text.strip()} if sep and " " not in task.strip() else {"text": d}
            task = d.get("task", "")
            if parked_away(coord, task):
                continue
            if (coord, task) in tasks:
                n = task_need(coord, task, "serious", "Decision needed")
            else:
                n = need(("decision", coord, i), "serious", "Decision needed", id=task, title=d.get("text", ""), coord=coord,
                         href=session_of(coord, task))
            n["asks"].append({"text": d.get("text", ""), "coord": coord, "id": d.get("id", ""), "options": d.get("options") or []})
            if d.get("href"):
                n["href"] = d["href"]
    for coord, mlist in members.items():
        for m in mlist:
            last = last_update(coord, m.get("name"))
            if m.get("status") in ("done", "paused") or not last or now - last <= dt.timedelta(minutes=STALE_MINUTES):
                continue
            if m.get("status") == "pending":
                need(("member", coord, m["name"]), "warning", f"Not joined · enrolled {ago(last, now)}", id=m["name"],
                     title=m.get("task", ""), status=f"Enrolled by {m.get('parent') or coord}", coord=coord, when=last,
                     stream=m.get("stream", ""))
            elif (coord, m["name"]) in tasks:
                task_need(coord, m["name"], "warning", f"No update for {since(last, now)}")
            else:
                need(("member", coord, m["name"]), "warning", f"No update for {since(last, now)}", id=m["name"],
                     title=m.get("task", ""), coord=coord, when=last, stream=m.get("stream", ""))
    for (coord, name), m in member_of.items():
        p = park_state(coord, name)
        if p and p["revisit"]:
            why = f"Revisit · parked until {p['until'].strftime('%b %-d')}"
            if (coord, name) in tasks:
                task_need(coord, name, "warning", why)
            else:
                need(("member", coord, name), "warning", why, id=name, title=m.get("task", ""), coord=coord,
                     when=last_update(coord, name), stream=m.get("stream", ""))

    def group_of(key, n):
        if key[0] in ("host", "lease", "admission", "coord"):
            return "alarm"
        if n["asks"]:
            return "decision"
        if any(r.startswith("Blocked") for r in n["reasons"]):
            return "blocked"
        if any(r.startswith("Revisit") for r in n["reasons"]):
            return "revisit"
        return "stale"

    def need_order(item):
        """Alarms worst first; inside every group, oldest change first."""
        n = item[1]
        return (SEV_ORDER[n["sev"]] if item[0][0] in ("host", "lease", "admission", "coord") else 0,
                n["when"] is None, n["when"] or now)

    groups = []
    for gkey, label, short, dot, ago_cls in NEED_GROUPS:
        items = sorted(((k, n) for k, n in needs.items() if group_of(k, n) == gkey), key=need_order)
        if items:
            groups.append({"key": gkey, "label": label.format(STALE_MINUTES), "short": short, "dot": dot, "ago": ago_cls,
                           "items": items})
    need_count = len(needs)
    worst = "danger" if any(n["sev"] == "critical" for n in needs.values()) else "warn" if needs else "ok"

    def park_buttons(coord, name):
        """Park (optional deadline) for any member; Unpark when it is parked."""
        if (coord, name) not in member_of:
            return ""
        attrs = f'data-coord="{e(coord)}" data-name="{e(name)}"'
        out = f'<button type="button" class="ghost" data-park="park" {attrs}>Park</button>'
        if park_state(coord, name):
            out += f'<button type="button" class="ghost" data-park="unpark" {attrs}>Unpark</button>'
        return out

    def ask_html(a, title):
        """The question (unless it is the row title), then one button per suggested answer (only for a decision with an id)."""
        out = f'<p class="t1">{e(a["text"])}</p>' if a["text"] and a["text"] != title else ""
        if a["id"] and a["options"]:
            attrs = f'data-coord="{e(a["coord"])}" data-id="{e(a["id"])}"'
            out += '<div class="opts">' + "".join(
                f'<button type="button" class="btn" data-decide="{i}" {attrs}>{e(o)}</button>'
                for i, o in enumerate(a["options"], 1)) + "</div>"
        return out

    def need_row(g, key, n):
        title = n["title"] or n["reasons"][0]
        prio = priority_of(n["coord"], n["id"]) if n["id"] else 0
        meta = meta_line(n["id"], n["coord"], stream_label(n["stream"]) if n["stream"] else "",
                         *[r for r in n["reasons"] if r != title], f"Priority {prio}" if prio else "",
                         f"last change {local(n['when'])}" if n["when"] else "")
        body = (meta + "".join(ask_html(a, title) for a in n["asks"])
                + (f'<p class="t2">{e(n["status"])}</p>' if n["status"] else "")
                + actions(open_button(n["href"]) + park_buttons(n["coord"], n["id"])))
        return row(dom_id("n", *key), g["dot"], title, n["when"], body, g["ago"])

    def need_group(g):
        rows = [need_row(g, key, n) for key, n in g["items"]]
        cap = len(rows) if g["key"] == "alarm" else NEED_CAP
        more = ""
        if len(rows) > cap:
            more = (f'<details class="more" id="more-{g["key"]}"><summary class="ghost" data-more="{len(rows) - cap}"></summary>'
                    f'{"".join(rows[cap:])}</details>')
        return (f'<div class="grp"><div class="grp-h"><span class="grp-l">{e(g["label"])}</span><span class="n">{len(rows)}</span></div>'
                f'{"".join(rows[:cap])}{more}</div>')

    # ---- work board: tasks not under Needs you, grouped by stream; newest change first
    def task_row(coord, t):
        tid = t.get("id", "")
        kind = kind_of(t)
        p = park_state(coord, tid)
        prio = priority_of(coord, tid)
        last = last_update(coord, tid)
        parked = (f"Parked until {p['until'].strftime('%b %-d')}" if p["until"] else "Parked · no deadline") if p else ""
        meta = meta_line(tid, coord, t.get("phase") or KIND_LABEL[kind], f"Priority {prio}" if prio else "", parked,
                         f"last change {local(last)}" if last else "")
        when = task_eta(tid) or t.get("eta", "")
        links = t.get("links", [])
        body = (meta + (f'<p class="t2">{e(t["latest"])}</p>' if t.get("latest") else "")
                + (f'<span class="mono sm t2">{e(when)}</span>' if when else "")
                + (f'<div class="links">{"".join(link(l) for l in links)}</div>' if links else "")
                + actions(open_button(t.get("session", "")) + park_buttons(coord, tid)))
        dot = KIND_DOT[kind] + (" live" if kind in ("work", "ok") and not p else "")
        return row(dom_id("t", coord, tid), dot, t.get("name") or tid, last, body, title_cls="t2")

    def newest_first(x):
        last = last_update(x[0], x[1].get("id", ""))
        return (-priority_of(x[0], x[1].get("id", "")), -(last.timestamp() if last else 0))

    def task_list(items, key):
        open_ = sorted(((c, t) for c, t in items if kind_of(t) != "done"), key=newest_first)
        done = sorted(((c, t) for c, t in items if kind_of(t) == "done"), key=newest_first)
        out = "".join(task_row(c, t) for c, t in open_)
        if done:
            out += (f'<details class="done" id="{dom_id("done", key)}"><summary class="grp-h"><span class="dot done"></span>'
                    f'<span class="grp-l">Done</span><span class="n">{len(done)}</span></summary>'
                    f'{"".join(task_row(c, t) for c, t in done)}</details>')
        return out

    rest = [(coord, t) for (coord, tid), t in tasks.items() if ("task", coord, tid) not in needs and not parked_away(coord, tid)]
    in_stream = {}  # slug -> (open tasks, tasks under Needs you)
    for (coord, tid), t in tasks.items():
        slug = stream_of(coord, tid)
        if kind_of(t) != "done" and not parked_away(coord, tid):
            total, waiting = in_stream.get(slug, (0, 0))
            in_stream[slug] = (total + 1, waiting + (("task", coord, tid) in needs))
    shown = [slug for slug, st in streams.items() if st.get("status") != "closed" or slug in in_stream]
    shown += [slug for slug in in_stream if slug and slug not in streams]
    board = ""
    if shown:
        for slug in shown + [""]:
            items = [(coord, t) for coord, t in rest if stream_of(coord, t.get("id", "")) == slug]
            total, waiting = in_stream.get(slug, (0, 0))
            if not slug and not items:
                continue
            st = streams.get(slug, {})
            head = (
                f'<div class="grp-h"><span class="grp-l">{e(stream_label(slug)) if slug else "No stream"}</span>'
                f'<span class="n">{total}</span>'
                + (f'<span>{e(st["coordinator"])}</span>' if st.get("coordinator") else "")
                + (f'<span class="warn">{waiting} under Needs you</span>' if waiting else "")
                + ('<span>closed</span>' if st.get("status") == "closed" else "") + "</div>"
                + (f'<p class="grp-goal">{e(st["goal"])}</p>' if st.get("goal") else "")
            )
            body = task_list(items, slug or "none") or f'<p class="none">{"All open tasks are under Needs you." if total else "No tasks."}</p>'
            board += f'<div class="grp" id="stream-{e(slug or "none")}">{head}{body}</div>'
    else:
        board = task_list(rest, "all")
    board = board or '<p class="none">No tasks.</p>'
    work_count = sum(1 for _, t in rest if kind_of(t) != "done")

    # ---- parked: out of Needs you and the board until unparked or past their deadline
    parked_rows = []
    for (coord, name), m in member_of.items():
        if not parked_away(coord, name):
            continue
        until = park_state(coord, name)["until"]
        t = tasks.get((coord, name)) or {"id": name, "name": m.get("task", ""), "latest": ""}
        parked_rows.append(((until is None, until or today, name), task_row(coord, t)))
    parked_rows.sort(key=lambda r: r[0])
    parked_html = (
        f'<section class="sec" id="parked"><div class="sec-h"><h2>Parked</h2><span class="n">{len(parked_rows)}</span></div>'
        '<p class="grp-goal">Out of Needs you; a task returns there as Revisit after its date.</p>'
        f'{"".join(r for _, r in parked_rows)}</section>'
        if parked_rows else ""
    )

    # ---- leases: one lane per class, running then queued entries
    leases_on = roster.get("leases") == "on" or any(holders(leases, c) or queue.get(c) for c in classes)
    lease_panel = wall_leases = ""
    if leases_on:
        def lane_status(cls):
            cur, cap = holders(leases, cls), capacity.get(cls)
            ready = [q for q in queue.get(cls, []) if not q.get("hold")]
            queued = f" · {len(ready)} queued" if ready else ""
            if any(parse(h["expiresAt"]) < now for h in cur):
                text, color = "Expired" + queued, "danger"
            elif cur:
                full = cap is not None and len(cur) >= max(1, cap)
                text = (f"Running {len(cur)}/{cap}" if cap and cap > 1 else "Running") + queued
                color = "warn" if full and ready else "t2"
            else:
                text, color = ("Free" + queued, "t3") if ready else ("Free", "ok")
            left = settle_left(cls)
            if left > 0:
                text = f"Settling {int(left)} s · " + text
            return text, color

        def qbutton(action, cls, entry_id, label):
            return (f'<button type="button" class="ghost{" cancel" if action == "unwait" else ""}" data-q="{action}" '
                    f'data-cls="{e(cls)}" data-id="{e(entry_id)}">{label}</button>')

        def requested(minutes, x):
            """Requested time, cores and memory as icon-led HTML; a figure the entry lacks is left out."""
            parts = [(icon("time", "Requested time"), f"{minutes:g}m")]
            parts += [(icon(k, label), f"{fmt(x[k])}{unit}") for k, label, unit in (("cpus", "Cores", ""), ("gib", "Memory", " GiB"))
                      if x.get(k) is not None]
            return "".join(f"<span>{svg}{e(text)}</span>" for svg, text in parts)

        def lane_entries(cls):
            """(pos, holder, duration, duration color, request, detail, commands, buttons) for each held and queued entry."""
            out = []
            for h in holders(leases, cls):
                end = parse(h["expiresAt"])
                left = int((end - now).total_seconds() // 60)
                dur, color = (("expired", "danger") if left < 0 else (f"{left}m left", "t2"))
                mins = h.get("minutes") or (end - parse(h["grantedAt"])).total_seconds() / 60
                out.append((RUNNING, h, dur, color, requested(round(mins), h), eta_text(cls, h["id"]), h.get("commands", ""), ""))
            pos = 0
            for q in queue.get(cls, []):
                pos += 0 if q.get("hold") else 1
                buttons = (qbutton("up", cls, q["id"], "Move up") if pos > 1 and not q.get("hold") else "") + qbutton("unwait", cls, q["id"], "Cancel")
                prio = f"priority {q['priority']} · " if q.get("priority") else ""
                start = eta[cls][q["id"]][1]
                dur = "hold" if q.get("hold") else f"~{local(start)}"
                out.append(("–" if q.get("hold") else str(pos), q, dur, "t3", requested(est_minutes(cls, q), q),
                            f"{prio}{eta_text(cls, q['id'])}", "", buttons))
            return out

        desk_lanes = wall_lanes = ""
        for cls in classes:
            text, color = lane_status(cls)
            cap = capacity.get(cls)
            desc = (f'{registry[cls].get("description", "")} · capacity {cap if cap is not None else "∞"}'
                    f' · peak ~{fmt((budget.get("peakGiB") or {}).get(cls))} GiB'
                    f' · ~{fmt((budget.get("peakCpus") or {}).get(cls))} cores')
            entries = lane_entries(cls)
            rows = "".join(
                f'<details class="row q" id="{dom_id("q", cls, h["id"])}"><summary class="row-h"><span class="q-pos">{pos}</span>'
                f'<span class="q-t"><span class="row-t {"t1" if pos == RUNNING else "t2"}">{e(h.get("holder", ""))}</span>'
                f'<span class="q-req">{req}</span></span>'
                f'<span class="row-ago {dcolor}">{e(dur)}</span></summary><div class="row-b">'
                + meta_line(h.get("coordinator", ""), detail)
                + (f'<span class="mono sm t2 wrap">{e(commands)}</span>' if commands else "")
                + f'<span class="mono sm t3 wrap">{e(h["id"])}</span>{actions(buttons)}</div></details>'
                for pos, h, dur, dcolor, req, detail, commands, buttons in entries)
            desk_lanes += (f'<div class="lane"><div class="lane-h" title="{e(desc)}"><b>{e(cls)}</b><span class="{color}">{e(text)}</span></div>'
                           f'{rows}</div>')
            wall_rows = "".join(
                f'<div class="wq"><span class="q-pos">{pos}</span><span class="q-t"><span class="row-t">{e(h.get("holder", ""))}</span>'
                f'<span class="q-req">{req}</span></span><span class="mono {dcolor}">{e(dur)}</span></div>'
                for pos, h, dur, dcolor, req, *_ in entries)
            wall_lanes += f'<div class="lane"><div class="lane-h"><b>{e(cls)}</b><span class="{color}">{e(text)}</span></div>{wall_rows}</div>'
        ends = [end for cls in classes for kind, _, end in eta[cls].values() if kind == "queued"]
        clears = f"Queue clears ~{local(max(ends))}" if ends else "Queue empty"
        lease_panel = (
            f'<section class="sec leases" id="leases"><div class="sec-h"><h2>Leases</h2>'
            f'<span class="n">{clears}</span></div>{desk_lanes}</section>'
        )
        wall_leases = (f'<section class="w-leases"><div class="lane-h"><span class="wl">Leases</span>'
                       f'<span class="wl t3">{clears}</span></div>{wall_lanes}</section>')

    # ---- coordinators (in the ledger drawer)
    coord_rows = ""
    for name in sorted(set(coords) | set(sources)):
        c, src = coords.get(name, {}), sources.get(name, {})
        live = coord_live(c)
        mlist = members.get(name, [])
        pending = sum(1 for m in mlist if m.get("status") == "pending")
        paused = sum(1 for m in mlist if m.get("status") == "paused")
        href = (src.get("coordinator") or {}).get("href", "")
        label = (f'<a class="c-n" href="{e(href)}" title="Open coordinator session">{e(name)}</a>' if href
                 else f'<span class="c-n">{e(name)}</span>')
        state = (f'<span class="t3">idle{f" · {paused} parked" if paused else ""}</span>' if c.get("status") == "idle"
                 else f'<span class="{"ok" if live else "danger"}">{"live" if live else "stale"}</span>')
        owned = [slug for slug, st in streams.items() if st.get("coordinator") == name and st.get("status") != "closed"]
        links, notes = [link(l) for l in src.get("links", [])], src.get("notes", [])
        coord_rows += (
            f'<div class="coord" id="coord-{e(name)}"><div class="c-h">{label}{state}'
            + ('<span class="t3">general</span>' if c.get("general") else "")
            + f'<span class="c-m">{len(mlist) - pending} members{f" · {pending} pending" if pending else ""} · {e(src.get("updated", "?"))}</span></div>'
            + (f'<p class="c-s">{e(c["focus"])}</p>' if c.get("focus") else "")
            + (f'<p class="c-s">Streams: {e(", ".join(f"{stream_label(s)} ({in_stream.get(s, (0, 0))[0]})" for s in owned))}</p>' if owned else "")
            + (f'<div class="links">{"".join(links)}</div>' if links else "")
            + (f'<ul class="notes">{"".join(f"<li>{e(n)}</li>" for n in notes)}</ul>' if notes else "")
            + "</div>"
        )
    coord_rows = coord_rows or '<p class="none">None</p>'

    # ---- ledger drawer
    ledger = []
    try:
        for line in reversed(open(os.path.join(DIR, "ledger.jsonl")).read().splitlines()[-20:]):
            try:
                ledger.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass

    def entry(x):
        try:
            at = local(parse(x.get("at", "")))
        except (TypeError, ValueError):
            at = str(x.get("at", ""))[11:16]
        return (f'<div class="entry"><span class="mono sm t3">{e(" · ".join(p for p in (at, x.get("by", "")) if p))}</span>'
                f'<p class="t2">{e(x.get("text", ""))}</p></div>')

    ledger_html = "".join(entry(x) for x in ledger) or '<div class="entry t3">Empty</div>'

    header = (
        '<header class="top"><div class="top-l"><span class="brand">Master of puppets</span>'
        f'<span class="live" title="Live · updated {time.strftime("%H:%M:%S")}"></span></div><div class="top-r">'
        f'<div class="minis" id="minis">{"".join(host_mini(t) for t in tiles)}</div>'
        '<div class="modes"><button type="button" class="mode" data-mode-btn="desk">Desk</button>'
        '<button type="button" class="mode" data-mode-btn="wall">Wall</button>'
        '<button type="button" class="ghost" data-ledger-open>Ledger</button></div></div></header>'
    )
    desk = (
        '<main class="desk"><div class="col-main">'
        f'<section class="sec needs"><div class="sec-h"><h2>Needs you</h2><span class="n {worst}">{need_count}</span></div>'
        + ("".join(need_group(g) for g in groups) or '<p class="none">None</p>')
        + f'</section><section class="sec"><div class="sec-h"><h2>Work</h2><span class="n">{work_count}</span></div>{board}</section>'
        f'{parked_html}</div><aside class="col-side">{lease_panel}</aside></main>'
    )
    flat = [(g, n) for g in groups for _, n in g["items"]]
    group_counts = "".join(f'<span><i class="dot {g["dot"]}"></i><b>{len(g["items"])}</b>{e(g["short"])}</span>' for g in groups)
    wall_rows = "".join(
        f'<div class="wn"><span class="dot {g["dot"]}"></span><span class="row-t">{e(n["title"] or n["reasons"][0])}</span>'
        f'<span class="mono {g["ago"]}">{ago_short(n["when"], now) if n["when"] else ""}</span></div>'
        for g, n in flat[:WALL_ROWS])
    wall_more = f'<div class="wn t3">{len(flat) - WALL_ROWS} more</div>' if len(flat) > WALL_ROWS else ""
    wall = (
        f'<main class="wall"><div class="w-host">{"".join(host_wall(t) for t in tiles)}</div><div class="w-body">'
        f'<section class="w-needs"><div class="w-count"><div class="w-big"><b class="{worst}">{need_count}</b><span>Needs you</span></div>'
        f'<div class="w-groups">{group_counts}</div></div>'
        f'<div class="w-list">{wall_rows}{wall_more}</div></section>{wall_leases}</div></main>'
    )
    drawer = (
        '<div class="scrim" data-ledger-close></div><aside class="drawer" aria-label="Ledger"><div class="drawer-h">'
        '<span class="brand">Ledger</span><button type="button" class="ghost" data-ledger-close>Close</button></div>'
        f'<div class="drawer-b"><div class="coords"><span class="sub">Coordinators</span>{coord_rows}</div>{ledger_html}</div></aside>'
    )
    with open(PAGE) as f:
        return f.read().replace("{{BODY}}", header + desk + wall + drawer)


# ---------------------------------------------------------------- server

version = 0
page = b""
page_hash = None
host = {}
host_version = 0
changed = threading.Condition()


def inputs():
    paths = [os.path.join(DIR, n) for n in ("leases.json", "roster.json", "ledger.jsonl", "config.json")]
    paths += glob.glob(os.path.join(DIR, "projects", "*.json")) + glob.glob(os.path.join(DIR, "dashboard", "*-state.json"))
    out = []
    for p in paths:
        try:
            out.append((p, os.stat(p).st_mtime_ns))
        except OSError:
            out.append((p, 0))
    return out


def rerender():
    global version, page, page_hash
    try:
        body = render_page(host).encode()
    except Exception as exc:  # keep serving the last good page
        print(f"render failed: {exc!r}", file=sys.stderr, flush=True)
        return
    # The timestamp alone must not trigger an update.
    digest = hashlib.sha256(re.sub(rb"updated [0-9:]+", b"", body)).hexdigest()
    with changed:
        page = body
        if digest != page_hash:
            page_hash = digest
            version += 1
            changed.notify_all()


def watcher():
    last, forced = None, 0.0
    while True:
        cur = inputs()
        if cur != last or time.time() - forced >= FORCE_EVERY:
            rerender()
            last, forced = cur, time.time()
        time.sleep(1)


def host_sampler():
    global host, host_version
    prev, last = swapouts(), time.time()
    while True:
        try:
            sample, prev_new = sample_host(prev, max(1.0, time.time() - last))
        except Exception as exc:  # keep sampling; show the failure on the page
            sample, prev_new = {"at": time.strftime("%H:%M:%S"), "error": str(exc)[:200]}, prev
        prev, last = prev_new, time.time()
        sample["tiles"] = host_tiles(sample)
        with changed:
            host = sample
            host_version += 1
            changed.notify_all()
        time.sleep(HOST_EVERY)


COORDINATOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coordinator.py")
QUEUE_ACTIONS = ("up", "unwait")
ENTRY_ID = re.compile(r"^[\w.:@-]{1,200}$")


def queue_action(action, cls, entry_id):
    """Run `coordinator.py up|unwait CLASS --id ID --notify`; returns (ok, output lines)."""
    if action not in QUEUE_ACTIONS or cls not in (machine_config().get("classes") or DEFAULT_REGISTRY) or not ENTRY_ID.match(entry_id):
        return False, ["bad request"]
    try:
        r = subprocess.run([sys.executable, "-I", COORDINATOR, action, cls, "--id", entry_id, "--notify"],
                           capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, [f"coordinator.py failed: {exc}"]
    lines = [x for x in (r.stdout + r.stderr).splitlines() if x.strip()]
    return r.returncode == 0, lines or [f"coordinator.py exit {r.returncode}"]


PARK_ACTIONS = ("park", "unpark")
NAME = re.compile(r"^[\w.:@-]{1,200}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def park_action(action, coord, name, until):
    """Run `coordinator.py park|unpark --coordinator C --name N [--until D] --notify`."""
    if action not in PARK_ACTIONS or not NAME.match(coord) or not NAME.match(name) or (until and not DATE.match(until)):
        return False, ["bad request"]
    cmd = [sys.executable, "-I", COORDINATOR, action, "--coordinator", coord, "--name", name, "--notify"]
    if action == "park" and until:
        cmd += ["--until", until]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, [f"coordinator.py failed: {exc}"]
    lines = [x for x in (r.stdout + r.stderr).splitlines() if x.strip()]
    return r.returncode == 0, lines or [f"coordinator.py exit {r.returncode}"]


DECISION_ID = re.compile(r"^[0-9a-f]{8}$")


def decide_action(coord, decision_id, choice):
    """Run `coordinator.py decision answer --by C --id ID --choice N --notify`."""
    if not NAME.match(coord) or not DECISION_ID.match(decision_id) or not (isinstance(choice, int) and 1 <= choice <= 9):
        return False, ["bad request"]
    cmd = [sys.executable, "-I", COORDINATOR, "decision", "answer", "--by", coord, "--id", decision_id,
           "--choice", str(choice), "--notify"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, [f"coordinator.py failed: {exc}"]
    lines = [x for x in (r.stdout + r.stderr).splitlines() if x.strip()]
    return r.returncode == 0, lines or [f"coordinator.py exit {r.returncode}"]


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def same_origin(self):
        """Only this page may post: the Host and Origin must be this server, and the custom
        header forces a CORS preflight, which this server never answers."""
        local = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
        origin = self.headers.get("Origin", "")
        return (self.headers.get("Host") in local and origin in {f"http://{h}" for h in local}
                and self.headers.get("X-Requested-By") == "dashboard"
                and self.headers.get("Content-Type", "").startswith("application/json"))

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/queue", "/park", "/decide"):
            self.send_response(404)
            self.end_headers()
            return
        if not self.same_origin():
            self.send_response(403)
            self.end_headers()
            return
        try:
            req = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096)))
            if path == "/decide":
                choice = req.get("choice")
                ok, lines = decide_action(str(req.get("coord", "")), str(req.get("id", "")),
                                          choice if type(choice) is int else None)
            elif path == "/park":
                ok, lines = park_action(str(req.get("action", "")), str(req.get("coord", "")), str(req.get("name", "")),
                                        str(req.get("until") or ""))
            else:
                ok, lines = queue_action(str(req.get("action", "")), str(req.get("cls", "")), str(req.get("id", "")))
        except (ValueError, AttributeError):
            ok, lines = False, ["bad request"]
        self.send(json.dumps({"ok": ok, "lines": lines}).encode(), "application/json", 200 if ok else 400)

    def send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self.send(page or render_page(host).encode(), "text/html; charset=utf-8")
        elif path == "/host.json":
            self.send(json.dumps(host).encode(), "application/json")
        elif path == "/health":
            self.send(f"ok {version}".encode(), "text/plain")
        elif path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen, seen_host = version, -1
            try:
                while True:
                    with changed:
                        if seen == version and seen_host == host_version:
                            changed.wait(timeout=15)
                        cur, cur_host, sample = version, host_version, host
                    sent = False
                    if cur != seen:
                        self.wfile.write(f"event: update\ndata: {cur}\n\n".encode())
                        seen, sent = cur, True
                    if cur_host != seen_host and sample:
                        self.wfile.write(f"event: host\ndata: {json.dumps(sample)}\n\n".encode())
                        seen_host, sent = cur_host, True
                    if not sent:
                        self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self.send_response(404)
            self.end_headers()


def already_serving():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
            return r.read().startswith(b"ok")
    except OSError:
        return False


def main():
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        if already_serving():
            print(f"already serving: http://localhost:{PORT}/")
            return 0
        print(f"port {PORT} is in use by something else", file=sys.stderr)
        return 1
    server.daemon_threads = True
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    threading.Thread(target=host_sampler, daemon=True).start()
    threading.Thread(target=watcher, daemon=True).start()
    print(f"dashboard: http://localhost:{PORT}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
