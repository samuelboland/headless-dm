"""The dashboard's model panel, end to end except the browser: the override file laid over fleet.toml, the
checks on what a browser may send, the router following the file, and the lore gate's door.

No realm, no database, no credentials and no paid calls: every backend is a fake on loopback, every file is in
a temporary folder, and the lore gate is imported with placeholder database settings it never connects with.
Run from the repository root:  python3 -m unittest discover -s tests/fleet
"""

import importlib.util
import io
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services"))
from common import fleet_admin, fleet_config as fc, site  # noqa: E402

SECRET = "sk-test-SECRET-123"

FLEET_TOML = """\
[router]
bind = "127.0.0.1"
port = 11434
queue_wait = 2

[backends.local]
url = "{local}"
model = "qwen3-14b"
router_slots = 1
batch_slots = 2
timeout = 30
kinds = ["character"]

[backends.spare]
url = "{spare}"
model = "qwen3-next-80b"
router_slots = 2
batch_slots = 1

[backends.remote]
url = "https://openrouter.ai/api/v1"
model = "anthropic/claude-haiku-4.5"
api_key_env = "TEST_REMOTE_KEY"
router_slots = 2

[aliases]
old-name = "remote"

[routes]
ambient   = ["local", "spare"]
quality   = ["local", "remote"]
chronicle = ["spare"]
moment    = ["old-name", "local"]

[batch]
lanes = ["local", "spare"]

[judge]
backend = "local"
fallback = "remote"
"""


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FleetCase(unittest.TestCase):
    """A temporary site folder with a fleet.toml in it, and the environment pointed at it."""

    local_url = "http://127.0.0.1:1"
    spare_url = "http://127.0.0.1:2"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name)
        self.toml = self.site / "fleet.toml"
        self.override = self.site / "fleet.override.json"
        self.write_toml()
        self.addCleanup(patch.stopall)
        env = patch.dict(os.environ, FLEET_TOML=str(self.toml), ACCOUNTING_ENABLED="0",
                         ROUTER_PORT=str(free_port()))
        env.start()
        for name in ("FLEET_OVERRIDE", "TEST_REMOTE_KEY"):
            os.environ.pop(name, None)
        patch.object(site, "SITE_DIR", str(self.site)).start()
        patch.object(site, "_VALUES", {}).start()
        fc._warned.clear()

    def write_toml(self, text=None):
        self.toml.write_text(text or FLEET_TOML.format(local=self.local_url, spare=self.spare_url))

    def set_key(self, loaded=False):
        """Put the key in secrets.env. `loaded` also makes it a key this process started with, as it would be
        for a service restarted after the key was added; without it only a fresh look at the file finds it."""
        (self.site / "secrets.env").write_text(f"TEST_REMOTE_KEY={SECRET}\n")
        if loaded:
            site._VALUES["TEST_REMOTE_KEY"] = SECRET

    def write_override(self, **parts):
        doc = {"version": fc.OVERRIDE_VERSION, "revision": 1, "models": {}, "routes": {}}
        doc.update(parts)
        self.override.write_text(json.dumps(doc))

    def saved(self):
        return json.loads(self.override.read_text())


class LayeringTests(FleetCase):
    def test_no_file_leaves_fleet_toml_exactly_as_it_is(self):
        self.assertEqual(fc.load(), fc.load(overrides=False))
        self.assertNotIn("_override", fc.load())

    def test_saved_model_and_order_are_laid_over_fleet_toml(self):
        before = self.toml.read_bytes()
        self.write_override(models={"local": "qwen3-32b"}, routes={"ambient": ["spare", "local"]})
        self.assertEqual(fc.backend("local")["model"], "qwen3-32b")
        self.assertEqual([b["name"] for b in fc.routes()["ambient"]], ["spare", "local"])
        self.assertEqual(self.toml.read_bytes(), before)           # fleet.toml is never rewritten
        # The same readers the batch lanes and the judge use see the new model.
        self.assertEqual(fc.judge()["model"], "qwen3-32b")
        self.assertEqual({b["name"]: b["model"] for b in fc.batch_lanes()}["local"], "qwen3-32b")

    def test_fleet_toml_alone_is_still_available(self):
        self.write_override(models={"local": "qwen3-32b"})
        self.assertEqual(fc.load(overrides=False)["backends"]["local"]["model"], "qwen3-14b")

    def test_an_entry_that_does_not_fit_is_skipped_on_its_own_and_said_once(self):
        self.write_override(
            models={"gone": "x", "local": "good-model", "spare": "a bad model name"},
            routes={"ambient": ["spare", "gone"], "quality": ["remote", "local"],
                    "chronicle": ["spare", "spare"], "nope": ["local"]})
        said = io.StringIO()
        with redirect_stderr(said):
            cfg = fc.load()
            fc.load()
        self.assertEqual(cfg["backends"]["local"]["model"], "good-model")
        self.assertEqual(cfg["backends"]["spare"]["model"], "qwen3-next-80b")
        self.assertEqual(cfg["routes"]["ambient"], ["local", "spare"])
        self.assertEqual(cfg["routes"]["quality"], ["remote", "local"])
        self.assertEqual(cfg["routes"]["chronicle"], ["spare"])
        self.assertEqual(sum(1 for line in said.getvalue().splitlines() if "'gone'" in line and "model" in line), 1)
        self.assertEqual(sum(1 for line in said.getvalue().splitlines() if "override for route 'nope'" in line), 1)

    def test_a_file_that_cannot_be_used_is_ignored_and_carries_the_reason(self):
        for text in ("{not json", json.dumps([1]), json.dumps({"version": 99}), "x" * (fc.OVERRIDE_MAX_BYTES + 1)):
            with self.subTest(text[:20]), redirect_stderr(io.StringIO()):
                self.override.write_text(text)
                cfg = fc.load()
                self.assertEqual(cfg["backends"], fc.load(overrides=False)["backends"])
                self.assertEqual(cfg["routes"], fc.load(overrides=False)["routes"])
                self.assertTrue(cfg["_override"]["problem"])

    def test_the_built_in_fallback_is_never_changed_by_a_saved_file(self):
        self.toml.unlink()
        self.write_override(models={"local": "other-model"})
        self.assertEqual(fc.load()["backends"]["local"]["model"], "other-model")
        self.assertEqual(fc._FALLBACK["backends"]["local"]["model"], "local")

    def test_the_fingerprint_follows_models_and_order_but_not_keys(self):
        plain = fc.fingerprint()
        self.assertEqual(plain, fc.fingerprint())
        self.write_override(models={"local": "qwen3-32b"})
        changed_model = fc.fingerprint()
        self.write_override(routes={"ambient": ["spare", "local"]})
        changed_order = fc.fingerprint()
        self.assertEqual(len({plain, changed_model, changed_order}), 3)
        self.set_key()
        self.assertEqual(fc.fingerprint(), changed_order)

    def test_the_override_sits_beside_the_fleet_toml_in_use_unless_told_otherwise(self):
        self.assertEqual(Path(fc.override_path()), self.override)
        with patch.dict(os.environ, FLEET_OVERRIDE="/elsewhere/o.json"):
            self.assertEqual(fc.override_path(), "/elsewhere/o.json")


class SaveTests(FleetCase):
    def save(self, patch_, expect_changed=True):
        changed, summary = fleet_admin.save(patch_)
        self.assertEqual(changed, expect_changed)
        return summary

    def test_a_saved_model_goes_to_the_override_file_and_nowhere_else(self):
        before = self.toml.read_bytes()
        self.save({"models": {"local": "  qwen3-32b "}})
        doc = self.saved()
        self.assertEqual((doc["version"], doc["revision"], doc["models"], doc["routes"]),
                         (1, 1, {"local": "qwen3-32b"}, {}))
        self.assertEqual(stat.S_IMODE(self.override.stat().st_mode), 0o644)      # the router's user must read it
        self.assertEqual(sorted(p.name for p in self.site.iterdir()), ["fleet.override.json", "fleet.toml"])
        self.assertEqual(self.toml.read_bytes(), before)
        self.assertEqual(fc.backend("local")["model"], "qwen3-32b")

    def test_revisions_count_up_and_a_value_equal_to_fleet_toml_is_not_stored(self):
        self.save({"models": {"local": "a-model"}})
        self.save({"models": {"spare": "b-model"}})
        self.assertEqual(self.saved()["revision"], 2)
        self.save({"models": {"local": "qwen3-14b"}})            # fleet.toml's own value
        self.assertEqual(self.saved()["models"], {"spare": "b-model"})

    def test_null_puts_fleet_toml_back(self):
        self.save({"models": {"local": "a-model"}, "routes": {"ambient": ["spare", "local"]}})
        self.save({"models": {"local": None}, "routes": {"ambient": None}})
        doc = self.saved()
        self.assertEqual((doc["models"], doc["routes"]), ({}, {}))
        self.assertEqual(fc.load()["routes"]["ambient"], ["local", "spare"])

    def test_a_route_can_be_reordered_shortened_and_extended_from_defined_backends(self):
        self.save({"routes": {"ambient": ["spare", "local"]}})
        self.assertEqual([b["name"] for b in fc.routes()["ambient"]], ["spare", "local"])
        self.save({"routes": {"ambient": ["spare"]}})
        self.assertEqual([b["name"] for b in fc.routes()["ambient"]], ["spare"])
        self.save({"routes": {"ambient": ["local", "spare"]}})           # fleet.toml's own order
        self.assertEqual(self.saved()["routes"], {})

    def test_a_route_written_with_an_alias_in_fleet_toml_compares_by_real_names(self):
        self.set_key(loaded=True)
        self.save({"routes": {"moment": ["remote", "local"]}}, expect_changed=False)   # old-name is remote
        self.save({"routes": {"moment": ["local", "remote"]}})
        self.assertEqual([b["name"] for b in fc.routes()["moment"]], ["local", "remote"])

    def test_a_backend_that_needs_a_key_can_be_listed_once_its_key_is_set(self):
        self.set_key(loaded=True)
        self.save({"routes": {"ambient": ["remote", "local"]}})
        self.assertEqual([b["name"] for b in fc.routes()["ambient"]], ["remote", "local"])

    def test_what_a_browser_may_not_send_is_refused_and_nothing_is_written(self):
        long_chain = ["local"] * 17
        cases = [
            ({"backends": {"local": {"url": "http://evil"}}}, "fleet.toml"),
            ({"models": {"local": "x"}, "api_key": "sk-1"}, "secrets.env"),
            ({"models": {"local": {"url": "http://evil"}}}, "text"),
            ({"models": {"local": 5}}, "text"),
            ({"models": {"nope": "x"}}, "no backend"),
            ({"models": {"old-name": "x"}}, "no backend"),            # an alias is not a backend
            ({"models": {"local": ""}}, "empty"),
            ({"models": {"local": "has space"}}, "spaces"),
            ({"models": {"local": 'quo"te'}}, "quotes"),
            ({"models": {"local": "new\nline"}}, "spaces"),
            ({"models": {"local": "x" * 201}}, "200"),
            ({"models": {"local": "../etc"}}, "letters"),
            ({"models": {"local": "modèle"}}, "letters"),
            ({"routes": {"nope": ["local"]}}, "no route"),
            ({"routes": {"ambient": []}}, "between 1"),
            ({"routes": {"ambient": long_chain}}, "between 1"),
            ({"routes": {"ambient": "local"}}, "between 1"),
            ({"routes": {"ambient": ["local", "local"]}}, "only once"),
            ({"routes": {"ambient": ["ghost"]}}, "not a backend"),
            ({"routes": {"ambient": ["http://evil:1"]}}, "not a backend"),
            ({"routes": {"ambient": ["old-name"]}}, "not a backend"),
            ({"routes": {"ambient": [3]}}, "not a backend"),
            ({"routes": {"ambient": ["remote"]}}, "API key"),         # remote has no key here
            ({"models": []}, "object"),
            ({"routes": "x"}, "object"),
            ({"models": {"local": "x"}, "revision": "1"}, "whole number"),
            ({}, "nothing to change"),
            ([], "JSON object"),
            ("models", "JSON object"),
            (None, "JSON object"),
        ]
        for patch_, fragment in cases:
            with self.subTest(patch_ if len(str(patch_)) < 80 else str(patch_)[:80]):
                with self.assertRaises(fleet_admin.Refused) as caught:
                    fleet_admin.save(patch_)
                self.assertIn(fragment.lower(), caught.exception.message.lower())
                self.assertEqual(caught.exception.status, 400)
                self.assertFalse(self.override.exists())

    def test_a_refused_change_leaves_a_valid_file_as_it_was(self):
        self.save({"models": {"local": "a-model"}})
        before = self.override.read_bytes()
        with self.assertRaises(fleet_admin.Refused):
            fleet_admin.save({"models": {"spare": "fine-model", "local": "bad model"}})
        self.assertEqual(self.override.read_bytes(), before)       # all or nothing, not "spare" alone

    def test_a_page_that_is_out_of_date_gets_a_409_not_a_lost_change(self):
        self.save({"models": {"local": "a-model"}})
        with self.assertRaises(fleet_admin.Refused) as caught:
            fleet_admin.save({"models": {"spare": "b-model"}, "revision": 0})
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(self.saved()["models"], {"local": "a-model"})
        self.save({"models": {"spare": "b-model"}, "revision": 1})
        self.assertEqual(self.saved()["models"], {"local": "a-model", "spare": "b-model"})

    def test_saving_what_is_already_so_writes_nothing(self):
        self.save({"models": {"local": "qwen3-14b"}}, expect_changed=False)
        self.assertFalse(self.override.exists())
        self.save({"models": {"local": "a-model"}})
        stamp = self.override.stat().st_mtime_ns
        self.save({"models": {"local": "a-model"}}, expect_changed=False)
        self.assertEqual(self.override.stat().st_mtime_ns, stamp)

    def test_a_file_nobody_can_read_is_replaced_by_a_save(self):
        self.override.write_text("{garbage")
        self.save({"models": {"local": "a-model"}})
        self.assertEqual(self.saved()["models"], {"local": "a-model"})

    def test_a_write_that_fails_leaves_the_old_file_and_no_litter(self):
        self.save({"models": {"local": "a-model"}})
        before = self.override.read_bytes()
        with patch("os.replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(fleet_admin.Refused) as caught:
                fleet_admin.save({"models": {"local": "b-model"}})
        self.assertEqual(caught.exception.status, 500)
        self.assertEqual(self.override.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.site.iterdir()), ["fleet.override.json", "fleet.toml"])

    def test_a_folder_the_gate_cannot_write_in_is_said_plainly(self):
        with patch.dict(os.environ, FLEET_OVERRIDE="/nonexistent-folder/o.json"):
            with self.assertRaises(fleet_admin.Refused) as caught:
                fleet_admin.save({"models": {"local": "a-model"}})
        self.assertIn("FLEET_OVERRIDE", caught.exception.message)

    def test_saves_made_at_the_same_moment_all_survive(self):
        names = ["local", "spare", "remote"]
        start = threading.Barrier(len(names))
        errors = []

        def one(name):
            try:
                start.wait()
                for n in range(10):
                    fleet_admin.save({"models": {name: f"{name}-model-{n}"}})
            except Exception as e:                                 # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=one, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.saved()["models"], {n: f"{n}-model-9" for n in names})
        self.assertEqual(self.saved()["revision"], 30)


class ViewTests(FleetCase):
    def view(self):
        return fleet_admin.view(probe=False)

    def test_a_key_is_never_in_what_the_panel_is_given(self):
        self.set_key()
        view = self.view()
        self.assertNotIn(SECRET, json.dumps(view))
        remote = next(b for b in view["backends"] if b["name"] == "remote")
        self.assertEqual((remote["key"], remote["usable"], remote["key_name"]), ("set", True, "TEST_REMOTE_KEY"))

    def test_a_missing_key_is_reported_and_the_route_says_it_is_skipped(self):
        view = self.view()
        remote = next(b for b in view["backends"] if b["name"] == "remote")
        self.assertEqual((remote["key"], remote["usable"]), ("missing", False))
        quality = next(r for r in view["routes"] if r["name"] == "quality")
        self.assertEqual((quality["chain"], quality["skipped"]), (["local", "remote"], ["remote"]))
        local = next(b for b in view["backends"] if b["name"] == "local")
        self.assertEqual(local["key"], "not needed")

    def test_a_key_added_since_the_gate_started_shows_without_a_restart(self):
        self.assertEqual(next(b for b in self.view()["backends"] if b["name"] == "remote")["key"], "missing")
        self.set_key()
        self.assertEqual(next(b for b in self.view()["backends"] if b["name"] == "remote")["key"], "set")

    def test_it_says_what_each_backend_is_used_by(self):
        view = self.view()
        by = {b["name"]: b["used_by"] for b in view["backends"]}
        self.assertEqual(by["local"], {"routes": ["ambient", "quality", "moment"], "lane": True, "judge": "judge"})
        self.assertEqual(by["remote"]["judge"], "fallback")
        self.assertEqual(by["remote"]["routes"], ["quality", "moment"])          # old-name resolves to remote
        self.assertFalse(by["remote"]["lane"])
        self.assertEqual([lane["name"] for lane in view["batch"]["lanes"]], ["local", "spare"])
        self.assertEqual((view["judge"]["backend"], view["judge"]["fallback"]), ("local", "remote"))

    def test_changes_are_marked_and_fleet_tomls_own_values_stay_visible(self):
        fleet_admin.save({"models": {"local": "a-model"}, "routes": {"ambient": ["spare", "local"]}})
        view = self.view()
        local = next(b for b in view["backends"] if b["name"] == "local")
        self.assertEqual((local["model"], local["default_model"], local["changed"]), ("a-model", "qwen3-14b", True))
        ambient = next(r for r in view["routes"] if r["name"] == "ambient")
        self.assertEqual((ambient["chain"], ambient["default_chain"], ambient["changed"]),
                         (["spare", "local"], ["local", "spare"], True))
        self.assertFalse(next(r for r in view["routes"] if r["name"] == "chronicle")["changed"])
        self.assertEqual(view["revision"], 1)
        # The judge and the lanes show the model they now use.
        self.assertEqual(view["judge"]["model"], "a-model")
        self.assertEqual(view["batch"]["lanes"][0]["model"], "a-model")

    def test_a_lane_that_will_not_be_used_says_why(self):
        self.write_toml(FLEET_TOML.format(local=self.local_url, spare=self.spare_url)
                        .replace('lanes = ["local", "spare"]', 'lanes = ["local", "remote", "ghost"]'))
        lanes = {lane["name"]: lane["skipped"] for lane in self.view()["batch"]["lanes"]}
        self.assertEqual(lanes, {"local": None, "remote": "no key", "ghost": "not defined in fleet.toml"})

    def test_a_file_that_cannot_be_used_is_reported(self):
        self.override.write_text("{garbage")
        with redirect_stderr(io.StringIO()):
            view = self.view()
        self.assertIn("not valid JSON", view["problem"])
        self.assertEqual(view["revision"], 0)

    def test_without_a_fleet_toml_it_says_so(self):
        self.toml.unlink()
        view = self.view()
        self.assertEqual(view["source"], "built-in defaults")
        self.assertEqual([b["name"] for b in view["backends"]], ["local"])


class HealthFake:
    """A stand-in for the router's /health, answering whatever it is given."""

    def __init__(self, body):
        outer = self
        self.body = body

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                payload = json.dumps(outer.body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RouterStatusTests(FleetCase):
    def status(self, body):
        fake = HealthFake(body)
        self.addCleanup(fake.close)
        with patch.dict(os.environ, ROUTER_PORT=str(fake.port)):
            return fleet_admin.router_status(fc.load())

    def test_live_when_the_router_reports_the_same_digest(self):
        digest = fc.fingerprint()
        self.assertEqual(self.status({"ok": True, "fleet": {"digest": digest, "error": None}}), {"state": "live"})

    def test_waiting_when_it_has_not_picked_the_change_up(self):
        self.assertEqual(self.status({"ok": True, "fleet": {"digest": "0" * 12, "error": None}}), {"state": "waiting"})

    def test_error_when_it_tried_and_kept_the_old_routes(self):
        got = self.status({"ok": True, "fleet": {"digest": "0" * 12, "error": "fleet.toml has no [routes]"}})
        self.assertEqual(got, {"state": "error", "error": "fleet.toml has no [routes]"})

    def test_old_when_a_router_from_before_this_feature_does_not_report(self):
        self.assertEqual(self.status({"ok": True, "routes": ["ambient"]}), {"state": "old"})

    def test_down_when_nothing_answers(self):
        self.assertEqual(fleet_admin.router_status(fc.load(), timeout=0.5), {"state": "down"})


class ProviderFake:
    """An OpenAI-style backend that echoes the model it was asked for, and can hold its first answer back."""

    def __init__(self, hold_first=False):
        outer = self
        self.models = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.hold = hold_first
        if not hold_first:
            self.release.set()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.models.append(body["model"])
                if outer.hold:
                    outer.hold = False
                    outer.started.set()
                    outer.release.wait(10)
                payload = json.dumps({"choices": [{"message": {"content": "from " + body["model"]}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


class RouterReloadTests(FleetCase):
    def start(self, hold_first=False):
        provider = ProviderFake(hold_first)
        self.addCleanup(provider.close)
        self.local_url = self.spare_url = provider.url
        self.write_toml()
        self.router = module(f"router_{id(self)}", ROOT / "services/router/03-router.py")
        self.said = []
        self.router.log = self.said.append                   # the router's own log lines, kept out of the output
        return provider

    def chain(self, route="ambient"):
        return [b["name"] for b in self.router.ROUTES[route]]

    def test_the_routes_follow_a_saved_change_and_a_second_look_finds_nothing_new(self):
        self.start()
        self.assertEqual(self.chain(), ["local", "spare"])
        self.assertFalse(self.router.reload_fleet())                      # nothing changed yet
        fleet_admin.save({"models": {"local": "qwen3-32b"}, "routes": {"ambient": ["spare", "local"]}})
        self.assertTrue(self.router.reload_fleet())
        self.assertEqual(self.chain(), ["spare", "local"])
        self.assertEqual(self.router.ROUTES["ambient"][1]["model"], "qwen3-32b")
        self.assertEqual(self.router._LOADED["revision"], 1)
        self.assertEqual(self.router._LOADED["digest"], fc.fingerprint())
        self.assertFalse(self.router.reload_fleet())
        self.assertIn("route ambient: local,spare -> spare,local", self.said[-1])
        self.assertIn("model of local: qwen3-14b -> qwen3-32b", self.said[-1])

    def test_one_backend_object_and_so_one_cap_is_shared_by_every_route_it_is_in(self):
        self.start()
        for _ in range(2):                           # as built at start, and as rebuilt after a reload
            local = self.router.ROUTES["ambient"][0]
            self.assertEqual(local["name"], "local")
            self.assertIs(self.router.ROUTES["quality"][0], local)
            self.assertIs(self.router.ROUTES["moment"][0], local)
            fleet_admin.save({"models": {"local": "qwen3-32b" if local["model"] == "qwen3-14b" else "qwen3-14b"}})
            self.router.reload_fleet()

    def test_the_cap_survives_a_reload_and_the_old_backend_object_is_not_edited(self):
        self.start()
        old = self.router.ROUTES["ambient"][0]
        fleet_admin.save({"models": {"local": "qwen3-32b"}})
        self.router.reload_fleet()
        new = self.router.ROUTES["ambient"][0]
        self.assertIsNot(old, new)
        self.assertIs(old["sem"], new["sem"])
        self.assertEqual((old["model"], new["model"]), ("qwen3-14b", "qwen3-32b"))

    def test_a_request_in_flight_finishes_on_its_old_model_and_still_holds_the_cap(self):
        provider = self.start(hold_first=True)
        answers = []
        worker = threading.Thread(target=lambda: answers.append(self.router.route_call("ambient", [], {})))
        worker.start()
        self.assertTrue(provider.started.wait(5))
        fleet_admin.save({"models": {"local": "qwen3-32b"}, "routes": {"ambient": ["local", "spare"]}})
        self.assertTrue(self.router.reload_fleet())                       # swapped while the request is out
        # local allows one request at a time and one is in flight: the rebuilt route must not hand out a
        # second slot.
        sem = self.router.ROUTES["ambient"][0]["sem"]
        self.assertFalse(sem.acquire(blocking=False))
        provider.release.set()
        worker.join(5)
        self.assertEqual(answers, ["from qwen3-14b"])                      # the model it started with
        self.assertTrue(sem.acquire(blocking=False))                       # and the slot came back
        sem.release()
        self.assertEqual(self.router.route_call("ambient", [], {}), "from qwen3-32b")

    def test_a_reload_that_fails_keeps_the_routes_in_use_and_says_why(self):
        self.start()
        before = self.router.ROUTES
        good = self.toml.read_text()
        self.toml.write_text("[backends.local]\nurl = \"http://127.0.0.1:1\"\n")       # no [routes]
        self.assertFalse(self.router.reload_fleet())
        self.assertIs(self.router.ROUTES, before)
        self.assertIn("routes", self.router._LOADED["error"])
        self.assertEqual(self.router.route_call("ambient", [], {}), "from qwen3-14b")  # chat still answers
        self.toml.write_text(good)
        self.assertTrue(self.router.reload_fleet())
        self.assertIsNone(self.router._LOADED["error"])

    def test_a_saved_file_nobody_can_read_keeps_what_is_live_and_deleting_it_reverts(self):
        self.start()
        fleet_admin.save({"routes": {"ambient": ["spare", "local"]}})
        self.router.reload_fleet()
        self.override.write_text("{garbage")
        with redirect_stderr(io.StringIO()):
            self.assertFalse(self.router.reload_fleet())
        self.assertEqual(self.chain(), ["spare", "local"])
        self.assertIn("not valid JSON", self.router._LOADED["error"])
        self.override.unlink()
        self.assertTrue(self.router.reload_fleet())
        self.assertEqual(self.chain(), ["local", "spare"])

    def test_a_reload_that_would_leave_no_route_with_a_usable_backend_is_refused(self):
        self.start()
        only_remote = FLEET_TOML.format(local=self.local_url, spare=self.spare_url)
        for route in ("ambient", "quality", "chronicle", "moment"):
            only_remote = "\n".join(f'{route} = ["remote"]' if line.startswith(route + " ") else line
                                    for line in only_remote.splitlines())
        self.toml.write_text(only_remote)
        before = self.router.ROUTES
        self.assertFalse(self.router.reload_fleet())
        self.assertIs(self.router.ROUTES, before)
        self.assertIn("no route", self.router._LOADED["error"])

    def test_health_reports_the_fleet_in_use_without_names_or_addresses(self):
        self.start()
        fleet_admin.save({"models": {"local": "qwen3-32b"}})
        self.router.reload_fleet()
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.router.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=5) as resp:
            body = json.loads(resp.read())
        self.assertTrue(body["ok"])
        self.assertEqual(set(body["fleet"]), {"digest", "revision", "at", "error"})
        self.assertEqual((body["fleet"]["digest"], body["fleet"]["revision"]), (fc.fingerprint(), 1))
        self.assertNotIn("qwen3", json.dumps(body))
        # The panel's own check agrees.
        with patch.dict(os.environ, ROUTER_PORT=str(server.server_port)):
            self.assertEqual(fleet_admin.router_status(fc.load()), {"state": "live"})

    def test_the_watcher_applies_a_change_without_being_asked(self):
        self.start()
        stop = threading.Event()
        self.router.RELOAD_EVERY = 0.05
        watcher = threading.Thread(target=self.router._watch_fleet, args=(stop,), daemon=True)
        watcher.start()
        self.addCleanup(watcher.join, 5)
        self.addCleanup(stop.set)
        fleet_admin.save({"routes": {"ambient": ["spare", "local"]}})
        deadline = time.time() + 5
        while self.chain() != ["spare", "local"] and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.chain(), ["spare", "local"])


class GateDoorTests(FleetCase):
    TOKEN = "t" * 20

    @classmethod
    def setUpClass(cls):
        # The gate imports the lore pipeline, which asks for database settings when it is imported (it does not
        # connect). Placeholders are enough: the model door never touches a database.
        os.environ.setdefault("DB_PASS", "unused")
        os.environ.setdefault("DB_CHARACTERS", "unused")
        os.environ.setdefault("DB_WORLD", "unused")
        sys.path.insert(0, str(ROOT / "services" / "lore"))
        cls.gate = importlib.import_module("lore_gate")
        cls.shipped_default = cls.gate.MODEL_SETTINGS

    def setUp(self):
        super().setUp()
        gate = self.gate
        self.lines = []
        patch.object(gate, "TOKEN", self.TOKEN).start()
        patch.object(gate, "MODEL_SETTINGS", True).start()
        patch.object(gate, "ORIGINS", ["http://127.0.0.1:8787"]).start()
        patch.object(gate, "PAUSE_FILE", str(self.site / "PAUSE")).start()
        patch.object(gate, "log", self.lines.append).start()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), gate.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def ask(self, method, path, body=None, token=TOKEN, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}{path}", data=data, method=method,
                                     headers={"X-Lore-Token": token, "Content-Type": "application/json",
                                              "Origin": "http://127.0.0.1:8787"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read() or b"{}"), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}"), e.headers

    def test_it_ships_off(self):
        self.assertFalse(self.shipped_default)

    def test_the_token_is_needed_to_read_and_to_write(self):
        self.assertEqual(self.ask("GET", "/models", token="wrong")[0], 401)
        self.assertEqual(self.ask("POST", "/models-set", {"models": {"local": "x"}}, token="")[0], 401)
        self.assertFalse(self.override.exists())

    def test_with_the_setting_off_it_reads_as_off_and_writes_nothing(self):
        with patch.object(self.gate, "MODEL_SETTINGS", False):
            status, body, _ = self.ask("GET", "/models")
            self.assertEqual((status, body["enabled"]), (200, False))
            self.assertIn("MODEL_SETTINGS_ENABLED", body["message"])
            status, body, _ = self.ask("POST", "/models-set", {"models": {"local": "x"}})
            self.assertEqual((status, body["ok"]), (403, False))
        self.assertFalse(self.override.exists())

    def test_it_reads_the_fleet_with_the_gates_cors_headers_and_no_key(self):
        self.set_key()
        status, body, headers = self.ask("GET", "/models")
        self.assertEqual(status, 200)
        self.assertEqual([b["name"] for b in body["fleet"]["backends"]], ["local", "spare", "remote"])
        self.assertEqual(body["fleet"]["router"]["state"], "down")          # no router on this port
        self.assertNotIn(SECRET, json.dumps(body))
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://127.0.0.1:8787")
        self.assertIn("X-Lore-Token", headers["Access-Control-Allow-Headers"])

    def test_a_change_goes_through_and_is_logged(self):
        status, body, _ = self.ask("POST", "/models-set", {"models": {"local": "qwen3-32b"},
                                                          "routes": {"ambient": ["spare", "local"]}, "revision": 0})
        self.assertEqual((status, body["ok"], body["changed"]), (200, True, True))
        self.assertEqual(body["fleet"]["revision"], 1)
        self.assertEqual(self.saved()["models"], {"local": "qwen3-32b"})
        self.assertTrue(any("models: saved" in line and "qwen3-32b" in line for line in self.lines))
        status, body, _ = self.ask("POST", "/models-set", {"models": {"local": "qwen3-32b"}})
        self.assertEqual((status, body["changed"]), (200, False))

    def test_what_is_refused_stays_refused_over_http(self):
        status, body, _ = self.ask("POST", "/models-set", {"backends": {"local": {"url": "http://evil"}}})
        self.assertEqual(status, 400)
        self.assertIn("fleet.toml", body["message"])
        self.assertEqual(self.ask("POST", "/models-set", {"models": {"local": "two words"}})[0], 400)
        self.assertEqual(self.ask("POST", "/models-set", raw=b"{nope")[0], 400)
        self.assertEqual(self.ask("POST", "/models-set", raw=b"x" * (self.gate.MODELS_BODY_MAX + 1))[0], 413)
        self.assertEqual(self.ask("GET", "/models-set")[0], 404)
        self.assertFalse(self.override.exists())

    def test_a_stale_page_is_told_and_given_the_current_settings(self):
        self.ask("POST", "/models-set", {"models": {"local": "a-model"}})
        status, body, _ = self.ask("POST", "/models-set", {"models": {"spare": "b-model"}, "revision": 0})
        self.assertEqual((status, body["ok"]), (409, False))
        self.assertEqual(body["fleet"]["revision"], 1)

    def test_pause_does_not_close_it_though_it_closes_the_rest_of_the_gate(self):
        (self.site / "PAUSE").write_text("")
        self.assertEqual(self.ask("GET", "/models")[0], 200)
        self.assertEqual(self.ask("POST", "/models-set", {"models": {"local": "a-model"}})[0], 200)
        status, body, _ = self.ask("GET", "/rules")
        self.assertEqual((status, body["message"]), (503, "The gate is paused."))

    def test_the_preflight_is_answered(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}/models-set", method="OPTIONS",
                                     headers={"Origin": "http://127.0.0.1:8787"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 204)
            self.assertIn("POST", resp.headers["Access-Control-Allow-Methods"])

    def test_the_page_learns_from_the_published_file_whether_to_show_the_panel(self):
        published = self.site / "lore-edit.json"
        with patch.object(self.gate, "EDIT_JSON", str(published)), \
                patch.object(self.gate, "full_doc", lambda: {"generated": 1, "characters": []}):
            for on in (True, False):
                with patch.object(self.gate, "MODEL_SETTINGS", on):
                    self.gate.publish()
                    self.assertIs(json.loads(published.read_text())["model_settings"], on)


if __name__ == "__main__":
    unittest.main()
