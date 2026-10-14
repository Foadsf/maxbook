// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Thin client for the local Maxbook server.  The per-launch token arrives in
// the URL fragment (never sent to the server in URLs or logs) and is kept in
// sessionStorage so reloads keep working.

let token = "";

export function initToken() {
  const m = location.hash.match(/token=([A-Za-z0-9_-]+)/);
  if (m) {
    token = m[1];
    try { sessionStorage.setItem("maxbook-token", token); } catch { /* storage may be blocked */ }
    history.replaceState(null, "", location.pathname);
  } else {
    try { token = sessionStorage.getItem("maxbook-token") || ""; } catch { token = ""; }
  }
  return token;
}

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

export async function api(method, path, body) {
  const opts = { method, headers: { "X-Maxbook-Token": token } };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new ApiError("Maxbook server is not reachable. Is it still running?", 0);
  }
  let data = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw new ApiError(data.error || res.statusText, res.status);
  return data;
}

export const get = (path) => api("GET", path);
export const post = (path, body = {}) => api("POST", path, body);
