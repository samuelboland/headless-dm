"""What the dashboard's model panel reads and writes: the lore gate's GET /models and POST /models-set.

The operator can see which model every part of the realm uses and change two things, nothing else:

  * the model a backend is told (`backends.<name>.model`), and
  * the order of a route's backends, chosen from backends fleet.toml already defines.

Addresses, API keys, slots, timeouts and new backends or routes are fleet.toml and secrets.env, edited by hand.
The browser cannot send them, and this module refuses them by name rather than ignoring them.

The changes are saved to `site/fleet.override.json` and laid over fleet.toml by `fleet_config.load()`. The file is
written whole and renamed into place, so the router (which watches it) and every other reader see the old file or
the new one and never half of one. fleet.toml, with its hand-written comments, is never rewritten.

This module holds no secrets and never returns one: a backend's key is reported as "set", "missing" or "not
needed", and the name of the environment variable it is read from.

Stdlib only. Nothing here touches the database or a game object.
"""

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from common import fleet_config as fc  # noqa: E402
from common import site  # noqa: E402

CHANGEABLE = ("models", "routes", "revision")

# Held for the whole read-check-write of a save: two phones saving at once must not each start from the
# same file and lose one of the changes.
_lock = threading.Lock()


class Refused(Exception):
    """A request the panel should be told no to, in words the operator can act on."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def key_state(entry):
    """'set', 'missing' or 'not needed' for one backend. Read from the files now, not from what this
    process loaded at start, so a key added since shows without restarting the gate."""
    env = (entry or {}).get("api_key_env")
    if not env:
        return "not needed"
    return "set" if site.fresh(env) else "missing"


def _revision(doc):
    n = doc.get("revision")
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0


def _chain(names, cfg):
    """A route's backends as real names, in order, each once -- what the router builds from it."""
    return list(dict.fromkeys(fc.resolve(n, cfg) for n in names or []))


def router_status(cfg, timeout=1.5):
    """Whether the router is using what is saved, from its own /health.

    {"state": "live"}      its digest matches this config
    {"state": "waiting"}   it answers but has not picked the config up yet (it looks every few seconds)
    {"state": "error"}     it tried and kept the old routes; "error" says why
    {"state": "old"}       it answers but does not report its fleet: it was started before this feature
    {"state": "down"}      it does not answer; the change applies when it starts
    """
    r = fc.router(cfg)
    host = str(r.get("bind") or "127.0.0.1")
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    port = os.environ.get("ROUTER_PORT") or site.get("ROUTER_PORT") or r.get("port", 11434)
    try:
        with urllib.request.urlopen(f"http://{host}:{int(port)}/health", timeout=timeout) as resp:
            body = json.loads(resp.read(65536).decode("utf-8"))
    except (OSError, ValueError):
        return {"state": "down"}
    fleet = body.get("fleet") if isinstance(body, dict) else None
    if not isinstance(fleet, dict):
        return {"state": "old"}
    if fleet.get("error"):
        return {"state": "error", "error": str(fleet["error"])[:200]}
    return {"state": "live" if fleet.get("digest") == fc.fingerprint(cfg) else "waiting"}


def view(probe=True):
    """Everything the panel draws, as one document. `probe=False` skips asking the router."""
    base = fc.load(overrides=False)
    cfg = fc.load()
    doc, problem = fc.read_override()
    backends = cfg.get("backends") or {}
    base_backends = base.get("backends") or {}
    chains = {r: _chain(names, cfg) for r, names in (cfg.get("routes") or {}).items()}
    base_chains = {r: _chain(names, base) for r, names in (base.get("routes") or {}).items()}

    batch = cfg.get("batch") or {}
    lane_names = _chain(batch.get("lanes") or list(backends), cfg)
    j = cfg.get("judge") or {}
    judge_main = fc.resolve(j.get("backend") or "local", cfg)
    judge_fallback = fc.resolve(j["fallback"], cfg) if j.get("fallback") else None

    def model_of(name):
        return (backends.get(name) or {}).get("model", "local")

    def used_by(name):
        return {"routes": [r for r, chain in chains.items() if name in chain],
                "lane": name in lane_names,
                "judge": "judge" if name == judge_main else "fallback" if name == judge_fallback else None}

    out_backends = []
    for name, entry in backends.items():
        entry = entry or {}
        state = key_state(entry)
        default = (base_backends.get(name) or {}).get("model", "local")
        out_backends.append({
            "name": name, "model": model_of(name), "default_model": default,
            "changed": model_of(name) != default,
            "key": state, "key_name": entry.get("api_key_env") or None, "usable": state != "missing",
            "used_by": used_by(name),
        })

    def skipped(name):
        """Why a batch lane would not be used, or None."""
        entry = backends.get(name)
        if entry is None:
            return "not defined in fleet.toml"
        if key_state(entry) == "missing":
            return "no key"
        if int(entry.get("batch_slots", 0) or 0) <= 0:
            return "no batch slots"
        return None

    out_routes = []
    for name, chain in chains.items():
        out_routes.append({
            "name": name, "chain": chain, "default_chain": base_chains.get(name, []),
            "changed": chain != base_chains.get(name, []),
            "skipped": [n for n in chain if key_state(backends.get(n)) == "missing"],
        })

    return {
        "source": "fleet.toml" if os.path.exists(fc.path()) else "built-in defaults",
        "revision": _revision(doc),
        "saved_at": doc.get("saved_at") if isinstance(doc.get("saved_at"), str) else None,
        "problem": problem,
        "max_chain": fc.MAX_CHAIN,
        "backends": out_backends,
        "routes": out_routes,
        "batch": {"lanes": [{"name": n, "model": model_of(n), "skipped": skipped(n)} for n in lane_names]},
        "judge": {"backend": judge_main, "model": model_of(judge_main),
                  "fallback": judge_fallback, "fallback_model": model_of(judge_fallback) if judge_fallback else None},
        "router": router_status(cfg) if probe else {"state": "unknown"},
    }


def _write(path, doc):
    """Whole file or none: written beside the target, flushed to disk, then renamed over it."""
    folder = os.path.dirname(path) or "."
    try:
        fd, tmp = tempfile.mkstemp(prefix=".fleet.override.", suffix=".tmp", dir=folder)
    except OSError as e:
        raise Refused(f"The gate cannot write in {folder} ({e.strerror}). Give its user write access to that "
                      f"folder, or point FLEET_OVERRIDE at a file it can write.", 500)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        # mkstemp makes the file private to the gate's user. The router runs as another user and has to read it;
        # nothing in it is secret.
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise Refused(f"The change could not be saved ({e.strerror}).", 500)


def _short(value):
    return repr(str(value)[:60])


def save(patch):
    """Check a change from the browser and, if it is allowed, save it.

    `patch` is {"models": {backend: model-or-null}, "routes": {route: [backends]-or-null}, "revision": n}.
    null puts fleet.toml's own value back. "revision", when given, is the revision the page was looking at;
    a different one means someone else saved in between, and the answer is a 409 rather than a lost change.

    Returns (changed, summary) where summary is a list of short phrases for the log. Raises Refused.
    """
    if not isinstance(patch, dict):
        raise Refused("Say what to change as a JSON object.")
    extra = sorted(set(patch) - set(CHANGEABLE))
    if extra:
        raise Refused("Only a backend's model name and the order of a route's backends can be changed here. "
                      "Addresses, keys, slots and new backends are set in fleet.toml and secrets.env "
                      f"(not accepted: {', '.join(_short(k) for k in extra[:5])}).")
    if "models" not in patch and "routes" not in patch:
        raise Refused("There is nothing to change.")
    wanted_models, wanted_routes = patch.get("models", {}), patch.get("routes", {})
    if not isinstance(wanted_models, dict) or not isinstance(wanted_routes, dict):
        raise Refused('"models" and "routes" are each an object.')
    seen = patch.get("revision")
    if seen is not None and (isinstance(seen, bool) or not isinstance(seen, int)):
        raise Refused('"revision" is a whole number.')

    with _lock:
        base = fc.load(overrides=False)
        base_backends = base.get("backends") or {}
        base_routes = base.get("routes") or {}
        doc, problem = fc.read_override()
        have = _revision(doc)
        if seen is not None and seen != have:
            raise Refused("These settings were changed somewhere else since this page loaded. "
                          "The page now shows the current ones; make the change again.", 409)

        # Start from what is in force, which drops entries that no longer fit fleet.toml.
        applied = (fc.apply_override(base, doc).get("_override") or {}).get("applied") if doc else None
        models = dict((applied or {}).get("models") or {})
        routes = {k: list(v) for k, v in ((applied or {}).get("routes") or {}).items()}
        before = (dict(models), {k: list(v) for k, v in routes.items()})
        summary = []

        for name, value in wanted_models.items():
            if name not in base_backends:
                raise Refused(f"There is no backend called {_short(name)}. Backends are defined in fleet.toml.")
            if value is None:
                models.pop(name, None)
                summary.append(f"model of {name}: back to fleet.toml's")
                continue
            try:
                model = fc.check_model(value)
            except ValueError as e:
                raise Refused(f"{name}: {e}")
            if model == (base_backends[name] or {}).get("model", "local"):
                models.pop(name, None)
            else:
                models[name] = model
            summary.append(f"model of {name}: {model}")

        for name, chain in wanted_routes.items():
            if name not in base_routes:
                raise Refused(f"There is no route called {_short(name)}. Routes are defined in fleet.toml.")
            if chain is None:
                routes.pop(name, None)
                summary.append(f"route {name}: back to fleet.toml's")
                continue
            if not isinstance(chain, list) or not 1 <= len(chain) <= fc.MAX_CHAIN:
                raise Refused(f"{name}: list between 1 and {fc.MAX_CHAIN} backends.")
            for n in chain:
                if not isinstance(n, str) or n not in base_backends:
                    raise Refused(f"{name}: {_short(n)} is not a backend fleet.toml defines. "
                                  "New backends are added in fleet.toml, not here.")
            if len(set(chain)) != len(chain):
                raise Refused(f"{name}: a backend can be in a route only once.")
            if all(key_state(base_backends[n]) == "missing" for n in chain):
                raise Refused(f"{name}: none of those backends has its API key set, so nothing would answer. "
                              "Keep at least one that works.")
            if chain == _chain(base_routes[name], base):
                routes.pop(name, None)
            else:
                routes[name] = list(chain)
            summary.append(f"route {name}: {','.join(chain)}")

        if (models, routes) == before and not problem:
            return False, []

        order = list(base_backends)
        new = {
            "version": fc.OVERRIDE_VERSION,
            "revision": have + 1,
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "models": {n: models[n] for n in order if n in models},
            "routes": {r: routes[r] for r in base_routes if r in routes},
        }
        _write(fc.override_path(), new)
        return True, summary
