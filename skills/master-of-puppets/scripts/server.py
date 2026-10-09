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
  /            the page (shell: dashboard.html). Desk mode: host meters in the header,
               "Needs you" first (worst first), the work board, then lease timelines,
               queues and coordinators; the ledger opens in a drawer. Wall mode: the
               same, large, for a shared screen (add ?mode=wall to the URL)
  POST /queue  {"action": "up"|"unwait", "cls", "id"} from the page's Move up and Cancel
               buttons: runs `lease.py <action> CLASS --id ID --notify`, which tells each
               affected coordinator. Same-origin JSON with X-Requested-By only.
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
    "BUILD": {"description": "builds, typecheck, lint/format, tests, codegen", "defaultGiB": 10, "maxMinutes": 20, "settle": {}},
    "E2E": {"description": "local servers/stacks and interacting with them", "defaultGiB": 8, "maxMinutes": 45, "settle": {"BUILD": 60}},
}
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
    return out, cur


SEV_ORDER = {"critical": 0, "serious": 1, "warning": 2, "ok": 3}
STALE_MINUTES = 30
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
KINDS = [("warn", "blocked", "Blocked"), ("work", "progress", "In progress"), ("ok", "ontrack", "On track"), ("done", "done", "Done")]


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
         "short": f"{f(h.get('cpuPct'), '%')} · load {f(h['load1'])}",
         "sub": f"load {f(h['load1'])} of {f(h['maxLoad'])} · {h['cores']} cores",
         "sev": "critical" if load_ratio >= 1 else "warning" if load_ratio >= 0.8 else "ok"},
        {"id": "memory", "label": "Memory", "value": f"{f(h.get('memUsedGiB'))} GiB", "pct": mem_pct,
         "short": f"{f(h.get('memUsedGiB'))} / {f(h['memTotalGiB'])}G",
         "sub": f"of {f(h['memTotalGiB'])} GiB · {f(h.get('memFreePct'), '%')} free · reserve {f(h['reserveGiB'])} GiB",
         "sev": "critical" if mem_pct >= 90 else "warning" if mem_pct >= 80 else "ok"},
        {"id": "swap", "label": "Swap", "value": f"{f(h.get('swapUsedGiB'))} GiB", "pct": swap_pct,
         "short": f"{f(h.get('swapUsedGiB'))} / {f(h.get('swapTotalGiB'))}G",
         "sub": f"of {f(h.get('swapTotalGiB'))} GiB · {f(outs)} swap-outs/12 s (max {max_outs})",
         "sev": "critical" if outs is not None and outs >= max_outs else "warning" if outs is not None and outs >= max_outs / 2 else "ok"},
        {"id": "disk", "label": "Disk", "value": f"{f(h['diskFreeGiB'])} GiB free", "pct": disk_pct,
         "short": f"{f(h['diskFreeGiB'])}G free",
         "sub": f"of {f(h['diskTotalGiB'])} GiB · floor {f(h['diskFloorGiB'])} GiB",
         "sev": "critical" if h["diskFreeGiB"] < h["diskFloorGiB"] else "warning" if h["diskFreeGiB"] < 2 * h["diskFloorGiB"] else "ok"},
    ]


# ---------------------------------------------------------------- rendering

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
    return "just now" if mins < 1 else f"{mins}m ago" if mins < 60 else f"{mins // 60}h {mins % 60}m ago"


def link(item):
    return f'<a href="{e(item["href"])}">{e(item["label"])}</a>'


def agent_class(tool):
    tool = (tool or "").lower()
    return "ag-claude" if "claude" in tool else "ag-codex" if "codex" in tool else "ag-other"


def clamp(pct):
    return max(0.0, min(100.0, float(pct)))


def host_mini(t):
    """Compact host meter for the header; the page script repaints it on each host event."""
    return (
        f'<div class="mini" data-host="{t["id"]}" data-sev="{t["sev"]}" title="{e(t["label"] + " " + t["value"] + " · " + t["sub"])}">'
        f'<div class="vbar"><i class="fill" data-axis="h" style="height:{clamp(t["pct"]):.1f}%"></i></div>'
        f'<div class="mini-t"><span class="cap">{e(t["label"])}</span><span class="hv" data-k="short">{e(t["short"])}</span></div></div>'
    )


def host_wall(t):
    """Large host tile for wall mode."""
    return (
        f'<div class="wtile" data-host="{t["id"]}" data-sev="{t["sev"]}"><span class="wl">{e(t["label"])}</span>'
        f'<span class="hv" data-k="value">{e(t["value"])}</span>'
        f'<div class="hbar"><i class="fill" style="width:{clamp(t["pct"]):.1f}%"></i></div>'
        f'<span class="hd" data-k="sub">{e(t["sub"])}</span></div>'
    )


def open_button(href):
    if not href or href.startswith("#"):
        return ""
    label = "Open session" if href.startswith(("claude://", "codex://")) else "Open"
    return f'<a class="btn" href="{e(href)}">{label}</a>'


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
        return runs[len(runs) // 2] if len(runs) >= 3 else registry[cls].get("maxMinutes", 20)

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

    def tool_of(coord):
        return coords.get(coord, {}).get("tool") or coord

    def who(coord, when=None):
        """Agent swatch and name, then the time of the last change."""
        out = f'<span class="agent {agent_class(tool_of(coord))}"><i class="sw"></i>{e(coord)}</span>' if coord else ""
        if when:
            out += f'<span class="when">{local(when)} · {ago_short(when, now)}</span>'
        return f'<div class="who">{out}</div>' if out else ""

    tasks = {(coord, t.get("id", "")): t for coord, src in sources.items() for t in src.get("tasks", [])}
    member_of = {(coord, m.get("name")): m for coord, mlist in members.items() for m in mlist}

    def kind_of(t):
        return t.get("kind") if t.get("kind") in ("warn", "work", "ok", "done") else "work"

    def last_update(coord, name):
        m = member_of.get((coord, name)) or {}
        last = m.get("updatedAt") or m.get("joinedAt") or m.get("enrolledAt")
        return parse(last) if last else None

    # ---- needs you: everything that needs a person, one card per task, worst first
    needs = {}

    def need(key, sev, reason, **card):
        n = needs.get(key)
        if n is None:
            n = needs[key] = {"sev": sev, "reasons": [], "asks": [], "id": "", "title": "", "status": "", "coord": "", "when": None, "href": ""}
            n.update(card)
        elif SEV_ORDER[sev] < SEV_ORDER[n["sev"]]:
            n["sev"] = sev
        if reason not in n["reasons"]:
            n["reasons"].append(reason)
        return n

    def task_need(coord, task_id, sev, reason):
        t = tasks[(coord, task_id)]
        return need(("task", coord, task_id), sev, reason, id=task_id, title=t.get("name", ""), status=t.get("latest", ""),
                    coord=coord, when=last_update(coord, task_id), href=t.get("session", ""))

    tiles = host_tiles(host)
    for t in tiles:
        if t["sev"] != "ok":
            need(("host", t["id"]), t["sev"], f"Host {t['label'].lower()}", title=t["value"], status=t["sub"])
    for cls in classes:
        for h in holders(leases, cls):
            if parse(h["expiresAt"]) < now:
                need(("lease", h["id"]), "critical", f"Expired {cls} lease · {ago(parse(h['expiresAt']), now)}",
                     id=h["id"], title=h.get("holder", ""), coord=h.get("coordinator", ""))
    for name, c in coords.items():
        if not coord_live(c):
            hb = f"Last heartbeat {ago(parse(c['heartbeat']), now)}" if c.get("heartbeat") else "No heartbeat"
            need(("coord", name), "critical", "Stale coordinator", title=name, status=hb, coord=name,
                 href=(sources.get(name, {}).get("coordinator") or {}).get("href", ""))
    for (coord, task_id), t in tasks.items():
        if kind_of(t) == "warn":
            task_need(coord, task_id, "warning", f"Blocked · {t['phase']}" if t.get("phase") else "Blocked")
    for coord, src in sources.items():
        for i, d in enumerate(src.get("decisions", [])):
            if isinstance(d, str):
                task, sep, text = d.partition(":")
                d = {"task": task.strip(), "text": text.strip()} if sep and " " not in task.strip() else {"text": d}
            task = d.get("task", "")
            if (coord, task) in tasks:
                n = task_need(coord, task, "serious", "Decision needed")
            else:
                n = need(("decision", coord, i), "serious", "Decision needed", id=task, coord=coord, href=session_of(coord, task))
            n["asks"].append(d.get("text", ""))
            if d.get("href"):
                n["href"] = d["href"]
    for coord, mlist in members.items():
        for m in mlist:
            last = last_update(coord, m.get("name"))
            if m.get("status") in ("done", "paused") or not last or now - last <= dt.timedelta(minutes=STALE_MINUTES):
                continue
            if m.get("status") == "pending":
                need(("member", coord, m["name"]), "warning", f"Not joined · enrolled {ago(last, now)}", id=m["name"],
                     title=m.get("task", ""), status=f"Enrolled by {m.get('parent') or coord}", coord=coord, when=last)
            elif (coord, m["name"]) in tasks:
                task_need(coord, m["name"], "warning", f"No update for {since(last, now)}")
            else:
                need(("member", coord, m["name"]), "warning", f"No update for {since(last, now)}", id=m["name"],
                     title=m.get("task", ""), coord=coord, when=last)
    need_list = sorted(needs.values(), key=lambda n: SEV_ORDER[n["sev"]])
    worst = "danger" if any(n["sev"] == "critical" for n in need_list) else "warn" if need_list else "ok"

    def reasons_html(n):
        return f'<div class="reasons">{"".join(f"<span>{e(r)}</span>" for r in n["reasons"])}</div>'

    def need_card(n):
        idl = (f'<span class="id">{e(n["id"])}</span>' if n["id"] else "") + (f'<span class="ttl">{e(n["title"])}</span>' if n["title"] else "")
        side = who(n["coord"], n["when"]) + open_button(n["href"])
        return (
            f'<article class="need{" critical" if n["sev"] == "critical" else ""}"><div class="need-main">{reasons_html(n)}'
            + (f'<div class="idl">{idl}</div>' if idl else "")
            + "".join(f'<p class="t1">{e(a)}</p>' for a in n["asks"] if a)
            + (f'<p class="st">{e(n["status"])}</p>' if n["status"] else "")
            + "</div>" + (f'<div class="need-side">{side}</div>' if side else "") + "</article>"
        )

    def wall_card(n):
        ident = f'<span class="id">{e(n["id"])}</span>' if n["id"] else ""
        agent = f'<div class="agent {agent_class(tool_of(n["coord"]))}"><i class="sw"></i>{e(n["coord"])}</div>' if n["coord"] else ""
        return (f'<article class="wneed{" critical" if n["sev"] == "critical" else ""}">{reasons_html(n)}'
                f'<div class="wt">{ident}{e(n["title"])}</div>{agent}</article>')

    # ---- work board: tasks not under Needs you, grouped by work state
    def task_row(coord, t):
        tid = t.get("id", "")
        name = e(t.get("name", ""))
        title = (f'<a class="ttl" href="{e(t["session"])}" title="Open session">{name}</a>' if t.get("session")
                 else f'<span class="ttl">{name}</span>')
        meta = [f'<span class="t1">{e(t["phase"])}</span>'] if t.get("phase") else []
        when = task_eta(tid) or t.get("eta", "")
        if when:
            meta.append(f'<span class="mono t2">{e(when)}</span>')
        meta += [link(l) for l in t.get("links", [])]
        return (
            f'<article class="row{" done" if kind_of(t) == "done" else ""}"><div class="row-main">'
            f'<div class="idl"><span class="id">{e(tid)}</span>{title}</div>'
            + (f'<p class="st">{e(t["latest"])}</p>' if t.get("latest") else "")
            + (f'<div class="meta">{"".join(meta)}</div>' if meta else "")
            + f"</div>{who(coord, last_update(coord, tid))}</article>"
        )

    rest = [(coord, t) for (coord, tid), t in tasks.items() if ("task", coord, tid) not in needs]
    listed = sum(1 for k in needs if k[0] == "task")
    board = ""
    for kind, dot, label in KINDS:
        rows = [task_row(coord, t) for coord, t in rest if kind_of(t) == kind]
        if not rows:
            continue
        head = f'<span class="dot {dot}"></span>{label}<span class="n">{len(rows)}</span>'
        inner = f'<div class="card list">{"".join(rows)}</div>'
        board += (f'<details class="grp" id="grp-done"><summary class="grp-h">{head}</summary>{inner}</details>' if kind == "done"
                  else f'<div class="grp"><div class="grp-h">{head}</div>{inner}</div>')
    board = board or '<p class="t3">No tasks.</p>'
    work_note = f"{len(rest)} tasks" + (f" · {listed} under Needs you" if listed else "")

    # ---- leases: a timeline per class, then every held and queued entry
    leases_on = roster.get("leases") == "on" or any(holders(leases, c) or queue.get(c) for c in classes)
    lease_panel = wall_leases = ""
    if leases_on:
        spans = {}
        for cls in classes:
            items = []
            for h in holders(leases, cls):
                end = parse(h["expiresAt"])
                start = parse(h["grantedAt"]) if h.get("grantedAt") else now
                items.append(("expired" if end < now else "run", "", start, max(now, end), h))
            pos = 0
            for q in queue.get(cls, []):
                kind, start, end = eta[cls].get(q["id"], (None, None, None))
                if kind == "queued":
                    pos += 1
                    items.append(("queued", f"#{pos}", start, end, q))
            spans[cls] = items
        w0 = now - dt.timedelta(minutes=5)
        last_end = max([i[3] for items in spans.values() for i in items] + [w0])
        span = max(30, min(120, -(-int((last_end - w0).total_seconds()) // 300) * 5))
        step = 5 if span <= 40 else 10 if span <= 80 else 15
        w1 = w0 + dt.timedelta(minutes=span)

        def pct(t):
            return clamp((t - w0) / (w1 - w0) * 100)

        lw = w0.astimezone().replace(second=0, microsecond=0)
        tick = lw + dt.timedelta(minutes=step - lw.minute % step)
        ticks = []
        while tick < w1:
            ticks.append((pct(tick), tick.strftime("%H:%M")))
            tick += dt.timedelta(minutes=step)
        tick_lines = "".join(f'<span class="tk" style="left:{p:.2f}%"></span>' for p, _ in ticks)
        tick_labels = "".join(f'<span style="left:{p:.2f}%">{label}</span>' for p, label in ticks)
        now_line = f'<span class="now" style="left:{pct(now):.2f}%"></span>'

        def track(cls, big=False):
            blocks = ""
            for kind, pos, start, end, h in spans[cls]:
                if end <= w0 or start >= w1:
                    continue
                left, right = pct(start), pct(end)
                title = f'{h.get("holder", "")} · {h["id"]} · {local(start)}–{local(end)}'
                blocks += (
                    f'<div class="blk {kind} {agent_class(tool_of(h.get("coordinator", "")))}" title="{e(title)}" '
                    f'style="left:{left:.2f}%;width:calc({right - left:.2f}% - 2px)">'
                    + (f"<b>{pos}</b>" if pos else "") + f'<span>{e(h.get("holder", "").split(" ")[0])}</span></div>'
                )
            return f'<div class="track{" big" if big else ""}">{tick_lines}{blocks}{now_line}</div>'

        def lane_status(cls):
            cur, cap = holders(leases, cls), capacity.get(cls)
            ready = [q for q in queue.get(cls, []) if not q.get("hold")]
            queued = f" · {len(ready)} queued" if ready else ""
            if any(parse(h["expiresAt"]) < now for h in cur):
                text, color = "Expired" + queued, "danger"
            elif cur:
                full = cap is not None and len(cur) >= max(1, cap)
                text = (f"Held {len(cur)}/{cap}" if cap and cap > 1 else "Held") + queued
                color = "warn" if full and ready else "t1"
            else:
                text, color = "Free" + queued, "t2" if ready else "ok"
            left = settle_left(cls)
            if left > 0:
                text = f"Settling {int(left)} s · " + text
            return text, color

        def qbutton(action, cls, entry_id, label):
            return (f'<button type="button" class="ghost{" cancel" if action == "unwait" else ""}" data-q="{action}" '
                    f'data-cls="{e(cls)}" data-id="{e(entry_id)}">{label}</button>')

        def qrow(cls, tag, h, detail, commands="", actions=""):
            task, _, what = h.get("holder", "").partition(" ")
            return (
                f'<div class="qrow"><span class="q-pos">{e(cls)} {e(tag)}</span><div class="q-b">'
                f'<span><b>{e(task)}</b> <span class="t2">{e(what)}</span></span>'
                f'<span class="sm t3">{e(h.get("coordinator", ""))} · {e(detail)}</span>'
                + (f'<span class="mono xs t2 wrap">{e(commands)}</span>' if commands else "")
                + f'<span class="mono xs t3 wrap">{e(h["id"])}</span>'
                + (f'<div class="q-act">{actions}</div>' if actions else "") + "</div></div>"
            )

        desk_lanes, wall_lanes, qrows = f'<span></span><div class="ticks">{tick_labels}</div>', "", ""
        for cls in classes:
            text, color = lane_status(cls)
            cap = capacity.get(cls)
            desc = (f'{registry[cls].get("description", "")} · capacity {cap if cap is not None else "∞"}'
                    f' · peak ~{fmt((budget.get("peakGiB") or {}).get(cls))} GiB')
            desk_lanes += f'<div class="lane-l" title="{e(desc)}"><b>{e(cls)}</b><span class="{color}">{e(text)}</span></div>{track(cls)}'
            wall_lanes += f'<div class="blane"><div class="blane-h"><b>{e(cls)}</b><span class="{color}">{e(text)}</span></div>{track(cls, True)}</div>'
            for h in holders(leases, cls):
                qrows += qrow(cls, "held", h, f'{fmt(h.get("gib"))} GiB · {eta_text(cls, h["id"])}', h.get("commands", ""))
            pos = 0
            for q in queue.get(cls, []):
                pos += 0 if q.get("hold") else 1
                actions = (qbutton("up", cls, q["id"], "Move up") if pos > 1 and not q.get("hold") else "") + qbutton("unwait", cls, q["id"], "Cancel")
                qrows += qrow(cls, "hold" if q.get("hold") else f"#{pos}", q, f"~{est_minutes(cls, q):g} min · {eta_text(cls, q['id'])}",
                              actions=actions)
        qrows = qrows or '<div class="qempty sm t3">Nothing queued.</div>'
        lease_panel = (
            f'<section class="card panel" id="leases"><div class="panel-h"><h2>Leases</h2>'
            f'<span class="sm t3">FIFO · {fmt(budget.get("freeGiB"))} of {fmt(budget.get("limitGiB"))} GiB free</span></div>'
            f'<div class="lanes">{desk_lanes}</div><div>{qrows}</div></section>'
        )
        wall_leases = f'<section class="w-leases"><h2>Leases</h2>{wall_lanes}<div class="ticks big">{tick_labels}</div></section>'

    # ---- coordinators
    coord_rows = ""
    for name in sorted(set(coords) | set(sources)):
        c, src = coords.get(name, {}), sources.get(name, {})
        live = coord_live(c)
        mlist = members.get(name, [])
        pending = sum(1 for m in mlist if m.get("status") == "pending")
        href = (src.get("coordinator") or {}).get("href", "")
        label = (f'<a class="c-n" href="{e(href)}" title="Open coordinator session">{e(name)}</a>' if href
                 else f'<span class="c-n">{e(name)}</span>')
        links, notes = [link(l) for l in src.get("links", [])], src.get("notes", [])
        more = ""
        if links or notes:
            summary = " · ".join(([f"Links ({len(links)})"] if links else []) + ([f"Notes ({len(notes)})"] if notes else []))
            more = (
                f'<details id="coord-more-{e(name)}"><summary class="ghost"><span class="cl">{summary}</span><span class="op">Hide</span></summary>'
                + (f'<div class="links">{"".join(links)}</div>' if links else "")
                + (f'<ul class="notes">{"".join(f"<li>{e(n)}</li>" for n in notes)}</ul>' if notes else "")
                + "</details>"
            )
        coord_rows += (
            f'<div class="coord" id="coord-{e(name)}"><div class="c-h"><i class="sw {agent_class(tool_of(name))}"></i>{label}'
            f'<span class="sm {"ok" if live else "danger"}">{"live" if live else "stale"}</span>'
            f'<span class="c-m">{len(mlist) - pending} members{f" · {pending} pending" if pending else ""}'
            f' · <span class="mono">{e(src.get("updated", "?"))}</span></span></div>'
            + (f'<p class="c-s">{e(c["focus"])}</p>' if c.get("focus") else "") + more + "</div>"
        )
    coord_rows = coord_rows or '<p class="coord t3">None</p>'

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
        by = x.get("by", "")
        return (f'<div class="entry"><div class="entry-h"><span class="mono t3">{e(at)}</span>'
                f'<i class="sw {agent_class(tool_of(by))}"></i><b>{e(by)}</b></div><p class="st">{e(x.get("text", ""))}</p></div>')

    ledger_html = "".join(entry(x) for x in ledger) or '<div class="entry t3">Empty</div>'

    header = (
        '<header class="top"><div class="top-l"><span class="brand">Master of puppets</span><span class="live"></span>'
        f'<span class="mono sm t3">updated {time.strftime("%H:%M:%S")}</span></div><div class="top-r">'
        f'<div class="minis" id="minis">{"".join(host_mini(t) for t in tiles)}</div>'
        '<div class="seg"><button type="button" data-mode-btn="desk">Desk</button><button type="button" data-mode-btn="wall">Wall</button></div>'
        f'<button type="button" class="btn" data-ledger-open>Ledger<span class="mono sm t3">{len(ledger)}</span></button></div></header>'
    )
    desk = (
        '<main class="desk"><div class="col-main">'
        f'<section class="sec"><div class="sec-h"><h2>Needs you</h2><span class="mono sm {worst}">{len(need_list)}</span>'
        f'<span class="sm t3">Alarms, decisions, blocked tasks, or no update for {STALE_MINUTES} min</span></div>'
        + ("".join(need_card(n) for n in need_list) or '<div class="empty">Nothing needs you right now.</div>')
        + f'</section><section class="sec work"><div class="sec-h"><h2>Work</h2><span class="sm t3">{e(work_note)}</span></div>{board}</section></div>'
        f'<aside class="col-side">{lease_panel}<section class="card coords"><h2>Coordinators</h2>{coord_rows}</section></aside></main>'
    )
    counts = "".join(
        f'<div class="count"><b>{sum(1 for t in tasks.values() if kind_of(t) == kind)}</b><span><span class="dot {dot}"></span>{label}</span></div>'
        for kind, dot, label in KINDS[:3]
    )
    wall = (
        f'<main class="wall"><div class="w-host">{"".join(host_wall(t) for t in tiles)}</div>'
        f'<section class="w-needs"><div class="w-count"><b class="{worst}">{len(need_list)}</b>'
        f'<span>{"needs you" if len(need_list) == 1 else "need you"}</span></div>'
        + "".join(wall_card(n) for n in need_list)
        + f'<div class="counts">{counts}</div></section>{wall_leases}</main>'
    )
    drawer = (
        '<div class="scrim" data-ledger-close></div><aside class="drawer" aria-label="Ledger"><div class="drawer-h">'
        '<div class="sec-h"><span class="brand">Ledger</span><span class="sm t3">All coordinators · newest first</span></div>'
        f'<button type="button" class="ghost" data-ledger-close>Close</button></div><div class="drawer-b">{ledger_html}</div></aside>'
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


LEASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lease.py")
QUEUE_ACTIONS = ("up", "unwait")
ENTRY_ID = re.compile(r"^[\w.:@-]{1,200}$")


def queue_action(action, cls, entry_id):
    """Run `lease.py up|unwait CLASS --id ID --notify`; returns (ok, output lines)."""
    if action not in QUEUE_ACTIONS or cls not in (machine_config().get("classes") or DEFAULT_REGISTRY) or not ENTRY_ID.match(entry_id):
        return False, ["bad request"]
    try:
        r = subprocess.run([sys.executable, "-I", LEASE, action, cls, "--id", entry_id, "--notify"],
                           capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, [f"lease.py failed: {exc}"]
    lines = [x for x in (r.stdout + r.stderr).splitlines() if x.strip()]
    return r.returncode == 0, lines or [f"lease.py exit {r.returncode}"]


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
        if self.path.split("?")[0] != "/queue":
            self.send_response(404)
            self.end_headers()
            return
        if not self.same_origin():
            self.send_response(403)
            self.end_headers()
            return
        try:
            req = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096)))
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
