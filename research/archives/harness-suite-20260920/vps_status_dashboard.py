#!/usr/bin/env python3
"""Small read-only status page for evaluation runs.

The service intentionally binds to loopback by default.  A local relay copies
sanitised status snapshots to ``/srv/hse-status``; this process never receives
model prompts, source trees, or credentials.
"""

from __future__ import annotations

import gzip
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(os.environ.get("HSE_STATUS_ROOT", "/srv/hse-status"))
HOST = os.environ.get("HSE_STATUS_HOST", "127.0.0.1")
PORT = int(os.environ.get("HSE_STATUS_PORT", "18080"))
PUBLIC = os.environ.get("HSE_STATUS_PUBLIC") == "1"
HIDDEN_RUNS = {
    item.strip()
    for item in os.environ.get(
        "HSE_STATUS_HIDDEN_RUNS",
        "probe-20260922,20260921T220110Z-33a8ee",
    ).split(",")
    if item.strip()
}
_CACHE: dict[str, dict] = {}
_CACHE_LOCK = threading.Lock()


def public_status(value: dict) -> dict:
    """Allowlist only progress metadata; never publish raw conversation/log fields."""
    fields = (
        "schema",
        "run_id",
        "experiment_name",
        "state",
        "round",
        "total_rounds",
        "phase",
        "completed",
        "failed",
        "total_units",
        "delivery",
        "components",
        "last_heartbeat",
        "updated_at",
        "exit_code",
        "recovery_revision",
        "stalled_for_seconds",
        "started_at",
    )
    result = {key: value.get(key) for key in fields}
    sources = value.get("api_sources")
    result["api_sources"] = {
        role: sources[role]
        for role in ("harness", "user", "synthesizer", "developer")
        if isinstance(sources, dict) and sources.get(role) in ("Boyue", "WIS", "OpenRouter", "Unknown")
    }
    # Historical snapshots may have labelled a failed process as finished.
    if result.get("exit_code") not in (None, 0, "0"):
        result["state"] = "controller_exited"
    result["agents"] = [
        {key: row.get(key) for key in ("role", "running", "round", "started_at", "updated_at")}
        for row in value.get("agents", [])
        if isinstance(row, dict)
    ]
    proposals = value.get("proposals")
    if isinstance(proposals, dict):
        result["proposals"] = {
            key: proposals.get(key)
            for key in (
                "admitted",
                "completed",
                "processing",
                "ready",
                "awaiting_confirmation",
                "failed",
                "blocked",
                "unknown",
            )
        }
        result["proposals"]["items"] = [
            {
                key: row.get(key)
                for key in (
                    "issue",
                    "pr",
                    "state",
                    "ledger_status",
                    "runtime_status",
                    "observed_phase",
                    "last_action",
                    "last_action_at",
                    "last_observed_at",
                )
            }
            for row in proposals.get("items", [])
            if isinstance(row, dict)
        ]
    return result


def _read_json(path: Path, fallback: object) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return fallback


def _runs() -> list[dict]:
    with _CACHE_LOCK:
        for path in ROOT.glob("*/status.json"):
            value = _read_json(path, {})
            if isinstance(value, dict) and value.get("run_id") == path.parent.name:
                _CACHE[path.parent.name] = value
        rows = [
            public_status(row) if PUBLIC else dict(row)
            for run_id, row in _CACHE.items()
            if run_id not in HIDDEN_RUNS
        ]
    # IDs contain immutable launch timestamps. Never sort by relay freshness.
    return sorted(rows, key=lambda row: str(row.get("run_id") or ""), reverse=True)


def _run_payload(run_id: str) -> dict:
    if not run_id or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in run_id
    ):
        return {}
    safe = Path(run_id).name
    directory = ROOT / safe
    value = _read_json(directory / "status.json", {})
    if safe in HIDDEN_RUNS:
        return {}
    if not isinstance(value, dict) or value.get("run_id") != safe:
        with _CACHE_LOCK:
            value = dict(_CACHE.get(safe, {}))
    if PUBLIC:
        return public_status(value)
    events = (directory / "events.jsonl").read_text(encoding="utf-8", errors="replace")[-12000:]
    log_tail = (directory / "log.tail").read_text(encoding="utf-8", errors="replace")[-12000:]
    value["events"] = events.splitlines()[-120:]
    value["log_tail"] = log_tail.splitlines()[-120:]
    return value


PAGE = """<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Harness Evaluation Status</title>
<style>
body{font:14px system-ui,sans-serif;margin:24px;background:#f6f7f9;color:#20242a}
table{border-collapse:collapse;width:100%;background:white}th,td{padding:9px;border:1px solid #e1e4e8;text-align:left}
.ok{color:#087f5b}.bad{color:#c92a2a}.stale{color:#e67700}.mono{font-family:ui-monospace,monospace;white-space:pre-wrap}
section{background:#fff;padding:16px;margin:14px 0;border:1px solid #e1e4e8;border-radius:8px}
button{padding:5px 10px;cursor:pointer}small{color:#667085}
</style><body><h1>Harness Evaluation Status</h1><small id="updated">loading…</small>
<section><table><thead><tr><th>Experiment</th><th>run</th><th>API Source used</th><th>round</th><th>phase</th><th>OpenAgents Proposal</th><th>components</th><th>Ledger update time</th><th>state</th></tr></thead><tbody id="runs"></tbody></table></section>
<section id="detail"><h2>Select one run</h2></section>
<script>
let selected=null, refreshInFlight=false;
const snapshots=new Map(), rowNodes=new Map();
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function componentSummary(x){return (x.components||[]).map(c=>esc(c.name)+': '+esc(c.state)+(c.total?' · '+esc(c.completed)+'/'+esc(c.total)+' Completed':'')+(c.failed?' · '+esc(c.failed)+' Failed':'')+(c.name==='openagents'?'（Process status，Does not indicate ongoing delivery）':'')).join('<br>')||'—';}
function proposalSummary(x){let p=x.proposals;if(!p)return 'No proposal monitoring data yet';return `Enter ${esc(p.admitted)} Items · Completed ${esc(p.completed)}<br>Processing ${esc(p.processing)} · Ready ${esc(p.ready)} · Pending confirmation ${esc(p.awaiting_confirmation)}<br>Failed ${esc(p.failed)} · Blocked ${esc(p.blocked)} · Unknown ${esc(p.unknown)}`;}
function sourceSummary(x){let s=x.api_sources||{};let names=[...new Set(['harness','user','synthesizer','developer'].map(k=>s[k]).filter(Boolean))];return names.length?names.map(esc).join(' / '):'Not recorded';}
function proposalTable(x){let p=x.proposals;if(!p)return '<p>No proposal monitoring data yet</p>';let labels={completed:'Completed（Ledger confirmation）',processing:'Processing',ready:'Ready for processing',awaiting_confirmation:'Development complete，Pending central controller confirmation',failed:'Failed',blocked:'Blocked',unknown:'Pending verification'};return '<h3>Entered this round OpenAgents Proposals</h3><p>'+proposalSummary(x)+'</p><small>Processing status is based on the latest observation，Does not guarantee continued progress；Heartbeat updates do not indicate completion。An unchanged ledger over time does not necessarily indicate a stall。</small><table><thead><tr><th>Proposal</th><th>PR</th><th>Status</th><th>Development records</th><th>Latest concrete action / Time</th><th>Latest observation</th></tr></thead><tbody>'+p.items.map(r=>`<tr><td>#${esc(r.issue)}</td><td>${r.pr?'#'+esc(r.pr):'—'}</td><td>${esc(labels[r.state]||r.state)}</td><td>${esc(r.runtime_status||'—')} / ${esc(r.observed_phase||'—')}</td><td>${esc(r.last_action||'—')}<br>${esc(r.last_action_at||'—')}</td><td>${esc(r.last_observed_at||'—')}</td></tr>`).join('')+'</tbody></table>';}
function renderRows(rows){
const tbody=document.getElementById('runs');
for(const x of rows){
let tr=rowNodes.get(x.run_id);
if(!tr){tr=document.createElement('tr');for(let i=0;i<9;i++)tr.appendChild(document.createElement('td'));rowNodes.set(x.run_id,tr);}
const bad=x.state==='controller_exited'||(x.exit_code!=null&&x.exit_code!==0);
const age=x.updated_at?Math.max(0,Math.floor((Date.now()-Date.parse(x.updated_at))/1000)):null;
const openagents=(x.components||[]).find(c=>c.name==='openagents');
const final=x.state==='finished'||(x.exit_code!=null&&!openagents?.process_running);
const stale=!final&&(age==null||age>180);
const syncLabel=final?'Final snapshot':stale?'Sync stale':'Synchronization normal';
const cells=[esc(x.experiment_name||'Unlabeled experiment'),`<button onclick="selectRun('${esc(x.run_id)}')">${esc(x.run_id)}</button>`,sourceSummary(x),`${esc(x.round)}/${esc(x.total_rounds)}`,esc(x.phase),proposalSummary(x),componentSummary(x),`${esc(x.last_heartbeat||'—')}<br><small>Synchronize ${esc(x.updated_at||'—')}</small><br><span class="${stale?'stale':'ok'}">${syncLabel} · ${esc(age??'—')}s Before</span>`,`<span class="${bad?'bad':'ok'}">${esc(x.state||'unknown')}</span>`];
cells.forEach((body,i)=>{if(tr.children[i].innerHTML!==body)tr.children[i].innerHTML=body;});
}
rows.forEach((x,i)=>{const tr=rowNodes.get(x.run_id);if(tbody.children[i]!==tr)tbody.insertBefore(tr,tbody.children[i]||null);});
if(!rows.length)tbody.innerHTML='<tr><td colspan="9">No synchronization data available</td></tr>';
}
async function refresh(){
if(refreshInFlight)return;
refreshInFlight=true;
let timeout;
const controller=typeof AbortController==='function'?new AbortController():null;
try{
// Avoid AbortSignal.timeout(): older browsers and embedded webviews do not
// implement it, which previously made every refresh fail before fetch ran.
let fresh=await Promise.race([
 (async()=>{let r=await fetch('/api/runs',{cache:'no-store',...(controller?{signal:controller.signal}:{})});if(!r.ok)throw new Error(r.status);return r.json();})(),
 new Promise((_,reject)=>{timeout=setTimeout(()=>{if(controller)controller.abort();reject(new Error('request timeout'));},20000)})
]);
if(!Array.isArray(fresh))throw new Error('invalid runs payload');
for(const row of fresh){const prev=snapshots.get(row.run_id);if(row.run_id&&(!prev||String(row.updated_at||'')>=String(prev.updated_at||'')))snapshots.set(row.run_id,row);}
let rows=Array.from(snapshots.values()).sort((a,b)=>b.run_id.localeCompare(a.run_id));
document.getElementById('updated').textContent='updated '+new Date().toLocaleString();
renderRows(rows);
if(!selected&&rows.length)selected=rows[0].run_id;
if(selected)selectRun(selected);
}catch(e){document.getElementById('updated').textContent='refresh failed; retaining last snapshot';}
finally{clearTimeout(timeout);refreshInFlight=false;}
}
function selectRun(id){selected=id;let x=snapshots.get(id);if(!x)return;
const detail=document.getElementById('detail');const opened=detail.querySelector('details')?.open;
document.getElementById('detail').innerHTML='<h2>'+esc(x.run_id||id)+'</h2><p>round '+esc(x.round)+'/'+esc(x.total_rounds)+' · phase '+esc(x.phase)+' · Ledger/Character status not updated '+esc(x.stalled_for_seconds??'—')+'s（Not stuck determination）</p>'+proposalTable(x)+'<details><summary>Component and ledger details</summary><div class="mono">'+esc(JSON.stringify({components:x.components,delivery:x.delivery},null,2))+'</div></details>';
if(opened)detail.querySelector('details').open=true;
}
refresh();setInterval(refresh,5000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/runs":
            self._json(_runs())
            return
        if parsed.path.startswith("/api/runs/"):
            self._json(_run_payload(unquote(parsed.path.rsplit("/", 1)[-1])))
            return
        if parsed.path in {"/", "/index.html"}:
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def _json(self, value: object) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        encoding = self.headers.get("Accept-Encoding", "")
        use_gzip = any(
            part.strip().split(";", 1)[0].lower() == "gzip"
            and not any(option.strip().lower() == "q=0" for option in part.split(";")[1:])
            for part in encoding.split(",")
        )
        if use_gzip:
            body = gzip.compress(body, compresslevel=5, mtime=0)
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Vary", "Accept-Encoding")
        if use_gzip:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"hse-status listening on http://{HOST}:{PORT} root={ROOT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
