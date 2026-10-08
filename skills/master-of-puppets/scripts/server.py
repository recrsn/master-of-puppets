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
  /            the page: an at-a-glance strip of cards, then the details
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


def host_cards(h):
    """(id, label, value, sub, hot) for the four host cards; the page JS mirrors this."""
    if not h:
        return [(k, k.title(), "…", "waiting for the first sample", False) for k in ("cpu", "memory", "swap", "disk")]
    if h.get("error"):
        return [("cpu", "Host", "?", h["error"], True)]
    def f(v, unit=""):
        return "?" if v is None else f"{v}{unit}"
    return [
        ("cpu", "CPU", f(h["cpuPct"], "%"), f"load {f(h['load1'])} / {f(h['maxLoad'])} · {h['cores']} cores", h["load1"] >= h["maxLoad"]),
        ("memory", "Memory", f"{f(h['memUsedGiB'])} / {f(h['memTotalGiB'])} GiB", f"{f(h['memFreePct'], '%')} free · reserve {h['reserveGiB']} GiB",
         h["memFreePct"] is not None and h["memFreePct"] < 15),
        ("swap", "Swap", f"{f(h['swapUsedGiB'])} / {f(h['swapTotalGiB'])} GiB", f"{f(h['swapoutsPer12s'])} outs/12 s · max {h['maxSwapouts']}",
         h["swapoutsPer12s"] is not None and h["swapoutsPer12s"] >= h["maxSwapouts"]),
        ("disk", "Disk", f"{f(h['diskFreeGiB'])} GiB free", f"of {f(h['diskTotalGiB'])} GiB · floor {h['diskFloorGiB']} GiB", h["diskFreeGiB"] < h["diskFloorGiB"]),
    ]


# ---------------------------------------------------------------- rendering

def local(t):
    return t.astimezone().strftime("%H:%M")


def parse(iso):
    return dt.datetime.fromisoformat(iso)


def holders(leases, cls):
    return leases.get(cls) or []


def card(label, value, sub="", kind="", ident="", href=""):
    attrs = f' id="c-{ident}"' if ident else ""
    inner = f'<div class="cl">{e(label)}</div><div class="cv">{e(value)}</div><div class="cs">{e(sub)}</div>'
    if href:
        return f'<a class="card {kind}"{attrs} href="{e(href)}">{inner}</a>'
    return f'<div class="card {kind}"{attrs}>{inner}</div>'


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
    capacity = (budget.get("capacity") or {})  # None for a class = unbounded
    queue = leases.get("queue", {})
    projects = {os.path.basename(p)[:-5]: load(p, {}) for p in glob.glob(os.path.join(DIR, "projects", "*.json"))}

    def est_minutes(cls, q):
        """Entry estimate, else the project's median recorded run (3+ runs), else the default."""
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
            return f"running, ends by {local(end)}"
        if kind == "hold":
            return "on hold (keeps place)"
        if kind == "queued":
            return f"starts ~{local(start)}, done ~{local(end)}"
        return ""

    def task_eta(task_id):
        parts = []
        for cls in classes:
            for h in holders(leases, cls) + queue.get(cls, []):
                name = h.get("holder", "")
                if task_id and (name == task_id or name.startswith(task_id + " ")):
                    parts.append(f"{cls} {eta_text(cls, h['id'])}")
        return "; ".join(parts)

    def find_task(task_id):
        return next((t for src in sources.values() for t in src.get("tasks", []) if t.get("id") == task_id), None)

    # decisions
    decisions = [(name, d) for name, src in sources.items() for d in src.get("decisions", [])]

    # ---- at-a-glance strip
    leases_on = roster.get("leases") == "on" or any(holders(leases, c) or queue.get(c) for c in classes)
    glance = card("Needs you", str(len(decisions)), "decisions waiting" if decisions else "nothing waiting",
                  "hot" if decisions else "ok", href="#decisions" if decisions else "")
    for ident, label, value, sub, hot in host_cards(host):
        glance += card(label, value, sub, "hot" if hot else "", ident)
    def settle_left(cls):
        """Seconds until no other class's grant settles cls."""
        return max([0] + [
            secs - (now - parse(h["grantedAt"])).total_seconds()
            for other, spec in registry.items()
            for secs in [(spec.get("settle") or {}).get(cls, 0)] if secs
            for h in holders(leases, other)
        ])

    if leases_on:
        for cls in classes:
            cur = holders(leases, cls)
            ready = [q for q in queue.get(cls, []) if not q.get("hold")]
            sub = f"{len(ready)} queued"
            if settle_left(cls) > 0:
                sub = f"settling {int(settle_left(cls))} s · " + sub
            if cur:
                sub += f" · {cur[0]['holder'][:28]} until {local(parse(cur[0]['expiresAt']))}"
            expired = any(parse(h["expiresAt"]) < now for h in cur)
            kind = "hot" if expired else ("work" if cur else "ok")
            glance += card(f"{cls} lease", f"{len(cur)} / {capacity.get(cls) if capacity.get(cls) is not None else '∞'}", ("EXPIRED · " if expired else "") + sub, kind, href="#leases")
    else:
        glance += card("Leases", "Off", "no queues", "")
    for name, c in roster.get("coordinators", {}).items():
        hb = parse(c["heartbeat"]) if c.get("heartbeat") else None
        is_live = bool(hb and now - hb < dt.timedelta(minutes=LIVE_MINUTES))
        members = roster.get("members", {}).get(name, [])
        pending = sum(1 for m in members if m.get("status") == "pending")
        sub = f"{len(members) - pending} members" + (f" (+{pending} pending)" if pending else "") + f" · {c.get('focus', '')}"
        glance += card(f"{c.get('tool', '')} coordinator · {'live' if is_live else 'stale'}", name, sub,
                       "ok" if is_live else "hot", href=f"#coord-{name}")

    # ---- details
    decisions_html = "".join(
        f'<li><span class="tag">{e(who)}</span> '
        + (f'<a href="{e(d.get("href") or (find_task(d.get("task", "")) or {}).get("session", ""))}">{e(d.get("task", ""))}</a> '
           if d.get("task") or d.get("href") else "")
        + f"{e(d.get('text', ''))}</li>"
        for who, d in decisions
    ) or "<li class='muted'>None</li>"

    def task_rows(tasks):
        rows = ""
        for t in tasks:
            links = []
            if t.get("session"):
                links.append(f'<a href="{e(t["session"])}">session</a>')
            if t.get("worktree"):
                links.append(f'<a href="file://{e(t["worktree"])}">worktree</a>')
            links += [link(l) for l in t.get("links", [])]
            rows += (
                f'<tr><td class="id">{e(t.get("id", ""))}</td>'
                f'<td>{e(t.get("name", ""))}<div class="lk">{" · ".join(links)}</div></td>'
                f'<td><span class="badge {e(t.get("kind", "work"))}">{e(t.get("phase", ""))}</span></td>'
                f'<td class="muted">{e(t.get("latest", ""))}</td>'
                f'<td class="muted">{e(task_eta(t.get("id", "")) or t.get("eta", ""))}</td></tr>'
            )
        return rows

    coord_sections = ""
    for name, src in sources.items():
        c = roster.get("coordinators", {}).get(name, {})
        top = [link(l) for l in ([src["coordinator"]] if src.get("coordinator") else []) + src.get("links", [])]
        notes = "".join(f"<li>{e(n)}</li>" for n in src.get("notes", []))
        coord_sections += (
            f'<section id="coord-{e(name)}"><h2>{e(name)} <span class="muted">· {e(c.get("focus", ""))} · updated {e(src.get("updated", "?"))}</span></h2>'
            + (f'<div class="lk">{" · ".join(top)}</div>' if top else "")
            + (f'<table><tr><th>Id</th><th>Task</th><th>Phase</th><th>Latest</th><th>Lease ETA</th></tr>{task_rows(src.get("tasks", []))}</table>'
               if src.get("tasks") else "<p class='muted'>No tasks reported yet.</p>")
            + (f"<ul class='notes'>{notes}</ul>" if notes else "")
            + "</section>"
        )

    lease_html = ""
    if leases_on:
        for cls in classes:
            items = "".join(
                f"<li><b>{e(h['id'])}</b> {e(h['holder'])} <span class='muted'>({e(h['coordinator'])}, {h['gib']} GiB)</span> — {e(eta_text(cls, h['id']))}"
                + (f"<div class='lk'>covers: <code>{e(h['commands'])}</code></div>" if h.get("commands") else "") + "</li>"
                for h in holders(leases, cls)
            ) + "".join(
                f"<li class='q'>{e(q['holder'])} <span class='muted'>({e(q['coordinator'])}, {e(q['id'])}, ~{est_minutes(cls, q):g} min)</span> — {e(eta_text(cls, q['id']))}</li>"
                for q in queue.get(cls, [])
            )
            cap = capacity.get(cls) if capacity.get(cls) is not None else "∞"
            lease_html += f"<h3>{cls} <span class='muted'>{e(registry[cls].get('description', ''))} · capacity {cap} · {budget.get('freeGiB', '?')} of {budget.get('limitGiB', '?')} GiB free · peak ~{(budget.get('peakGiB') or {}).get(cls, '?')} GiB</span></h3><ol>{items or '<li class=muted>Empty</li>'}</ol>"
        lease_html = f'<section id="leases"><h2>Leases and queues <span class="muted">strict FIFO across coordinators</span></h2>{lease_html}</section>'

    ledger = []
    try:
        for line in reversed(open(os.path.join(DIR, "ledger.jsonl")).read().splitlines()[-15:]):
            try:
                ledger.append(json.loads(line))
            except ValueError:
                pass
    except OSError:
        pass
    ledger_html = "".join(
        f"<li><span class='muted'>{e(x.get('at', '')[11:16])}Z {e(x.get('by', ''))}</span> {e(x.get('text', ''))}</li>" for x in ledger
    ) or "<li class='muted'>Empty</li>"

    return PAGE.replace("{{GLANCE}}", glance).replace("{{UPDATED}}", time.strftime("%H:%M:%S")).replace(
        "{{BODY}}",
        f'<section id="decisions"><h2>Needs your decision</h2><ul class="dec">{decisions_html}</ul></section>'
        + coord_sections + lease_html
        + f'<section><h2>Shared ledger <span class="muted">newest first</span></h2><ul class="ledger">{ledger_html}</ul></section>',
    )


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Master of puppets</title>
<style>
:root{--bg:#fafaf8;--card:#f1efe8;--fg:#1f1f1d;--mut:#6b6a65;--bd:#dcdad2;
--ok-bg:#eaf3de;--ok:#27500a;--wk-bg:#e6f1fb;--wk:#0c447c;--hot-bg:#faeeda;--hot:#7a3d00}
@media (prefers-color-scheme:dark){:root{--bg:#1c1c1a;--card:#2a2a28;--fg:#f1efe8;--mut:#a9a79e;--bd:#3d3d3a;
--ok-bg:#20380b;--ok:#c0dd97;--wk-bg:#0e3256;--wk:#b5d4f4;--hot-bg:#55300a;--hot:#fac775}}
*{box-sizing:border-box} body{font:14px/1.45 -apple-system,system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--bd);padding:12px 20px 14px}
h1{font-size:17px;font-weight:600;margin:0 0 10px;display:flex;gap:10px;align-items:baseline}
h1 .muted{font-size:12px;font-weight:400}
.glance{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:8px}
.card{display:block;background:var(--card);border-radius:8px;padding:8px 10px;color:inherit;text-decoration:none;min-height:66px}
a.card:hover{outline:1px solid var(--bd)}
.card.ok{background:var(--ok-bg)} .card.ok .cv{color:var(--ok)}
.card.work{background:var(--wk-bg)} .card.work .cv{color:var(--wk)}
.card.hot{background:var(--hot-bg)} .card.hot .cv,.card.hot .cs{color:var(--hot)}
.cl{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.03em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cv{font-size:17px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cs{font-size:12px;color:var(--mut);overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
main{padding:4px 20px 40px;max-width:1400px}
section{margin-top:18px} h2{font-size:15px;font-weight:600;margin:0 0 6px} h3{font-size:13px;font-weight:600;margin:10px 0 2px}
.muted{color:var(--mut);font-weight:400}
table{width:100%;border-collapse:collapse} td,th{text-align:left;padding:6px;border-top:1px solid var(--bd);vertical-align:top}
th{color:var(--mut);font-weight:400;font-size:12px;border-top:none} td.id{white-space:nowrap;font-weight:600}
.badge{font-size:12px;padding:2px 8px;border-radius:8px;white-space:nowrap;background:var(--wk-bg);color:var(--wk)}
.badge.ok{background:var(--ok-bg);color:var(--ok)} .badge.warn{background:var(--hot-bg);color:var(--hot)}
.badge.done{background:var(--card);color:var(--mut)}
.tag{font-size:11px;padding:1px 6px;border-radius:6px;background:var(--card);color:var(--mut)}
ul,ol{margin:4px 0;padding-left:20px} li{margin:3px 0} .dec li{margin:6px 0}
a{color:var(--wk);text-decoration:none} a:hover{text-decoration:underline} .lk{font-size:12px;margin:2px 0}
body[data-stale] header::after{content:"Dashboard server unreachable; showing the last state.";display:block;color:var(--hot);margin-top:8px}
</style>
<script>
(() => {
  const f = (v, u = "") => (v === null || v === undefined) ? "?" : v + u;
  const paint = (h) => {
    if (!h || h.error) return;
    const set = (id, value, sub, hot) => {
      const el = document.getElementById("c-" + id);
      if (!el) return;
      el.querySelector(".cv").textContent = value;
      el.querySelector(".cs").textContent = sub;
      el.classList.toggle("hot", !!hot);
    };
    set("cpu", f(h.cpuPct, "%"), `load ${f(h.load1)} / ${f(h.maxLoad)} · ${h.cores} cores`, h.load1 >= h.maxLoad);
    set("memory", `${f(h.memUsedGiB)} / ${f(h.memTotalGiB)} GiB`, `${f(h.memFreePct, "%")} free · reserve ${h.reserveGiB} GiB`, h.memFreePct !== null && h.memFreePct < 15);
    set("swap", `${f(h.swapUsedGiB)} / ${f(h.swapTotalGiB)} GiB`, `${f(h.swapoutsPer12s)} outs/12 s · max ${h.maxSwapouts}`, h.swapoutsPer12s !== null && h.swapoutsPer12s >= h.maxSwapouts);
    set("disk", `${f(h.diskFreeGiB)} GiB free`, `of ${f(h.diskTotalGiB)} GiB · floor ${h.diskFloorGiB} GiB`, h.diskFreeGiB < h.diskFloorGiB);
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
<header><h1>Master of puppets <span class="muted">rendered {{UPDATED}} · <span id="sampled">live</span></span></h1>
<div class="glance">{{GLANCE}}</div></header>
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
