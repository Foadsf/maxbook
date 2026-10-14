# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""AI helper (with a fake API client) and the collaboration authority."""

import base64
import http.client
import json
import threading
import time
from types import SimpleNamespace

import pytest

from maxbook import server
from maxbook.ai import AIError, AIHelper
from maxbook.collab import CollabError, CollabHub


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_helper(text="ok", stop_reason="end_turn", explanation=None):
    pytest.importorskip("anthropic")  # the helper maps the SDK's exception classes
    resp = SimpleNamespace(stop_reason=stop_reason,
                           stop_details=SimpleNamespace(explanation=explanation),
                           content=[SimpleNamespace(type="thinking", thinking=""),
                                    SimpleNamespace(type="text", text=text)])
    msgs = FakeMessages(resp)
    client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    return AIHelper(client=client, enabled=True), msgs


def test_ai_request_shape_and_maxima_extraction():
    helper, msgs = fake_helper("Use this:\n```maxima\nintegrate(x^2, x);\n```\nDone.")
    res = helper.ask("maxima", "integrate x squared", context="f(x) := x^2;")
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "f(x) := x^2;" in call["messages"][0]["content"]
    assert res["maxima"] == ["integrate(x^2, x);"]


def test_ai_refusal_and_bad_input():
    helper, _ = fake_helper(stop_reason="refusal", explanation="not allowed")
    with pytest.raises(AIError, match="declined: not allowed"):
        helper.ask("explain", "something")
    helper, _ = fake_helper()
    with pytest.raises(AIError, match="unknown task"):
        helper.ask("hack", "x")
    with pytest.raises(AIError, match="select"):
        helper.ask("explain", "   ")
    with pytest.raises(AIError, match="PNG"):
        helper.image_to_markdown("data:text/plain;base64,aGk=")
    with pytest.raises(AIError, match="base64"):
        helper.image_to_markdown("data:image/png;base64,***")


def test_ai_image_request():
    helper, msgs = fake_helper("$$x^2$$")
    png = base64.b64encode(b"\x89PNG fake").decode()
    assert helper.image_to_markdown(f"data:image/png;base64,{png}")["markdown"] == "$$x^2$$"
    blocks = msgs.calls[0]["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/png"


def test_ai_disabled_without_credentials(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "MAXBOOK_AI"):
        monkeypatch.delenv(var, raising=False)
    helper = AIHelper.from_environment()
    assert not helper.enabled and "credentials" in helper.reason


# ------------------------------------------------------------------ collab
def test_collab_orders_steps_and_rejects_stale_versions():
    hub = CollabHub()
    doc_id = hub.start({"type": "doc", "content": []}, None)["docId"]
    assert hub.receive(doc_id, 0, [{"s": 1}], "a") == 1
    with pytest.raises(CollabError) as exc:
        hub.receive(doc_id, 0, [{"s": 2}], "b")  # b has not seen step 1
    assert exc.value.status == 409
    assert hub.receive(doc_id, 1, [{"s": 2}, {"s": 3}], "b") == 3
    ev = hub.events(doc_id, 1, timeout=0.1)
    assert ev["steps"] == [{"s": 2}, {"s": 3}] and ev["clientIDs"] == ["b", "b"]
    with pytest.raises(CollabError) as exc:
        hub.receive("other", 3, [], "a")
    assert exc.value.status == 410


def test_collab_long_poll_wakes_on_new_steps():
    hub = CollabHub()
    doc_id = hub.start({"type": "doc"}, None)["docId"]
    result = {}
    t = threading.Thread(target=lambda: result.update(hub.events(doc_id, 0, timeout=10)))
    t.start()
    time.sleep(0.2)
    hub.receive(doc_id, 0, [{"s": 1}], "a")
    t.join(5)
    assert result["version"] == 1


def test_collab_snapshot_and_resync_and_reset():
    hub = CollabHub()
    doc_id = hub.start({"type": "doc", "v": 0}, "a.maxbook")["docId"]
    hub.receive(doc_id, 0, [{"s": 1}, {"s": 2}], "a")
    hub.snapshot(doc_id, 2, {"type": "doc", "v": 2})
    st = hub.state()
    assert st["baseVersion"] == 2 and st["steps"] == [] and st["doc"]["v"] == 2
    assert hub.events(doc_id, 1, timeout=0)["resync"]
    hub.start({"type": "doc"}, None)
    assert hub.events(doc_id, 2, timeout=0)["reset"]


# --------------------------------------------- guest role over HTTP (share)
@pytest.fixture()
def shared_app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.chdir(tmp_path)
    app = server.App(maxima_path=None, share=True)
    app.ai = AIHelper()
    httpd = server.create_server(app, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app
    httpd.shutdown()


def call(app, method, path, body=None, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
    headers = {"Host": f"127.0.0.1:{app.port}", "X-Maxbook-Token": token or app.token}
    data = json.dumps(body).encode() if body is not None else None
    if data:
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read() or b"{}")


def test_guest_can_collaborate_but_not_run_or_touch_files(shared_app):
    app = shared_app
    nb = {"format": "maxbook", "version": 2, "doc": {"type": "doc", "content": [{"type": "paragraph"}]}}
    status, started = call(app, "POST", "/api/collab/start", {"notebook": nb})
    assert status == 200
    g = app.guest_token
    assert call(app, "POST", "/api/collab/start", {"notebook": nb}, token=g)[0] == 403
    status, sess = call(app, "GET", "/api/session", token=g)
    assert status == 200 and sess["role"] == "guest" and sess["collab"]["docId"] == started["docId"]
    assert "recent" not in sess and "home" not in sess
    status, res = call(app, "POST", "/api/collab/steps",
                       {"docId": started["docId"], "version": 0, "steps": [{"stepType": "x"}], "clientID": "g1"},
                       token=g)
    assert status == 200 and res["version"] == 1
    for method, path in [("POST", "/api/run"), ("POST", "/api/save"), ("POST", "/api/open"),
                         ("GET", "/api/fs"), ("POST", "/api/interrupt"), ("POST", "/api/shutdown"),
                         ("POST", "/api/ai/ask")]:
        assert call(app, method, path, {}, token=g)[0] == 403, path
    status, host = call(app, "GET", "/api/session")
    assert host["share"]["enabled"] is True


def test_ai_endpoint_reports_disabled(shared_app):
    status, res = call(shared_app, "POST", "/api/ai/ask", {"task": "explain", "content": "x"})
    assert status == 503 and "ANTHROPIC_API_KEY" in res["error"]
