#!/usr/bin/env python3
"""mod-ollama-chat's RAG knowledge base as in-world knowledge.

  inworld  (one-off, done 2026-09-14) rewrite the shipped player-guide files
           into what a well-travelled resident would know, through the router.
  revise   bring the live in-world files to an era (era.py): every entry goes
           to the fleet (fleet.py lanes); the model replies KEEP when nothing
           is out of time, otherwise rewrites it. Results pass the era regex and
           the judge; a KEEP the judge flags is retried as a forced rewrite.
           The live directory is copied to --backup-dir first. ids, keywords
           and tags are kept so retrieval still matches. RAG loads only at
           worldserver startup.

Under PREMISE=isekai both write what an arrival a few days in has picked up
instead (ISEKAI_PROMPT, ISEKAI_REVISE_PROMPT), checked with the isekai word
filter and judge; native is unchanged.

Usage:
  python3 rag_inworld.py inworld [--route chronicle] [--workers 2]
  python3 rag_inworld.py revise --era classic --backup-dir DIR [--lanes a,b] [--slots lane=n]
Output: /opt/wow/server/data/ollama-rag/*.json  (inworld also writes _dropped.json.txt)
"""
import argparse
import concurrent.futures as cf
import glob
import json
import os
import re
import shutil
import sys
import threading
import urllib.request

import era as eras
import fleet

# realpath, not abspath: reached through /opt/wow/lore, a symlink into the repo (plan 23 W1).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from common import premise, site  # noqa: E402

_R = fleet._fleet.router()
# All three used to name this machine. The knowledge base ships inside the module, lands in the data
# directory, and is rewritten through the router -- all three of which site/ and fleet.toml know (23 W3).
SRC = os.path.join(site.get("CORE_DIR", "/opt/wow/azerothcore-wotlk"),
                   "modules", "mod-ollama-chat", "data", "rag")
DST = os.path.join(site.get("DATA_DIR", "/opt/wow/server/data"), "ollama-rag")
ROUTER = f"http://{_R['bind'] if _R['bind'] != '0.0.0.0' else '127.0.0.1'}:{_R['port']}/api/generate"
LORE_DIR = os.path.dirname(os.path.abspath(__file__))

PROMPT = """You are rewriting a reference note for characters who LIVE in Azeroth during the war against the Lich King. To them it is the real world, not a game.

Rewrite the note below as common knowledge a well-travelled person of that world would have, in plain prose, 40 to 110 words. Keep every true place, person, faction, creature and historical fact. Remove or translate everything that only makes sense to a game player: levels and level ranges (say "for seasoned fighters" or "dangerous to the untested" instead), experience, specs, talents as trees, damage roles like tank/healer/DPS, loot drops, respawns, instances, addons, interface, keybindings, auction house as a feature (a market or broker is fine), arena ratings, honor points, achievements, patches, servers.

If nothing of the note has meaning inside the world (for example it is about addons, the user interface or game settings), reply with exactly: DROP

Reply with only the rewritten note, or DROP. No title, no preamble.

TITLE: {title}
NOTE: {content}"""

REVISE_PROMPT = """The people of Azeroth live in this time: {setting}

Below is a note of common knowledge that was written for a later time. {instruction}

Keep every place, person, faction, creature and fact that is true in this time. Where the note names something that has not happened yet, or gives a person a title, home or fate they only reach later, rewrite that part so it is true now, or leave it out. Plain prose, 40 to 110 words, in-world: no levels as numbers, players or game terms.

Reply with only the note{keep_clause}. No title, no preamble.

TITLE: {title}
NOTE: {content}"""


# Under PREMISE=isekai the notes are what an arrival a few days in has picked up (the isekai chat prompt frames
# them as "things you have picked up since you woke here"): seen, told by locals, or heard from other arrivals.
# Practical and plain, levels as numbers allowed, and never the game's name: that is per-person (the bio).
ISEKAI_PROMPT = """You are rewriting a reference note for ordinary people from the United States and Canada who woke up a few days ago in a strange world that works like a game: they feel their level, health and skills. They do not know its history.

Rewrite the note below as what one of them could have seen, been told by the locals, or heard from other newcomers by now: practical, survival-minded knowledge (where to go, what is dangerous, who sells what, which town is which), in plain modern English, 40 to 110 words. Keep every true place, person, faction and creature. Levels as numbers are fine ("the gnolls past the river are level 10, stay away at 3"). Old history only as something a local said, never as lifelong familiarity. Never name the game, its expansions, patches, servers, addons or interface.

If nothing of the note would matter to someone living there (for example it is about addons, the user interface or game settings), reply with exactly: DROP

Reply with only the rewritten note, or DROP. No title, no preamble.

TITLE: {title}
NOTE: {content}"""

ISEKAI_REVISE_PROMPT = """{setting}

Below is a note of what newcomers pick up in their first days. {instruction}

It must be what a newcomer a few days in could have seen, been told by locals, or heard from other newcomers: practical, plain modern English, levels as numbers allowed. Keep every place, person, faction, creature and fact that is true in this time. Rewrite or leave out anything that has not happened yet, anything told as lifelong familiarity with the world's past, and any name of the game, its expansions, servers or interface. 40 to 110 words.

Reply with only the note{keep_clause}. No title, no preamble.

TITLE: {title}
NOTE: {content}"""


def get_era(name):
    """era.get for native. Under isekai, gen_backstories.get_era (the isekai word filter), plus the game's name,
    which no note every bot reads may say."""
    if not premise.is_isekai():
        return eras.get(name)
    import gen_backstories as gb
    e = gb.get_era(name)
    return dict(e, meta=re.compile(r"\b(warcraft)\b|" + e["meta"].pattern, re.I))


def judge_prompt(e, text):
    return premise.judge_prompt(e, text, 0) if premise.is_isekai() else eras.judge_prompt(e, text)


def ask(route, prompt, timeout=180):
    body = json.dumps({"model": route, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.4, "num_predict": 400}}).encode()
    req = urllib.request.Request(ROUTER, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    text = data.get("response") or data.get("message", {}).get("content", "")
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def rewrite(route, entry):
    for attempt in range(3):
        try:
            out = ask(route, (ISEKAI_PROMPT if premise.is_isekai() else PROMPT).format(
                title=entry.get("title", ""), content=entry["content"]))
        except Exception as e:  # backends can vanish (reclaim mode); retry
            err = e
            continue
        if out.strip().upper().startswith("DROP"):
            return None
        if len(out) >= 60:
            return out
        err = ValueError(f"short reply: {out!r}")
    raise RuntimeError(f"{entry['id']}: {err}")


def inworld(args):
    os.makedirs(DST, exist_ok=True)
    dropped, failed = [], []
    for path in sorted(glob.glob(os.path.join(SRC, "*.json"))):
        name = os.path.basename(path)
        dst = os.path.join(DST, name)
        if os.path.exists(dst):
            print(f"skip {name} (exists)", flush=True)
            continue
        entries = json.load(open(path))
        kept = [None] * len(entries)
        with cf.ThreadPoolExecutor(args.workers) as pool:
            futs = {pool.submit(rewrite, args.route, e): i for i, e in enumerate(entries)}
            for fut in cf.as_completed(futs):
                i = futs[fut]
                e = entries[i]
                try:
                    text = fut.result()
                except Exception as ex:
                    failed.append(str(ex))
                    continue
                if text is None:
                    dropped.append({"file": name, "id": e["id"], "title": e.get("title")})
                    continue
                kept[i] = {**e, "content": text}
        kept = [k for k in kept if k]
        tmp = dst + ".tmp"
        json.dump(kept, open(tmp, "w"), indent=2, ensure_ascii=False)
        os.replace(tmp, dst)
        print(f"{name}: kept {len(kept)}/{len(entries)}", flush=True)

    json.dump(dropped, open(os.path.join(DST, "_dropped.json.txt"), "w"), indent=2)
    print(f"done: dropped {len(dropped)}, failed {len(failed)}", flush=True)
    for f in failed:
        print("FAILED", f, flush=True)
    return 1 if failed else 0


def revise_entry(lane, attempt, e, judge, entry, results, key, review_lock):
    forced = attempt > 1
    isekai = premise.is_isekai()
    prompt = (ISEKAI_REVISE_PROMPT if isekai else REVISE_PROMPT).format(
        setting=premise.setting(e) if isekai else e["setting"], title=entry.get("title", ""), content=entry["content"],
        instruction=("It contains things that are not true in this time, so it must be rewritten." if forced else
                     "If everything in it is already true in this time, reply exactly KEEP."),
        keep_clause="" if forced else ", or KEEP")
    out = lane.chat([{"role": "user", "content": prompt}], 400, temperature=0.4,
        context={
            "purpose": "knowledge_rewrite",
            "source": "lore/rag_inworld.py",
            "stage": "revise_entry",
            "route": "batch",
        })
    keep = not forced and out.strip().upper().startswith("KEEP")
    text = entry["content"] if keep else re.sub(r"\s+", " ", out).strip()
    if not keep and len(text) < 60:
        raise ValueError(f"short reply: {out[:80]!r}")
    bad = e["meta"].search(text)
    if bad:
        raise ValueError(f"out-of-world term: {bad.group(0)!r}")
    evidence = judge.check(judge_prompt(e, text))
    if evidence:
        if attempt < fleet.MAX_ATTEMPTS:
            raise ValueError(f"judge: {evidence}")
        with review_lock, open(os.path.join(LORE_DIR, f"review-rag-{e['name']}.jsonl"), "a") as f:
            f.write(json.dumps({"entry": key, "evidence": evidence, "text": text}) + "\n")
    results[key] = text
    return "kept" if keep else "rewritten"


def revise(args):
    e = get_era(args.era)
    backup = os.path.join(args.backup_dir, "ollama-rag")
    if not os.path.exists(backup):
        shutil.copytree(DST, backup)
        print(f"live RAG copied to {backup}", flush=True)
    files = {os.path.basename(p): json.load(open(p)) for p in sorted(glob.glob(os.path.join(DST, "*.json")))}
    lanes = [lane for lane in fleet.pick_lanes(args.lanes, args.slots) if "rag" in lane.kinds]
    judge, pool = fleet.Judge(), fleet.Pool(lanes)
    results, review_lock = {}, threading.Lock()
    for name, entries in files.items():
        for entry in entries:
            key = f"{name}:{entry['id']}"
            pool.submit("rag", 1, lambda lane, attempt, entry=entry, key=key:
                        revise_entry(lane, attempt, e, judge, entry, results, key, review_lock), key)
    failures = pool.run()
    for name, entries in files.items():
        updated = [{**entry, "content": results.get(f"{name}:{entry['id']}", entry["content"])} for entry in entries]
        tmp = os.path.join(DST, name + ".tmp")
        json.dump(updated, open(tmp, "w"), indent=2, ensure_ascii=False)
        os.replace(tmp, os.path.join(DST, name))
    for j in failures:
        print(f"FAILED (left unchanged) {j['label']}: {' | '.join(j['errors'])}", flush=True)
    print(f"done: {len(results)} entries vetted for era {e['name']}, {len(failures)} failed", flush=True)
    return 1 if failures else 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("inworld")
    i.add_argument("--route", default="chronicle")
    i.add_argument("--workers", type=int, default=2)
    r = sub.add_parser("revise")
    r.add_argument("--era", required=True)
    r.add_argument("--backup-dir", required=True)
    r.add_argument("--lanes", default=fleet.DEFAULT_LANES)
    r.add_argument("--slots", default="")
    args = ap.parse_args()
    sys.exit(inworld(args) if args.cmd == "inworld" else revise(args))


if __name__ == "__main__":
    main()
