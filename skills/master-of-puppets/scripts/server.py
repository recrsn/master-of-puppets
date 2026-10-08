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
  /            the page: what needs attention first (one hero count, worst first),
               then machine meters, lease tiles, the work board, queues and the ledger
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
SEV_LABEL = {"critical": "Critical", "serious": "Serious", "warning": "Warning", "ok": "OK"}
ICONS = {
    "critical": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.2 1h5.6L15 5.2v5.6L10.8 15H5.2L1 10.8V5.2z"/><path class="g" d="M7.2 4h1.6v5H7.2zM7.2 10.5h1.6v1.6H7.2z"/></svg>',
    "serious": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1l7.5 13.5H.5z"/><path class="g" d="M7.2 5.5h1.6v4.5H7.2zM7.2 11h1.6v1.6H7.2z"/></svg>',
    "warning": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7"/><path class="g" d="M7.2 4h1.6v5H7.2zM7.2 10.5h1.6v1.6H7.2z"/></svg>',
    "ok": '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7"/><path class="g" d="M6.9 10.9L4.1 8.1l1.1-1.1 1.7 1.7 3.9-3.9 1.1 1.1z"/></svg>',
}


def status(sev):
    """Severity icon; the name is the accessible label and hover title, never shown as text."""
    return f'<span class="st {sev}" role="img" aria-label="{SEV_LABEL[sev]}" title="{SEV_LABEL[sev]}">{ICONS[sev]}</span>'


def host_tiles(h):
    """Four host tiles: id, label, value, sub, meter percent, severity. Sent with each host event."""
    if not h or h.get("error"):
        why = (h or {}).get("error", "waiting for the first sample")
        return [{"id": k, "label": k.title(), "value": "…", "sub": why, "pct": 0, "sev": "ok"} for k in ("cpu", "memory", "swap", "disk")]

    def f(v, unit=""):
        return "?" if v is None else f"{v:g}{unit}" if isinstance(v, (int, float)) else f"{v}{unit}"

    load_ratio = (h["load1"] / h["maxLoad"]) if h.get("maxLoad") else 0
    mem_pct = 100 - h["memFreePct"] if h.get("memFreePct") is not None else 0
    swap_pct = 100 * h["swapUsedGiB"] / h["swapTotalGiB"] if h.get("swapTotalGiB") else 0
    disk_pct = 100 * (1 - h["diskFreeGiB"] / h["diskTotalGiB"]) if h.get("diskTotalGiB") else 0
    outs, max_outs = h.get("swapoutsPer12s"), h.get("maxSwapouts", 200)
    return [
        {"id": "cpu", "label": "CPU", "value": f(h.get("cpuPct"), "%"), "pct": h.get("cpuPct") or 0,
         "sub": f"load {f(h['load1'])} of {f(h['maxLoad'])} · {h['cores']} cores",
         "sev": "critical" if load_ratio >= 1 else "warning" if load_ratio >= 0.8 else "ok"},
        {"id": "memory", "label": "Memory", "value": f"{f(h.get('memUsedGiB'))} GiB", "pct": mem_pct,
         "sub": f"of {f(h['memTotalGiB'])} GiB · {f(h.get('memFreePct'), '%')} free · reserve {f(h['reserveGiB'])} GiB",
         "sev": "critical" if mem_pct >= 90 else "warning" if mem_pct >= 80 else "ok"},
        {"id": "swap", "label": "Swap", "value": f"{f(h.get('swapUsedGiB'))} GiB", "pct": swap_pct,
         "sub": f"of {f(h.get('swapTotalGiB'))} GiB · {f(outs)} swap-outs/12 s (max {max_outs})",
         "sev": "critical" if outs is not None and outs >= max_outs else "warning" if outs is not None and outs >= max_outs / 2 else "ok"},
        {"id": "disk", "label": "Disk", "value": f"{f(h['diskFreeGiB'])} GiB free", "pct": disk_pct,
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


def ago(t, now):
    mins = int((now - t).total_seconds() // 60)
    return f"{mins} min ago" if mins < 90 else f"{mins // 60} h {mins % 60} min ago"


def meter(pct, sev):
    pct = max(0.0, min(100.0, float(pct)))
    return f'<div class="meter {sev}" role="meter" aria-valuenow="{pct:.0f}" aria-valuemin="0" aria-valuemax="100"><i style="width:{pct:.1f}%"></i></div>'


def tile(t):
    return (
        f'<div class="tile" id="t-{e(t["id"])}" data-sev="{t["sev"]}"><div class="tl">{e(t["label"])}'
        f'<span class="tst">{status(t["sev"]) if t["sev"] != "ok" else ""}</span></div>'
        f'<div class="tv">{e(t["value"])}</div>{meter(t["pct"], t["sev"])}<div class="ts">{e(t["sub"])}</div></div>'
    )


def link(item):
    return f'<a href="{e(item["href"])}">{e(item["label"])}</a>'


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

    # ---- attention: everything that needs a person, worst first
    attention = []  # (sev, title, detail, href)
    for t in host_tiles(host):
        if t["sev"] != "ok":
            attention.append((t["sev"], f"Host {t['label'].lower()}: {t['value']}", t["sub"], "#host"))
    for cls in classes:
        for h in holders(leases, cls):
            if parse(h["expiresAt"]) < now:
                attention.append(("critical", f"{cls} lease {h['id']} expired", f"{h['holder'][:70]} · expired {ago(parse(h['expiresAt']), now)} · still holds its slot", "#leases"))
    for name, c in coords.items():
        if not coord_live(c):
            hb = f"last heartbeat {ago(parse(c['heartbeat']), now)}" if c.get("heartbeat") else "no heartbeat"
            attention.append(("critical", f"Coordinator {name} is stale", f"{hb} · its members get no directions", f"#coord-{name}"))
    for who, src in sources.items():
        for d in src.get("decisions", []):
            href = d.get("href") or session_of(who, d.get("task", "")) or "#decisions"
            attention.append(("serious", f"Decision for you{' · ' + d['task'] if d.get('task') else ''}", f"{d.get('text', '')} ({who})", href))
    for coord, mlist in members.items():
        for m in mlist:
            if m.get("status") in ("done", "paused"):
                continue
            last = m.get("updatedAt") or m.get("joinedAt") or m.get("enrolledAt")
            if not last:
                continue
            age = now - parse(last)
            if m.get("status") == "pending" and age > dt.timedelta(minutes=30):
                attention.append(("warning", f"{m['name']} never joined", f"enrolled {ago(parse(last), now)} by {m.get('parent', coord)} · {m.get('task', '')[:60]}", f"#coord-{coord}"))
            elif m.get("status") != "pending" and age > dt.timedelta(minutes=30):
                attention.append(("warning", f"{m['name']} is silent", f"no update {ago(parse(last), now)} · {m.get('task', '')[:60]} ({coord})", session_of(coord, m["name"]) or f"#coord-{coord}"))
    decided = {d.get("task") for src in sources.values() for d in src.get("decisions", []) if d.get("task")}
    for who, src in sources.items():
        for t in src.get("tasks", []):
            if t.get("kind") == "warn" and t.get("id") not in decided:
                attention.append(("warning", f"{t.get('id')} · {t.get('phase', '')}", t.get("latest", ""), t.get("session") or f"#coord-{who}"))
    attention.sort(key=lambda a: SEV_ORDER[a[0]])

    if attention:
        worst = attention[0][0]
        counts = {s: sum(1 for a in attention if a[0] == s) for s in ("critical", "serious", "warning")}
        summary = "".join(f'<span class="cnt">{status(s)}{n}</span>' for s, n in counts.items() if n)
        def att(item):
            sev, title, detail, href = item
            return (f'<li class="att {sev}"><a href="{e(href)}" title="{e(detail)}">{status(sev)}<span class="att-t">{e(title)}</span>'
                    f'<span class="att-d">{e(detail)}</span></a></li>')
        first, rest = attention[:6], attention[6:]
        more = (f'<details class="more"><summary>Show {len(rest)} more</summary><ul class="att-list">{"".join(att(a) for a in rest)}</ul></details>'
                if rest else "")
        hero = (
            f'<section class="hero {worst}" aria-label="Needs attention"><div class="hero-n">{len(attention)}</div>'
            f'<div class="hero-l"><div class="hero-h">need attention</div><div class="hero-s">{summary}</div></div>'
            f'<ul class="att-list">{"".join(att(a) for a in first)}</ul>{more}</section>'
        )
    else:
        hero = (
            f'<section class="hero ok" aria-label="Needs attention"><div class="hero-n">0</div>'
            f'<div class="hero-l"><div class="hero-h">{status("ok")} All clear</div>'
            f'<div class="hero-s">No decisions, expired leases, stale coordinators or silent members.</div></div></section>'
        )

    # ---- host tiles
    host_html = "".join(tile(t) for t in host_tiles(host))

    # ---- lease tiles
    leases_on = roster.get("leases") == "on" or any(holders(leases, c) or queue.get(c) for c in classes)
    lease_tiles = ""
    if leases_on:
        for cls in classes:
            cur = holders(leases, cls)
            cap = capacity.get(cls)
            ready = [q for q in queue.get(cls, []) if not q.get("hold")]
            expired = any(parse(h["expiresAt"]) < now for h in cur)
            sev = "critical" if expired else "warning" if (cap is not None and len(cur) >= max(1, cap) and ready) else "ok"
            pct = 100 * len(cur) / max(1, cap) if cap is not None else (100 if cur else 0)
            sub = f"{len(ready)} queued"
            if ready:
                sub += f" · next {ready[0]['holder'][:26]} {eta_text(cls, ready[0]['id'])}"
            left = settle_left(cls)
            if left > 0:
                sub = f"settling {int(left)} s · " + sub
            holder = f"{cur[0]['holder'][:34]} · {eta_text(cls, cur[0]['id'])}" if cur else "free"
            lease_tiles += (
                f'<a class="tile" href="#leases" data-sev="{sev}"><div class="tl">{e(cls)}'
                f'<span class="tst">{status(sev) if sev != "ok" else ""}</span></div>'
                f'<div class="tv">{len(cur)} / {cap if cap is not None else "∞"}</div>{meter(pct, sev)}'
                f'<div class="ts">{e(holder)}</div><div class="ts">{e(sub)}</div></a>'
            )

    # ---- work board: every coordinator's tasks in one list, grouped by work state
    def task_row(t, coord):
        links = [link(l) for l in t.get("links", [])]
        when = task_eta(t.get("id", "")) or t.get("eta", "")
        name_html = (f'<a class="stretch" href="{e(t["session"])}" title="Open session">{e(t.get("name", ""))}</a>'
                     if t.get("session") else e(t.get("name", "")))
        tool = coords.get(coord, {}).get("tool", "")
        return (
            f'<li class="task k-{e(t.get("kind", "work"))}{" click" if t.get("session") else ""}"><div class="task-h"><span class="tid">{e(t.get("id", ""))}</span>'
            f'<span class="tname">{name_html}</span><span class="tag" title="coordinator">{e(coord)}{" · " + e(tool) if tool and tool != coord else ""}</span>'
            f'<span class="badge k-{e(t.get("kind", "work"))}">{e(t.get("phase", ""))}</span></div>'
            + (f'<div class="tlatest">{e(t.get("latest", ""))}</div>' if t.get("latest") else "")
            + (f'<div class="tmeta">{" · ".join(links)}{" · " if links and when else ""}{e(when)}</div>' if links or when else "")
            + "</li>"
        )

    groups = [("warn", "Blocked or waiting"), ("work", "In progress"), ("ok", "On track"), ("done", "Done")]
    all_tasks = [(t, coord) for coord, src in sources.items() for t in src.get("tasks", [])]
    board = ""
    for kind, label in groups:
        rows = [task_row(t, c) for t, c in all_tasks if (t.get("kind") or "work") == kind]
        if not rows:
            continue
        inner = f'<ul class="tasks">{"".join(rows)}</ul>'
        if kind == "done":
            board += f'<details class="group"><summary><span class="gh">{label}</span> <span class="muted">{len(rows)}</span></summary>{inner}</details>'
        else:
            board += f'<section class="group"><div class="gh">{label} <span class="muted">{len(rows)}</span></div>{inner}</section>'

    strip = ""
    for name in sorted(set(coords) | set(sources)):
        c, src = coords.get(name, {}), sources.get(name, {})
        live = coord_live(c)
        mlist = members.get(name, [])
        pending = sum(1 for m in mlist if m.get("status") == "pending")
        href = (src.get("coordinator") or {}).get("href", "")
        top = [link(l) for l in src.get("links", [])]
        strip += (
            f'<div class="coord{" click" if href else ""}" id="coord-{e(name)}"><div class="coord-h">'
            + (f'<a class="stretch" href="{e(href)}" title="Open coordinator session">{e(name)}</a>' if href else e(name))
            + f' <span class="chip {"live" if live else "stale"}">{"live" if live else "stale"}</span></div>'
            f'<div class="muted small">{e(c.get("tool", ""))} · {e(c.get("focus", ""))}</div>'
            f'<div class="small">{len(mlist) - pending} members{f" · {pending} pending" if pending else ""} · updated {e(src.get("updated", "?"))}</div>'
            + (f'<div class="lk">{"".join(top)}</div>' if top else "")
            + "</div>"
        )
    notes = [(name, n) for name, src in sources.items() for n in src.get("notes", [])]
    notes_html = (
        f'<article class="card"><details class="notes-box"><summary><span class="gh">Notes</span> <span class="muted">{len(notes)}</span></summary>'
        f'<ul class="notes">{"".join(f"<li><span class=tag>{e(n)}</span> {e(x)}</li>" for n, x in notes)}</ul></details></article>'
        if notes else ""
    )

    # ---- queues and ledger (side column)
    queue_html = ""
    if leases_on:
        for cls in classes:
            items = "".join(
                f"<li><span class='badge k-work'>held</span> <b>{e(h['holder'][:48])}</b>"
                f"<div class='muted'>{e(h['id'])} · {e(h['coordinator'])} · {h['gib']:g} GiB · {e(eta_text(cls, h['id']))}</div>"
                + (f"<div class='code'>{e(h['commands'])}</div>" if h.get("commands") else "") + "</li>"
                for h in holders(leases, cls)
            ) + "".join(
                f"<li><span class='badge {'k-done' if q.get('hold') else 'k-ok'}'>{'hold' if q.get('hold') else i + 1}</span> {e(q['holder'][:48])}"
                f"<div class='muted'>{e(q['id'])} · {e(q['coordinator'])} · ~{est_minutes(cls, q):g} min · {e(eta_text(cls, q['id']))}</div></li>"
                for i, q in enumerate(queue.get(cls, []))
            )
            cap = capacity.get(cls)
            queue_html += (
                f"<h4>{e(cls)} <span class='muted'>{e(registry[cls].get('description', ''))}</span></h4>"
                f"<div class='muted small'>capacity {cap if cap is not None else '∞'} · peak ~{(budget.get('peakGiB') or {}).get(cls, '?')} GiB</div>"
                f"<ol class='q'>{items or '<li class=muted>Empty</li>'}</ol>"
            )
        queue_html = (
            f'<article class="card" id="leases"><header class="card-h"><div><h3>Lease queues</h3>'
            f'<div class="muted">strict FIFO across coordinators · {budget.get("freeGiB", "?")} of {budget.get("limitGiB", "?")} GiB free</div></div></header>{queue_html}</article>'
        )
    ledger = []
    try:
        for line in reversed(open(os.path.join(DIR, "ledger.jsonl")).read().splitlines()[-20:]):
            try:
                ledger.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    ledger_html = "".join(
        f"<li><div class='lh'><time>{e(x.get('at', '')[11:16])}Z</time><b>{e(x.get('by', ''))}</b></div><div>{e(x.get('text', ''))}</div></li>" for x in ledger
    ) or "<li class='muted'>Empty</li>"
    side = queue_html + notes_html + f'<article class="card"><header class="card-h"><div><h3>Ledger</h3><div class="muted">newest first</div></div></header><ul class="ledger">{ledger_html}</ul></article>'

    body = (
        hero
        + f'<section class="row" id="host"><h2>Machine{" and leases" if leases_on else ""} <span class="muted" id="sampled">host {e((host or {}).get("at", "…"))}</span></h2>'
        + f'<div class="tiles">{host_html}{lease_tiles}</div></section>'
        + f'<div class="cols"><section class="col-main"><h2>Coordinators</h2><div class="coords">{strip or "<p class=muted>No coordinators yet.</p>"}</div>'
        + f'<h2>Work</h2>{board or "<p class=muted>No tasks reported yet.</p>"}</section>'
        + f'<aside class="col-side">{side}</aside></div>'
    )
    icons = json.dumps({sev: status(sev) for sev in ("critical", "serious", "warning")})
    return PAGE.replace("{{UPDATED}}", time.strftime("%H:%M:%S")).replace("{{ICONS}}", icons).replace("{{BODY}}", body)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Master of puppets</title>
<style>
:root{color-scheme:light dark;
--bg:#f4f5f7;--surface:#ffffff;--surface2:#f8f9fa;--bd:#e3e5e8;--ink:#1d1f23;--ink2:#4b5058;--mut:#6b7079;
--accent:#3a6fd8;--accent-track:#dde6f7;--link:#2f5fc4;
--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;
--good-bg:#e8f6e8;--warning-bg:#fff4dc;--serious-bg:#fdece5;--critical-bg:#fbe6e6;
--warning-track:#fdeac0;--serious-track:#f9d8ca;--critical-track:#f4d2d2;
--shadow:0 1px 2px rgba(16,24,40,.06),0 1px 3px rgba(16,24,40,.08)}
@media (prefers-color-scheme:dark){:root{
--bg:#121314;--surface:#1a1a19;--surface2:#202122;--bd:#2c2d2f;--ink:#eceef1;--ink2:#b9bdc4;--mut:#8d929a;
--accent:#6b9cf0;--accent-track:#22324f;--link:#8fb4f5;
--good-bg:#12301a;--warning-bg:#3a2e10;--serious-bg:#3b2318;--critical-bg:#3d1b1b;
--warning-track:#4a3a12;--serious-track:#4a2c1f;--critical-track:#4d2323;--shadow:none}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,system-ui,sans-serif}
a{color:var(--link);text-decoration:none} a:hover{text-decoration:underline}
.top{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:12px;padding:12px 24px;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--bd)}
.top h1{font-size:16px;font-weight:600;margin:0;letter-spacing:-.01em}
.live{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--ink2)}
.live::before{content:"";width:8px;height:8px;border-radius:50%;background:var(--good);box-shadow:0 0 0 3px var(--good-bg)}
body[data-stale] .live::before{background:var(--critical);box-shadow:0 0 0 3px var(--critical-bg)}
body[data-stale] .live span::after{content:" · server unreachable, showing the last state"}
.top .muted{margin-left:auto}
main{max-width:1440px;margin:0 auto;padding:20px 24px 48px}
h2{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;color:var(--ink2);margin:24px 0 10px;display:flex;gap:10px;align-items:baseline}
h2 .muted{text-transform:none;letter-spacing:0;font-weight:400}
h3{font-size:15px;font-weight:600;margin:0;display:flex;align-items:center;gap:8px}
h4{font-size:13px;font-weight:600;margin:14px 0 2px}
.muted{color:var(--mut);font-weight:400} .small{font-size:12px}
.st{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:600;white-space:nowrap}
.st svg{width:16px;height:16px;flex:none} .st{vertical-align:-3px}
.hero-s{display:flex;gap:14px} .cnt{display:inline-flex;align-items:center;gap:5px;font-weight:600;color:var(--ink)} .st svg .g{fill:#fff}
.st.critical svg{fill:var(--critical)} .st.serious svg{fill:var(--serious)} .st.warning svg{fill:var(--warning)} .st.ok svg{fill:var(--good)}
.st.warning svg .g{fill:#1d1f23}
.hero{display:grid;grid-template-columns:auto 1fr;gap:4px 20px;align-items:center;background:var(--surface);border:1px solid var(--bd);border-left:6px solid var(--good);border-radius:14px;padding:18px 22px;box-shadow:var(--shadow)}
.hero.critical{border-left-color:var(--critical)} .hero.serious{border-left-color:var(--serious)} .hero.warning{border-left-color:var(--warning)}
.hero-n{font-size:52px;font-weight:600;line-height:1;letter-spacing:-.02em}
.hero-h{font-size:18px;font-weight:600;display:flex;gap:8px;align-items:center} .hero-s{color:var(--ink2)}
.att-list{grid-column:1/-1;list-style:none;margin:14px 0 0;padding:0;display:grid;gap:6px}
.att a{display:grid;grid-template-columns:18px minmax(180px,auto) 1fr;gap:12px;align-items:baseline;padding:9px 12px;border-radius:10px;color:inherit;text-decoration:none}
.att.critical a{background:var(--critical-bg)} .att.serious a{background:var(--serious-bg)} .att.warning a{background:var(--warning-bg)}
.att a:hover{outline:1px solid var(--bd)}
.att-t{font-weight:600} .att-d{color:var(--ink2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.tile{display:block;background:var(--surface);border:1px solid var(--bd);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow);color:inherit;text-decoration:none}
a.tile:hover{border-color:var(--accent)}
.tile[data-sev=critical]{border-color:var(--critical)} .tile[data-sev=warning]{border-color:var(--warning)}
.tl{display:flex;justify-content:space-between;align-items:center;font-size:12px;font-weight:600;color:var(--ink2);text-transform:uppercase;letter-spacing:.04em}
.tv{font-size:24px;font-weight:600;margin:4px 0 8px;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ts{font-size:12px;color:var(--mut);margin-top:6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.meter{height:8px;border-radius:4px;background:var(--accent-track);overflow:hidden}
.meter i{display:block;height:100%;border-radius:4px;background:var(--accent);transition:width .6s ease}
.meter.warning{background:var(--warning-track)} .meter.warning i{background:var(--warning)}
.meter.serious{background:var(--serious-track)} .meter.serious i{background:var(--serious)}
.meter.critical{background:var(--critical-track)} .meter.critical i{background:var(--critical)}
.cols{display:grid;grid-template-columns:minmax(0,1fr) 400px;gap:20px;align-items:start}
@media (max-width:1100px){.cols{grid-template-columns:1fr}}
.col-side{position:sticky;top:64px;display:grid;gap:16px;margin-top:46px;max-height:calc(100vh - 80px);overflow:auto}
.coords{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.coord{position:relative;background:var(--surface);border:1px solid var(--bd);border-radius:12px;padding:12px 14px;box-shadow:var(--shadow)}
.coord.click:hover{border-color:var(--accent)} .coord-h{font-weight:600;font-size:15px;display:flex;gap:8px;align-items:center}
.group{margin-bottom:18px} .gh{font-size:13px;font-weight:600;margin:0 0 8px;color:var(--ink)}
details.group summary{list-style:none;margin-bottom:8px} details.group summary::-webkit-details-marker{display:none}
details.group summary::before{content:"▸ ";color:var(--mut)} details.group[open] summary::before{content:"▾ "}
.tag{font-size:11px;padding:1px 7px;border-radius:6px;background:var(--surface);border:1px solid var(--bd);color:var(--ink2);white-space:nowrap}
@media (max-width:1100px){.col-side{position:static;margin-top:0}}
.card{background:var(--surface);border:1px solid var(--bd);border-radius:14px;padding:16px 18px;box-shadow:var(--shadow);margin-bottom:16px}
.col-side .card{margin-bottom:0}
.card-h{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:10px}
.card-n{text-align:right;font-size:13px;white-space:nowrap}
.chip{font-size:11px;font-weight:600;padding:1px 8px;border-radius:999px}
.chip.live{background:var(--good-bg);color:var(--good)} .chip.stale{background:var(--critical-bg);color:var(--critical)}
.lk{font-size:12px;margin:6px 0 0;display:flex;flex-wrap:wrap;gap:4px 12px}
.tasks{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.task{position:relative;border:1px solid var(--bd);border-radius:10px;padding:10px 12px;background:var(--surface2)}
.task.click,.card-h.click{cursor:pointer}
.task.click:hover{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.card-h{position:relative} .card-h.click:hover h3 a{text-decoration:underline}
a.stretch{color:inherit;text-decoration:none} a.stretch::after{content:"";position:absolute;inset:0;border-radius:inherit}
.tmeta a,.lk a{position:relative;z-index:1}
.task.k-warn{border-left:4px solid var(--warning)}
.task.k-done{opacity:.6}
.task-h{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.tid{font-weight:700;font-size:13px;min-width:28px} .tname{font-weight:600;flex:1 1 220px}
.tlatest{color:var(--ink2);font-size:13px;margin-top:4px} .tmeta{font-size:12px;color:var(--mut);margin-top:4px}
.badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;white-space:nowrap;background:var(--accent-track);color:var(--accent)}
.badge.k-ok{background:var(--good-bg);color:var(--good)} .badge.k-warn{background:var(--warning-track);color:#7a5200}
.badge.k-done{background:var(--surface2);color:var(--mut);border:1px solid var(--bd)}
@media (prefers-color-scheme:dark){.badge.k-warn{color:var(--warning)}}
ol.q,ul.ledger,ul.notes{margin:6px 0 0;padding:0;list-style:none;display:grid;gap:8px}
ol.q li{font-size:13px} .code{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--surface2);border:1px solid var(--bd);border-radius:6px;padding:4px 6px;margin-top:4px;overflow-x:auto;white-space:pre-wrap}
ul.ledger{max-height:560px;overflow:auto}
ul.ledger li{font-size:13px;padding-bottom:8px;border-bottom:1px solid var(--bd)} ul.ledger li:last-child{border-bottom:none}
ul.ledger .lh{display:flex;gap:8px;font-size:12px} ul.ledger time{color:var(--mut);font-variant-numeric:tabular-nums} ul.ledger b{font-weight:600}
details.more{grid-column:1/-1;margin-top:6px} details summary{cursor:pointer;font-size:13px;color:var(--link);font-weight:600}
details.more .att-list{margin-top:6px}
details.notes-box{margin-top:10px} details.notes-box .notes{margin-top:8px}
ul.notes li{font-size:13px;color:var(--ink2);padding-left:12px;border-left:3px solid var(--bd)}
</style>
<script>
window.__icons = {{ICONS}};
(() => {
  const paint = (h) => {
    if (!h || !h.tiles) return;
    for (const t of h.tiles) {
      const el = document.getElementById("t-" + t.id);
      if (!el) continue;
      el.dataset.sev = t.sev;
      el.querySelector(".tv").textContent = t.value;
      el.querySelector(".ts").textContent = t.sub;
      const m = el.querySelector(".meter");
      m.className = "meter " + t.sev;
      m.setAttribute("aria-valuenow", Math.round(t.pct));
      m.querySelector("i").style.width = Math.max(0, Math.min(100, t.pct)) + "%";
      el.querySelector(".tst").innerHTML = t.sev === "ok" ? "" : (window.__icons[t.sev] || "");
    }
    const at = document.getElementById("sampled");
    if (at) at.textContent = "host " + h.at;
  };
  if (!window.EventSource || location.protocol === "file:") return;
  const es = new EventSource("/events");
  es.addEventListener("host", (ev) => { window.__host = JSON.parse(ev.data); paint(window.__host); });
  es.addEventListener("update", async () => {
    const r = await fetch("/", {cache: "no-store"});
    if (!r.ok) return;
    const doc = new DOMParser().parseFromString(await r.text(), "text/html");
    const y = window.scrollY;
    document.body.innerHTML = doc.body.innerHTML;
    paint(window.__host);
    window.scrollTo(0, y);
  });
  es.onerror = () => document.body.dataset.stale = "1";
  es.onopen = () => delete document.body.dataset.stale;
})();
</script></head><body>
<header class="top"><h1>Master of puppets</h1><span class="live"><span>live</span></span><span class="muted small">rendered {{UPDATED}}</span></header>
<main>{{BODY}}</main>
</body></html>
"""


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
    digest = hashlib.sha256(re.sub(rb"rendered [0-9:]+", b"", body)).hexdigest()
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


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype):
        self.send_response(200)
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
