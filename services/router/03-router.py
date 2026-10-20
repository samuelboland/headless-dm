#!/usr/bin/env python3
"""
03-router.py — Ollama-impersonating LLM router with failover.

Sits on the realm's own host at port 11434 (Ollama's default) so mod-ollama-chat needs no
special endpoint config. Translates Ollama API calls (/api/generate,
/api/chat) into OpenAI /v1/chat/completions against llama-server or
LM Studio backends across the tailnet, with ordered failover per route
(including optional OpenRouter as last resort).

"Model" names sent by clients are ROUTE names (ambient, quality, chronicle,
prose, utility, moment). Unknown names fall back to DEFAULT_ROUTE.

The fleet is read again, without a restart, whenever fleet.toml or site/fleet.override.json (the dashboard's
model panel) changes: see reload_fleet. A bad reload keeps the routes in use.

Stdlib only. Run: python3 03-router.py   (env: OPENROUTER_API_KEY optional)
"""

import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from uuid import uuid4
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------- CONFIG --
# EDIT tailnet IPs to match your machines. Order within a route = failover
# order. "model" is what the backend is told (llama-server ignores it;
# OpenRouter requires a real slug).

# The machines, the routes and the caps all come from site/fleet.toml now (plan 23 W3). They used to be
# written out here AND again in services/lore/fleet.py -- two copies of six addresses, which is the kind
# of duplication that is fine until the day one of them is edited.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
from common import fleet_config as _fleet  # noqa: E402
from accounting.recorder import record_attempt  # noqa: E402

def _signature():
    """What the files look like right now: fleet.toml and the operator's override file, by modified time and
    size. A change to either means the routes may have to be built again."""
    out = []
    for p in (_fleet.path(), _fleet.override_path()):
        try:
            st = os.stat(p)
            out.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((p, None, None))
    return tuple(out)


# Taken BEFORE the fleet is read: a file saved in between then looks changed on the first look, and costs one
# harmless extra reload, instead of looking unchanged and being missed.
_SIG = _signature()
_CFG = _fleet.load()
_ROUTER = _fleet.router(_CFG)
QUEUE_WAIT = int(_ROUTER.get("queue_wait", 20))

# How often the files are looked at, in seconds. A stat of two files, so cheap enough to be short.
RELOAD_EVERY = 3

# Each physical backend is built ONCE per reading of the fleet and the same object is reused in every route it
# appears in, so its semaphore is shared. Building a fresh one per route would give each its own cap, and the
# cap would quietly stop meaning anything -- the machine would take four concurrent requests per route instead
# of four in total.
#
# The semaphores outlive a reload. A request in flight holds the one it took, and a rebuilt route that handed
# the next request a fresh one would let a machine take twice its cap for as long as the old requests ran.
# The backend objects themselves are never edited after they are built -- a reload makes new ones -- so a
# request that started on the old model finishes on it, and the accounting row names the model it really used.
_SEMS = {}

def _semaphore(name, slots):
    held = _SEMS.get(name)
    if held and held[0] == slots:
        return held[1]
    sem = threading.BoundedSemaphore(slots) if slots else None
    _SEMS[name] = (slots, sem)
    return sem

def _backend(name, cfg, built):
    """A fleet.toml backend in the shape this router's request path expects.

    The shapes differ on purpose and have to be translated here: fleet.toml holds a BASE url, because
    the batch side appends its own path, while call_backend passes ours straight to urllib. It also
    names the live-chat cap and timeout router_slots/router_timeout, because the same machine carries
    different numbers for batch work.
    """
    if name in built:
        return built[name]
    b = _fleet.backend(name, cfg)
    url = b["url"].rstrip("/")
    if not url.endswith("/chat/completions"):
        url = url + ("/chat/completions" if url.endswith("/v1") else "/v1/chat/completions")
    slots = int(b["router_slots"] or 0)
    built[name] = {
        "name": name,
        "url": url,
        "model": b["model"],
        "key": b["api_key"],
        "timeout": int(b["router_timeout"]),
        "sem": _semaphore(name, slots),
        "system_suffix": b["system_suffix"],
        "extra_body": b["extra_body"],
    }
    return built[name]

def _build(cfg):
    """(routes, default route) for one reading of the fleet.

    A paid backend with no key configured drops out of every route it is named in, which is what an
    optional fallback has to mean for a realm that never bought one. fleet_config has already filtered it.
    """
    built = {}
    routes = {name: [_backend(b["name"], cfg, built) for b in chain]
              for name, chain in _fleet.routes(cfg).items()}
    routes = {name: chain for name, chain in routes.items() if chain}
    return routes, ("ambient" if "ambient" in routes else next(iter(routes), "ambient"))

# Replaced whole by reload_fleet, never edited: a request takes one reading of ROUTES and works from that.
ROUTES, DEFAULT_ROUTE = _build(_CFG)
BIND = (_ROUTER.get("bind", "0.0.0.0"), int(os.environ.get("ROUTER_PORT", _ROUTER.get("port", 11434))))

# What /health says about the fleet in use, so the dashboard can tell "saved" from "the router has it".
_LOADED = {"digest": _fleet.fingerprint(_CFG), "revision": (_CFG.get("_override") or {}).get("revision", 0),
           "at": int(time.time()), "error": None}
_reload_lock = threading.Lock()

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
# A JSON reply some rented models wrap in a markdown fence anyway; only a lone fence is unwrapped.
FENCE_RE = re.compile(r"\A```(?:json)?\s*\n(.*?)\n?```\Z", re.DOTALL)

# --------------------------------------------------------------- helpers --

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ------------------------------------------------------------------ reload --
# The dashboard's model panel writes site/fleet.override.json (services/common/fleet_admin.py). Every few
# seconds the router looks at that file and fleet.toml and, when either changed, builds the routes again and
# swaps them in. A reload that fails for any reason -- a half-saved fleet.toml, a route left with no usable
# backend -- keeps the routes already in use and says why on /health; the router never stops answering chat
# because someone saved a file.

def _changes(old, new):
    """What differs between two route tables, as short phrases for the log."""
    said = []
    for name in sorted(set(old) | set(new)):
        before = [b["name"] for b in old.get(name, [])]
        after = [b["name"] for b in new.get(name, [])]
        if before != after:
            said.append(f"route {name}: {','.join(before) or '-'} -> {','.join(after) or '-'}")
    was = {b["name"]: b["model"] for chain in old.values() for b in chain}
    now = {b["name"]: b["model"] for chain in new.values() for b in chain}
    for name in sorted(set(was) & set(now)):
        if was[name] != now[name]:
            said.append(f"model of {name}: {was[name]} -> {now[name]}")
    return said

def reload_fleet(force=False):
    """Read the fleet again if its files changed (or `force`), and swap the routes in. True when new routes
    went live. In-flight requests are untouched: each holds the backend objects it started with."""
    global ROUTES, DEFAULT_ROUTE, QUEUE_WAIT, _CFG, _ROUTER, _SIG
    with _reload_lock:
        sig = _signature()
        if sig == _SIG and not force:
            return False
        try:
            cfg = _fleet.load()
            problem = (cfg.get("_override") or {}).get("problem")
            if problem and ROUTES:
                raise RuntimeError(problem)        # a saved-changes file nobody can read: keep what is live
            routes, default = _build(cfg)
            if not routes and ROUTES:
                raise RuntimeError("it would leave no route with a usable backend")
        except (Exception, SystemExit) as e:   # noqa: BLE001 -- load() and backend() stop the process with SystemExit
            why = (str(e) or type(e).__name__)[:200]
            if why != _LOADED["error"]:        # once, not every few seconds until someone fixes the file
                log(f"fleet: not reloaded, keeping the routes in use: {why}")
            _LOADED["error"] = why
            return False
        said = _changes(ROUTES, routes)
        ROUTES, DEFAULT_ROUTE = routes, default
        _CFG, _ROUTER = cfg, _fleet.router(cfg)
        QUEUE_WAIT = int(_ROUTER.get("queue_wait", 20))
        _SIG = sig
        _LOADED.update(digest=_fleet.fingerprint(cfg), revision=(cfg.get("_override") or {}).get("revision", 0),
                       at=int(time.time()), error=None)
        saved = f"saved changes, revision {_LOADED['revision']}" if _LOADED["revision"] else "no saved changes"
        log(f"fleet: reloaded ({saved})" + (": " + "; ".join(said) if said else ", nothing differs"))
        return True

def _watch_fleet(stop=None):
    stop = stop or threading.Event()
    while not stop.wait(RELOAD_EVERY):
        try:
            reload_fleet()
        except Exception as e:   # noqa: BLE001 -- the watcher must outlive anything a reload throws
            log(f"fleet: watcher error: {type(e).__name__}: {e}")

def call_backend(backend, messages, opts, context=None):
    suffix = backend.get("system_suffix")
    if suffix:
        # Copy so the suffix never leaks into the next backend on failover.
        messages = [dict(m) for m in messages]
        sys_msgs = [m for m in messages if m.get("role") == "system"]
        if sys_msgs:
            sys_msgs[-1]["content"] = f"{sys_msgs[-1].get('content') or ''} {suffix}".strip()
        else:
            messages.insert(0, {"role": "system", "content": suffix})
    body = {
        "model": backend["model"],
        "messages": messages,
        "stream": False,
    }
    # Provider-specific request fields from fleet.toml, e.g. OpenRouter's {"reasoning": {"enabled": false}}
    # to keep a thinking model from spending the reply budget on thoughts nobody reads.
    body.update(backend.get("extra_body") or {})
    # Diversity controls are forwarded too: mod-ollama-chat only emits these when the
    # operator moves them off the module's hardcoded sentinels, so anything that arrives
    # here was asked for deliberately. presence/frequency are OpenAI-standard; repeat_penalty,
    # top_k and min_p are llama.cpp/LM Studio extensions that both backends accept and
    # OpenRouter ignores. Dropping them (as this loop used to) silently defeated every
    # anti-repetition setting in the module's config.
    for k_src, k_dst in (("temperature", "temperature"), ("top_p", "top_p"),
                         ("presence_penalty", "presence_penalty"),
                         ("frequency_penalty", "frequency_penalty"),
                         ("repeat_penalty", "repeat_penalty"),
                         ("top_k", "top_k"), ("min_p", "min_p")):
        if k_src in opts and opts[k_src] is not None:
            body[k_dst] = opts[k_src]
    if opts.get("num_predict"):
        body["max_tokens"] = opts["num_predict"]
    if opts.get("format") == "json":
        body["response_format"] = {"type": "json_object"}

    data = json.dumps(body).encode()
    req = urllib.request.Request(backend["url"], data=data,
                                 headers={"Content-Type": "application/json"})
    if backend.get("key"):
        req.add_header("Authorization", f"Bearer {backend['key']}")
    with record_attempt(backend["model"], context) as attempt:
        with urllib.request.urlopen(req, timeout=backend["timeout"]) as resp:
            out = json.loads(resp.read().decode())
        attempt.result = out
        content = out["choices"][0]["message"]["content"] or ""
        text = THINK_RE.sub("", content).strip()
        if opts.get("format") == "json":
            text = FENCE_RE.sub(r"\1", text).strip()
        return text, out.get("usage") or {}

def route_call(route_name, messages, opts):
    # One reading of the route table. A reload swaps the whole dict and never edits it, so everything below
    # works from a table that cannot change under it, and a reload mid-request cannot tear the chain.
    routes = ROUTES
    backends = routes.get(route_name) or routes.get(DEFAULT_ROUTE) or next(iter(routes.values()), None)
    if not backends:
        raise RuntimeError("no route has a usable backend")
    errors = []
    parent_id = uuid4().hex
    for number, b in enumerate(backends, 1):
        # By fleet.toml name, not url: several rented models share one OpenRouter url.
        name = b["name"]
        sem = b.get("sem")
        t0 = time.time()
        if sem and not sem.acquire(timeout=QUEUE_WAIT):
            log(f"route={route_name} backend={name} BUSY after {QUEUE_WAIT}s wait")
            errors.append(f"{name} busy")
            continue
        waited = int((time.time()-t0)*1000)
        try:
            raw_context = opts.get("hdm_context")
            context = dict(raw_context) if isinstance(raw_context, dict) else {}
            context.setdefault("purpose", "chat_generation")
            context.setdefault("source", "router")
            context.update(route=route_name, parent_id=parent_id, attempt=number)
            text, usage = call_backend(b, messages, opts, context)
            cost = usage.get("cost")
            log(f"route={route_name} backend={name} "
                f"ok {int((time.time()-t0)*1000)}ms (queued {waited}ms) {len(text)}ch"
                + (f" {usage.get('prompt_tokens', 0)}+{usage.get('completion_tokens', 0)}tok ${cost:.5f}"
                   if cost is not None else ""))
            return text
        except Exception as e:  # noqa: BLE001 — any backend failure → next
            log(f"route={route_name} backend={name} "
                f"FAIL {type(e).__name__}: {e}")
            errors.append(str(e))
        finally:
            if sem:
                sem.release()
    raise RuntimeError(f"all backends failed for route '{route_name}': {errors}")

# --------------------------------------------------------------- server ---

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, obj):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            return {}

    def log_message(self, *a):  # quiet default access log; we log ourselves
        pass

    # ---- GET
    def do_GET(self):
        if self.path.startswith("/api/tags"):
            models = [{"name": r, "model": r, "modified_at": now_iso(),
                       "size": 0, "details": {"family": "router"}}
                      for r in ROUTES]
            self._send(200, {"models": models})
        elif self.path.startswith("/api/version"):
            self._send(200, {"version": "0.1.0-router"})
        elif self.path.startswith("/health"):
            # `fleet` is for the dashboard's model panel: a digest of the models and route order in use, the
            # revision of the operator's saved changes it came from, and why the last reload failed, if it did.
            # No names, addresses or keys: this port is open to the network.
            self._send(200, {"ok": True, "routes": list(ROUTES), "fleet": dict(_LOADED)})
        else:
            self._send(404, {"error": "not found"})

    # ---- POST
    def do_POST(self):
        body = self._read_body()
        try:
            if self.path.startswith("/api/generate"):
                self.handle_generate(body)
            elif self.path.startswith("/api/chat"):
                self.handle_chat(body)
            elif self.path.startswith("/api/show"):
                # capability probe (mod-ollama-chat think-mode). Advertise
                # plain completion only, so 'think' is never requested.
                self._send(200, {"capabilities": ["completion"],
                                 "details": {"family": "router"}})
            elif self.path.startswith("/v1/chat/completions"):
                self.handle_openai(body)
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            log(f"ERROR {self.path}: {e}")
            self._send(500, {"error": str(e)})

    # ---- Ollama /api/generate
    def handle_generate(self, body):
        route = body.get("model") or DEFAULT_ROUTE
        opts = dict(body.get("options") or {})
        opts["format"] = body.get("format")
        opts["hdm_context"] = body.get("hdm_context") or {}
        messages = []
        if body.get("system"):
            messages.append({"role": "system", "content": body["system"]})
        messages.append({"role": "user", "content": body.get("prompt", "")})
        text = route_call(route, messages, opts)
        self._send(200, {"model": route, "created_at": now_iso(),
                         "response": text, "done": True,
                         "done_reason": "stop"})

    # ---- Ollama /api/chat
    def handle_chat(self, body):
        route = body.get("model") or DEFAULT_ROUTE
        opts = dict(body.get("options") or {})
        opts["format"] = body.get("format")
        opts["hdm_context"] = body.get("hdm_context") or {}
        messages = body.get("messages") or []
        text = route_call(route, messages, opts)
        self._send(200, {"model": route, "created_at": now_iso(),
                         "message": {"role": "assistant", "content": text},
                         "done": True, "done_reason": "stop"})

    # ---- OpenAI passthrough (for your own later services: chronicler etc.)
    def handle_openai(self, body):
        route = body.get("model") or DEFAULT_ROUTE
        opts = {"temperature": body.get("temperature"),
                "top_p": body.get("top_p"),
                "num_predict": body.get("max_tokens"),
                "hdm_context": body.get("hdm_context")}
        text = route_call(route, body.get("messages") or [], opts)
        self._send(200, {
            "id": "router-1", "object": "chat.completion",
            "created": int(time.time()), "model": route,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
        })

def main():
    log(f"router up on {BIND[0]}:{BIND[1]} routes={list(ROUTES)} "
        f"paid={sorted({b['model'] for c in ROUTES.values() for b in c if b['key']}) or 'none'}"
        + (f" saved-changes=revision {_LOADED['revision']}" if _CFG.get("_override") else ""))
    threading.Thread(target=_watch_fleet, name="fleet-reload", daemon=True).start()
    ThreadingHTTPServer(BIND, Handler).serve_forever()

if __name__ == "__main__":
    sys.exit(main())
