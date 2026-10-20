#!/usr/bin/env python3
"""Put conf/*.overrides into the live server configs (plan 23 W4). The reverse of conf-overrides.py.

    python3 ops/scripts/conf-apply.py [--etc <dir>] [--only worldserver,playerbots] [--dry-run]

For each conf/<name>.overrides -- and, when site/site.env sets PREMISE (services/common/premise.py), the
premise's own conf/<premise>/<name>.overrides laid over it: the same key takes the premise's value, a key
the base does not set is added, and a premise file with no base file is applied on its own:

  * if the live <name>.conf is missing, start from the installed <name>.conf.dist;
  * replace each key's line in place, or append it if the .dist has never heard of it -- our own modules
    add keys (Regard, Chronicle, Company) that no .dist carries;
  * add, with the .dist's own value, any key a newer .dist has that the live conf does not mention at all.
    The conf is copied from its .dist once, so a key a module adds later never reaches it otherwise, and the
    worldserver warns "Missing property" for each at every boot. A key the live file has commented out is
    the operator's choice and is left alone;
  * fill ${PLACEHOLDERS} from site/site.env and site/secrets.env, and rebuild the database strings and
    tokens that conf-overrides.py wrote as ${REDACTED};
  * put back to the .dist's value any key that some premise layer sets but the active layers do not. A
    realm switched from isekai back to native would otherwise keep, say, Roleplay.UseRaceVoice = 0 for
    ever, because the base never mentions that key and so nothing would ever write it again;
  * back the live file up first, beside it, with a timestamp.

**It refuses to write a file that still contains a ${...} it could not resolve.** A half-substituted
config starts a server that looks healthy and behaves wrongly, which is worse than one that will not
start at all. Nothing is printed that came out of secrets.env.

Afterwards it says which changes need only `ra "ollama reload"` and which need the worldserver restarted.
"""
import argparse
import datetime as dt
import glob
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))), "services"))
from common import premise, site  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
LINE = re.compile(r"^\s*([A-Za-z0-9_.]+)\s*=\s*(.*?)\s*$")
PLACEHOLDER = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

# What conf-overrides.py redacted, and how to build it again. Values never reach stdout.
def _rebuild(key):
    table = {
        "LoginDatabaseInfo": lambda: site.dsn("auth"),
        "WorldDatabaseInfo": lambda: site.dsn("world"),
        "CharacterDatabaseInfo": lambda: site.dsn("characters"),
        "PlayerbotsDatabaseInfo": lambda: site.dsn("playerbots"),
        "Dashboard.CommandToken": lambda: site.get("DASHBOARD_TOKEN", ""),
        "OllamaChat.ApiKey": lambda: site.get("OPENROUTER_API_KEY", ""),
    }
    maker = table.get(key)
    return maker() if maker else ""


# Keys the module can pick up without a restart, via `ra "ollama reload"`.
RELOADABLE = re.compile(r"^(OllamaChat|Regard|Chronicle)\.", re.I)

# Site keys whose EMPTY value is an answer rather than a gap. site.example/site.env documents
# `MERCHANT_ACCOUNT=` and `MERCHANT_CHARACTERS=` (both empty) as "disables the seller", but site.get
# collapses empty into its default, so an operator who took that documented option had mod_ahbot.conf
# refused outright with "cannot resolve". Every OTHER placeholder left empty is a half-filled site.env
# and must still stop the write -- that is the whole point of refusing a half-substituted conf.
OPTIONAL_EMPTY = {"MERCHANT_ACCOUNT", "MERCHANT_CHARACTERS"}


def resolve(key, value):
    """The live value for one override line, or None if something is missing."""
    if value.strip() in ("${REDACTED}", '"${REDACTED}"'):
        built = _rebuild(key)
        if not built:
            return None
        return f'"{built}"' if value.strip().startswith('"') else built

    def one(m):
        got = site.get(m.group(1))
        if got not in (None, ""):
            return got
        return "" if m.group(1) in OPTIONAL_EMPTY else m.group(0)

    filled = PLACEHOLDER.sub(one, value)
    return None if PLACEHOLDER.search(filled) else filled


# Premises that carry their own layer, as conf/<premise>/<name>.overrides. Native is the base itself.
PREMISE_LAYERS = (premise.ISEKAI,)


def layers(name, which):
    """The overrides files for one conf, lowest first, as (label, path): the base, then the premise's."""
    out = [("base", os.path.join(REPO, "conf", name + ".overrides"))]
    if which in PREMISE_LAYERS:
        out.append((which, os.path.join(REPO, "conf", which, name + ".overrides")))
    return [(label, path) for label, path in out if os.path.exists(path)]


def read_layer(path):
    """(key, raw value) for each setting line of one overrides file, in order. `#` lines are notes."""
    for raw in open(path, encoding="utf-8"):
        if raw.lstrip().startswith("#"):
            continue
        m = LINE.match(raw)
        if m:
            yield m.group(1), m.group(2)


def merged(name, which):
    """{key: (raw value, label of the layer it came from)}, a later layer winning, in first-seen order."""
    out = {}
    for label, path in layers(name, which):
        for key, value in read_layer(path):
            out[key] = (value, label)
    return out


def premise_only_keys(name, which):
    """Keys some OTHER premise's layer sets for this conf, which the active layers may not."""
    keys = set()
    for other in PREMISE_LAYERS:
        path = os.path.join(REPO, "conf", other, name + ".overrides")
        if other != which and os.path.exists(path):
            keys.update(k for k, _ in read_layer(path))
    return keys


def dist_values(path):
    out = {}
    if os.path.exists(path):
        for raw in open(path, encoding="utf-8", errors="replace"):
            m = None if raw.lstrip().startswith("#") else LINE.match(raw)
            if m and m.group(1) not in out:
                out[m.group(1)] = m.group(2)
    return out


def apply_file(name, etc, dry, which=premise.NATIVE):
    """Returns (name, changed, added, errors, origin, restored): origin maps each key a premise layer set to
    that layer's label; restored lists the keys put back to the .dist because only another premise sets them."""
    # A conf lives either at <etc>/<name>.conf (worldserver, authserver, dbimport) or at
    # <etc>/modules/<name>.conf -- and on a freshly built server ONLY the .dist exists, because the
    # build installs nothing else (src/cmake/macros/ConfigInstall.cmake installs *.conf.dist alone).
    # Each candidate must therefore be paired with its OWN .dist. Pairing a top-level name with the
    # modules/ .dist is how every main conf silently went unwritten on a clean-room realm: the guide's
    # Phase 7.1 reported "not applied" for worldserver, authserver and dbimport, and Phase 7.2 then had
    # no config to run at all.
    candidates = [os.path.join(etc, name + ".conf"), os.path.join(etc, "modules", name + ".conf")]
    live = next((p for p in candidates if os.path.exists(p)), None)
    if live is None:
        live = next((p for p in candidates if os.path.exists(p + ".dist")), None)
    if live is None:
        return name, [], [], [f"neither {name}.conf nor {name}.conf.dist exists in {etc} or {etc}/modules"], {}, []
    dist = live + ".dist"

    wanted, unresolved, origin = {}, [], {}
    for key, (value, label) in merged(name, which).items():
        if label != "base":
            origin[key] = label
        got = resolve(key, value)
        if got is None:
            unresolved.append(key)
        else:
            wanted[key] = got
    if unresolved:
        return name, [], [], [f"cannot resolve: {', '.join(unresolved)} — set them in site/ and run again"], {}, []

    # A key only another premise sets goes back to the .dist's value, which is what it was before that
    # premise ever wrote it: the base records every key it changes, so a key it does not mention is one
    # it leaves at the .dist. A premise key no .dist has stays as it is -- there is nothing to go back to.
    restored = []
    defaults = dist_values(dist)
    for key in sorted(premise_only_keys(name, which)):
        if key not in wanted and key in defaults:
            wanted[key] = defaults[key]
            restored.append(key)

    source = live if os.path.exists(live) else dist
    lines = open(source, encoding="utf-8", errors="replace").read().splitlines(keepends=True)

    changed, seen = [], set()
    for i, raw in enumerate(lines):
        if raw.lstrip().startswith("#"):
            continue
        m = LINE.match(raw)
        if m and m.group(1) in wanted:
            key, was = m.group(1), m.group(2)
            seen.add(key)
            new = wanted[key]
            # Keep the live line's own quoting. The overrides file records a secret as a bare ${REDACTED},
            # but worldserver.conf writes its DSNs quoted -- so without this, nine already-correct lines
            # are rewritten on every run and a no-op reads as nine changes. A tool that always claims to
            # have changed something is a tool nobody reads the output of.
            if len(was) >= 2 and was.startswith('"') and was.endswith('"') and not new.startswith('"'):
                new = f'"{new}"'
            if was != new:
                lines[i] = f"{key} = {new}\n"
                changed.append(key)
    missing = [k for k in wanted if k not in seen]
    if missing:
        # Our own modules' keys are in no .dist; appending is the only way they ever get there.
        lines.append(f"\n# added by conf-apply.py {dt.date.today().isoformat()}\n")
        for k in missing:
            lines.append(f"{k} = {wanted[k]}\n")
        changed += missing

    added = []
    if source == live and os.path.exists(dist):
        mentioned = set(wanted)
        for raw in lines:
            m = LINE.match(raw.lstrip().lstrip("#").lstrip())
            if m:
                mentioned.add(m.group(1))
        new = {}
        for raw in open(dist, encoding="utf-8", errors="replace"):
            m = None if raw.lstrip().startswith("#") else LINE.match(raw)
            if m and m.group(1) not in mentioned and m.group(1) not in new:
                new[m.group(1)] = m.group(2)
        if new:
            lines.append(f"\n# new in {os.path.basename(dist)}, added with its default by conf-apply.py "
                         f"{dt.date.today().isoformat()}\n")
            for k, v in new.items():
                lines.append(f"{k} = {v}\n")
            added = list(new)

    if (changed or added) and not dry:
        if os.path.exists(live):
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(live, f"{live}.{stamp}.bak")
        os.makedirs(os.path.dirname(live), exist_ok=True)
        with open(live, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.chmod(live, 0o640)
    return name, changed, added, [], origin, [k for k in restored if k in changed]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--etc", default=os.path.join(site.get("SERVER_PREFIX", "/opt/wow/server"), "etc"))
    ap.add_argument("--only", default="", help="comma-separated conf names, e.g. worldserver,playerbots")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    only = {n.strip() for n in args.only.split(",") if n.strip()}
    which = premise.current()
    print(f"premise: {which}" + (f" (conf/{which}/ laid over conf/)" if which in PREMISE_LAYERS else ""))
    names = {os.path.basename(p)[: -len(".overrides")] for p in glob.glob(os.path.join(REPO, "conf", "*.overrides"))}
    if which in PREMISE_LAYERS:
        names |= {os.path.basename(p)[: -len(".overrides")]
                  for p in glob.glob(os.path.join(REPO, "conf", which, "*.overrides"))}
    reload_keys, restart_keys, problems = [], [], []
    for name in sorted(names):
        if only and name not in only:
            continue
        name, changed, added, errs, origin, restored = apply_file(name, args.etc, args.dry_run, which)
        problems += [f"{name}: {e}" for e in errs]
        if origin:
            base = {k for k, _ in read_layer(os.path.join(REPO, "conf", name + ".overrides"))} \
                if os.path.exists(os.path.join(REPO, "conf", name + ".overrides")) else set()
            over = sum(1 for k in origin if k in base)
            print(f"{name}: {len(origin)} key(s) from conf/{which}/{name}.overrides "
                  f"({over} over the base, {len(origin) - over} the base does not set)")
        if added:
            # Each takes the .dist's default, which is what the worldserver was already falling back to
            # when the key was missing -- unless the two disagree, which only the module's code can say.
            print(f"{name}: {len(added)} new .dist key(s) {'would be added' if args.dry_run else 'added'}: "
                  f"{', '.join(added)}")
        if restored:
            print(f"{name}: {len(restored)} key(s) only another premise sets "
                  f"{'would go' if args.dry_run else 'went'} back to the .dist: {', '.join(restored)}")
        if changed:
            print(f"{name}: {len(changed)} key(s) {'would change' if args.dry_run else 'changed'}")
            for k in changed:
                (reload_keys if RELOADABLE.match(k) else restart_keys).append(f"{name}.{k}")
                if args.dry_run and k in origin:
                    print(f"    {k}  [{origin[k]}]")
        elif not errs and not added:
            print(f"{name}: already matches")

    if reload_keys and not restart_keys:
        print(f"\n{len(reload_keys)} key(s) take effect with:  . ops/env.sh && ra \"ollama reload\"")
    elif restart_keys:
        print(f"\n{len(restart_keys)} key(s) need the worldserver restarted (operator, gate G3).")
        if reload_keys:
            print(f"{len(reload_keys)} more would have needed only an ollama reload.")
    if problems:
        print("\nnot applied:")
        for p in problems:
            print(f"  {p}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
