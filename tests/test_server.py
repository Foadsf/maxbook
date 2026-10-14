# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""HTTP API: security checks and file operations (no Maxima needed)."""

import http.client
import json
import threading

import pytest

from maxbook import server


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.chdir(tmp_path)
    a = server.App(maxima_path=None)
    httpd = server.create_server(a, 0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield a
    httpd.shutdown()


def request(app, method, path, body=None, token=True, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
    headers = {"Host": host or f"127.0.0.1:{app.port}"}
    if token:
        headers["X-Maxbook-Token"] = app.token if token is True else token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    try:
        return resp.status, json.loads(raw)
    except ValueError:
        return resp.status, raw


def test_static_index_needs_no_token_but_has_csp(app):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
    conn.request("GET", "/", headers={"Host": f"127.0.0.1:{app.port}"})
    resp = conn.getresponse()
    assert resp.status == 200
    assert "script-src 'self'" in resp.getheader("Content-Security-Policy")
    assert b"Maxbook" in resp.read()


def test_api_requires_token(app):
    assert request(app, "GET", "/api/session", token=False)[0] == 403
    assert request(app, "GET", "/api/session", token="wrong")[0] == 403
    assert request(app, "GET", "/api/session")[0] == 200


def test_foreign_host_header_is_rejected(app):
    # DNS-rebinding: a page on evil.example resolving to 127.0.0.1
    assert request(app, "GET", "/api/session", host=f"evil.example:{app.port}")[0] == 403
    assert request(app, "GET", "/", host="evil.example")[0] == 403


def test_path_traversal_blocked(app):
    status, _ = request(app, "GET", "/../server.py")
    assert status == 404
    status, _ = request(app, "GET", "/%2e%2e/server.py")
    assert status == 404


def test_session_without_maxima_reports_missing(app):
    status, data = request(app, "GET", "/api/session")
    assert status == 200
    assert data["notebook"]["format"] == "maxbook"


def test_convert_endpoint(app):
    _, data = request(app, "POST", "/api/convert", {"latex": r"\frac{1}{2}"})
    assert data == {"maxima": "1/2;"}
    _, data = request(app, "POST", "/api/convert", {"latex": r"u(t)", "sources": ["u(t) := t^2;"]})
    assert data == {"maxima": "u(t);"}
    _, data = request(app, "POST", "/api/convert", {"latex": r"\int x"})
    assert "differential" in data["error"]


def test_save_open_export_and_listing(app, tmp_path):
    _, data = request(app, "POST", "/api/new", {"title": "Demo"})
    nb = data["notebook"]
    nb["cells"][1]["source"] = "1+1;"
    status, data = request(app, "POST", "/api/save", {"path": str(tmp_path / "demo"), "notebook": nb})
    assert status == 200 and data["path"].endswith("demo.maxbook")
    status, data = request(app, "POST", "/api/open", {"path": str(tmp_path / "demo.maxbook")})
    assert data["notebook"]["cells"][1]["source"] == "1+1;"
    status, data = request(app, "POST", "/api/export",
                           {"format": "mac", "path": str(tmp_path / "demo.mac"), "notebook": nb})
    assert status == 200 and (tmp_path / "demo.mac").read_text().strip().endswith("1+1;")
    status, data = request(app, "GET", "/api/fs?path=" + str(tmp_path).replace("\\", "/"))
    names = [e["name"] for e in data["entries"]]
    assert "demo.maxbook" in names and "demo.mac" in names
    status, data = request(app, "POST", "/api/open", {"path": str(tmp_path / "missing.maxbook")})
    assert status == 404


def test_import_reports_note_and_does_not_claim_path(app, tmp_path):
    (tmp_path / "w.mac").write_text("1+1;\n", encoding="utf-8")
    _, data = request(app, "POST", "/api/open", {"path": str(tmp_path / "w.mac")})
    assert data["path"] is None and data["suggested"].endswith("w.maxbook")
    assert "original is not changed" in data["note"]


def test_bad_json_and_unknown_route(app):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
    conn.request("POST", "/api/save", body=b"{nope", headers={
        "Host": f"127.0.0.1:{app.port}", "X-Maxbook-Token": app.token, "Content-Type": "application/json"})
    assert conn.getresponse().status == 400
    assert request(app, "GET", "/api/nothing")[0] == 404
