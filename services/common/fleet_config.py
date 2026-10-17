"""The fleet, read from site/fleet.toml instead of written into the code (plan 23 W3).

Two callers with different needs read the same file:

  * the **router** wants routes — ordered failover lists of backends, with live-chat timeouts and caps;
  * **batch lore** wants lanes — the same machines, with batch caps and longer timeouts.

They are the same servers described twice, which is exactly why they were drifting: `fleet.py` and
`03-router.py` each carried their own copy of six addresses, and the judge lane was constructed in three
separate files. One file, asked by role.

A backend carries two caps and two timeouts on purpose. The Z13 has eight physical slots; live chat may
use four and batch takes three, so neither ever takes all eight. One number could not say that.

Falls back to the values that were hardcoded before this existed, so a realm with no fleet.toml still
runs — the same way site.py falls back to worldserver.conf.

**The operator's own changes are a second file, laid over this one.** The dashboard's model panel (lore
gate, `fleet_admin.py`) saves which model a backend is told and the order of a route's backends into
`site/fleet.override.json`, so the hand-commented fleet.toml is never rewritten by a program. `load()` puts
that file on top, and everything that reads the fleet through it sees the change. The file can change only
two things -- a backend's model name and a route's list of already-defined backends -- and a hand-edited
file that asks for anything else, or names something fleet.toml does not have, is ignored for that entry,
loudly and once. Delete the file and the realm is exactly what fleet.toml says.
"""

import copy
import hashlib
import json
import os
import re
import sys

try:
    import tomllib                      # 3.11+
except ModuleNotFoundError:             # pragma: no cover
    tomllib = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from common import site  # noqa: E402

# What the code assumed before there was a file to ask. Kept so nothing breaks on a realm that has not
# written one; a single local llama-server is the profile the clean-room setup is tested against.
_FALLBACK = {
    "router": {"bind": "0.0.0.0", "port": 11434, "queue_wait": 20},
    "backends": {
        "local": {"url": "http://127.0.0.1:8080", "model": "local", "router_slots": 4,
                  "batch_slots": 2, "router_timeout": 90, "batch_timeout": 300,
                  "kinds": ["guild", "character", "rag", "traits"]},
    },
    "routes": {k: ["local"] for k in ("ambient", "quality", "chronicle", "prose", "utility", "moment")},
    "batch": {"lanes": ["local"]},
    "judge": {"backend": "local", "slots": 3, "timeout": 60},
}


def path():
    return os.environ.get("FLEET_TOML") or os.path.join(site.SITE_DIR, "fleet.toml")


# --- the operator's overrides ---------------------------------------------------------------------------

OVERRIDE_VERSION = 1
OVERRIDE_MAX_BYTES = 64 * 1024
MAX_CHAIN = 16
# What a model name may look like. Real ones are slugs and file names ("qwen3-14b", "anthropic/claude-haiku-4.5",
# "qwen/qwen3-next-80b:free", "llama-3.1-8b@q4_k_m"): no spaces, no quotes, no control characters. The same rule
# stops a pasted sentence being sent to a provider as a model.
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+=~-]{0,199}")


def override_path():
    """Beside the fleet.toml in use, unless FLEET_OVERRIDE says otherwise (a different user may need to
    write it than the one that owns site/)."""
    return os.environ.get("FLEET_OVERRIDE") or os.path.join(os.path.dirname(path()), "fleet.override.json")


def check_model(raw):
    """The model name to store for what was typed, or ValueError saying what is wrong, in plain words."""
    if not isinstance(raw, str):
        raise ValueError("A model name is text.")
    text = raw.strip()
    if not text:
        raise ValueError("A model name cannot be empty. Use Reset to go back to fleet.toml's.")
    if not MODEL_RE.fullmatch(text):     # fullmatch: `$` would let a trailing newline through
        raise ValueError("A model name is letters, digits and . _ : / @ + = ~ - only, up to 200 long, with no "
                         "spaces or quotes.")
    return text


_warned = set()


def _warn(message):
    """Said once per distinct message: load() runs on every request in some services."""
    if message not in _warned:
        _warned.add(message)
        print(f"fleet: {message}", file=sys.stderr, flush=True)


def read_override(p=None):
    """(document, problem). No file is no override and no problem; a file that cannot be used is both."""
    p = p or override_path()
    try:
        with open(p, "rb") as fh:
            raw = fh.read(OVERRIDE_MAX_BYTES + 1)
    except FileNotFoundError:
        return {}, None
    except OSError as e:
        return {}, f"cannot read {p}: {e.strerror or e}"
    if len(raw) > OVERRIDE_MAX_BYTES:
        return {}, f"{p} is too large to be one of ours; ignored"
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {}, f"{p} is not valid JSON; ignored"
    if not isinstance(doc, dict) or doc.get("version") != OVERRIDE_VERSION:
        return {}, f"{p} is not a version {OVERRIDE_VERSION} override file; ignored"
    return doc, None


def apply_override(cfg, doc):
    """A copy of `cfg` with the saved choices on top. The one passed in is never touched (it may be the
    module's fallback, shared by every caller). An entry that does not fit this fleet.toml is skipped on its
    own, so one stale line cannot undo the rest."""
    out = copy.deepcopy(cfg)
    backends = out.get("backends") or {}
    routes = out.get("routes") or {}
    applied = {"models": {}, "routes": {}}
    models = doc.get("models")
    for name, model in (models.items() if isinstance(models, dict) else ()):
        try:
            if not isinstance(backends.get(name), dict):
                raise ValueError(f"fleet.toml has no backend {name!r}")
            model = check_model(model)
        except ValueError as e:
            _warn(f"override for model of {name!r} ignored: {e}")
            continue
        backends[name]["model"] = model
        applied["models"][name] = model
    chains = doc.get("routes")
    for name, chain in (chains.items() if isinstance(chains, dict) else ()):
        problem = None
        if name not in routes:
            problem = f"fleet.toml has no route {name!r}"
        elif not isinstance(chain, list) or not chain or len(chain) > MAX_CHAIN:
            problem = "a route needs a short, non-empty list of backends"
        elif not all(isinstance(n, str) and isinstance(backends.get(n), dict) for n in chain):
            problem = "it names a backend fleet.toml does not define"
        elif len(set(chain)) != len(chain):
            problem = "it names a backend twice"
        if problem:
            _warn(f"override for route {name!r} ignored: {problem}")
            continue
        routes[name] = list(chain)
        applied["routes"][name] = list(chain)
    revision = doc.get("revision")
    out["_override"] = {"revision": revision if isinstance(revision, int) and revision >= 0 else 0,
                        "applied": applied}
    return out


def fingerprint(cfg=None):
    """A short digest of what the fleet says to use: each backend's model, each route's backends in order.
    The router reports it and the gate compares, so "is the router using what I saved" has an answer
    without either side sending the other its config. It does not include keys or addresses."""
    cfg = cfg or load()
    effective = {
        "models": {n: (b or {}).get("model", "local") for n, b in (cfg.get("backends") or {}).items()},
        "routes": {r: list(dict.fromkeys(resolve(n, cfg) for n in names))
                   for r, names in (cfg.get("routes") or {}).items()},
    }
    blob = json.dumps(effective, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def load(strict=False, overrides=True):
    """The whole file as a dict. `strict` refuses the fallback, for callers that would rather stop.
    `overrides=False` is fleet.toml alone, which is what the model panel compares the operator's changes to."""
    p = path()
    if not os.path.exists(p):
        if strict:
            sys.exit(f"no {p} — copy site.example/fleet.toml and describe your model servers")
        data = _FALLBACK
    else:
        if tomllib is None:
            sys.exit("python 3.11+ is needed to read fleet.toml (tomllib)")
        with open(p, "rb") as fh:
            data = tomllib.load(fh)
        for section in ("backends", "routes"):
            if not data.get(section):
                sys.exit(f"{p} has no [{section}] — see site.example/fleet.toml")
    if not overrides:
        return data
    doc, problem = read_override()
    if problem:
        _warn(problem)
        # Carried on the result so a long-running reader (the router) can tell "no changes saved" from "a file of
        # changes that cannot be used", and keep what it has instead of falling back to fleet.toml.
        out = copy.deepcopy(data)
        out["_override"] = {"revision": 0, "applied": {"models": {}, "routes": {}}, "problem": problem}
        return out
    return apply_override(data, doc) if doc else data


def resolve(name, cfg=None):
    """A backend name after [aliases]. An alias lets a realm swap a machine out without touching the
    code that names it: services still ask for "evo-quality" by name, and a fleet.toml that has moved
    that work to a rented model says `evo-quality = "remote-qwen80"`. One hop only, so a cycle cannot
    loop."""
    cfg = cfg or load()
    return (cfg.get("aliases") or {}).get(name, name)


def backend(name, cfg=None):
    """One backend's settings, with the defaults filled in. Unknown name is fatal: a typo in a route
    should say so here rather than become a silent hole in the failover list. An alias resolves first,
    and the result carries the REAL name, so logs and request accounting say what actually answered."""
    cfg = cfg or load()
    name = resolve(name, cfg)
    got = (cfg.get("backends") or {}).get(name)
    if got is None:
        known = ", ".join(sorted((cfg.get("backends") or {})))
        sys.exit(f"fleet.toml names no backend {name!r}; it has: {known}")
    out = dict(got)
    out.setdefault("model", "local")
    out.setdefault("router_slots", 4)
    out.setdefault("batch_slots", 0)
    out.setdefault("router_timeout", out.get("timeout", 60))
    out.setdefault("batch_timeout", out.get("timeout", 300))
    out.setdefault("kinds", [])
    out.setdefault("lmstudio", False)
    out.setdefault("system_suffix", None)
    out.setdefault("extra_body", {})
    out["name"] = name
    # A paid backend without its key is not an error: it drops out of every route it appears in, which
    # is what "optional fallback" has to mean for a realm that never bought one.
    key_env = out.get("api_key_env")
    # Through site.get, not os.environ: no service unit exports secrets.env, so an environ-only lookup
    # read every key as unset and silently dropped the backend from its routes.
    out["api_key"] = site.get(key_env, "") if key_env else ""
    out["usable"] = bool(out["api_key"]) if key_env else True
    return out


def routes(cfg=None):
    """{route name: [backend dicts]}, with unusable paid backends already dropped."""
    cfg = cfg or load()
    out = {}
    for name, names in (cfg.get("routes") or {}).items():
        chain, seen = [], set()
        for n in names:
            b = backend(n, cfg)
            # Two aliases of one backend in a route would be the same server tried twice on failover.
            if b["usable"] and b["name"] not in seen:
                seen.add(b["name"])
                chain.append(b)
        out[name] = chain
    return out


def batch_lanes(cfg=None):
    """The backends batch lore may use, in preference order, minus any with no batch slots."""
    cfg = cfg or load()
    names = (cfg.get("batch") or {}).get("lanes") or list(cfg.get("backends") or {})
    out, seen = [], set()
    for b in (backend(n, cfg) for n in names):
        if b["usable"] and b["batch_slots"] > 0 and b["name"] not in seen:
            seen.add(b["name"])
            out.append(b)
    return out


def judge(cfg=None):
    """The judge backend plus its own slots and timeout. One definition, not three."""
    cfg = cfg or load()
    j = dict((cfg.get("judge") or {}))
    b = backend(j.get("backend") or "local", cfg)
    b["slots"] = int(j.get("slots", 3))
    b["router_timeout"] = b["batch_timeout"] = int(j.get("timeout", 60))
    # A second backend to ask when the first refuses (a rented model answers 429 under load). Optional.
    b["fallback"] = None
    if j.get("fallback"):
        f = backend(j["fallback"], cfg)
        f["router_timeout"] = f["batch_timeout"] = b["router_timeout"]
        b["fallback"] = f
    return b


def router(cfg=None):
    cfg = cfg or load()
    r = dict(_FALLBACK["router"])
    r.update(cfg.get("router") or {})
    return r
