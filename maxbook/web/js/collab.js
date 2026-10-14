// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Foad S. Farimani
// Collaboration client (prosemirror-collab).  Always on: it also keeps several
// windows on the same computer in sync.  The server orders the steps.

import { collab as C, transform } from "../vendor/prosemirror/prosemirror.mjs";
import { schema } from "./schema.js";
import { api, get, post, ApiError } from "./api.js";

const { Step } = transform;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class CollabClient {
  constructor({ onReset, onUsers, onPath, onError, name, color, role }) {
    Object.assign(this, { onReset, onUsers, onPath, onError, name, color, role });
    this.clientID = Math.random().toString(36).slice(2, 10);
    this.view = null;
    this.docId = "";
    this.stopped = false;
    this.sending = false;
    this.lastSnapshot = 0;
    this.users = [];
  }

  /** Host: publish a document as the shared one.  Returns the starting version. */
  async start(doc, path) {
    const res = await post("/api/collab/start", {
      notebook: { format: "maxbook", version: 2, title: doc.attrs.title, doc: doc.toJSON() }, path,
    });
    this.docId = res.docId;
    this.lastSnapshot = 0;
    return res.version;
  }

  /** Anyone: load the shared document (snapshot + later steps). */
  async join() {
    const st = await get("/api/collab/state");
    if (!st.docId) return null;
    this.docId = st.docId;
    let doc = schema.nodeFromJSON(st.doc);
    for (const json of st.steps) {
      const result = Step.fromJSON(schema, json).apply(doc);
      if (result.failed) throw new Error("could not replay the shared document: " + result.failed);
      doc = result.doc;
    }
    this.lastSnapshot = st.version;
    return { doc, version: st.version, path: st.path };
  }

  plugin(version) {
    return C.collab({ version, clientID: this.clientID });
  }

  attach(view) {
    this.view = view;
    if (!this.loopRunning) this.loop();
    if (!this.beatRunning) this.heartbeat();
  }

  stop() {
    this.stopped = true;
    api("POST", "/api/collab/leave", { clientID: this.clientID }, { keepalive: true }).catch(() => {});
  }

  /** Call after every local transaction. */
  changed() { this.send(); }

  async send() {
    if (this.sending || !this.view) return;
    const sendable = C.sendableSteps(this.view.state);
    if (!sendable) return;
    this.sending = true;
    try {
      await post("/api/collab/steps", {
        docId: this.docId, version: sendable.version, clientID: String(sendable.clientID),
        steps: sendable.steps.map((s) => s.toJSON()),
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        // Someone else got there first; the event loop brings their steps,
        // then we send again (rebased).
      } else if (e instanceof ApiError && e.status === 410) {
        this.onReset?.();
      } else {
        this.onError?.(e);
        await sleep(1000);
      }
    } finally {
      this.sending = false;
    }
  }

  async loop() {
    this.loopRunning = true;
    while (!this.stopped) {
      if (!this.view || !this.docId) { await sleep(200); continue; }
      const docId = this.docId;
      const view = this.view;
      const version = C.getVersion(view.state);
      let ev;
      try {
        ev = await get(`/api/collab/events?docId=${docId}&version=${version}`);
      } catch (e) {
        this.onError?.(e);
        await sleep(2000);
        continue;
      }
      // the document was replaced locally (New/Open) while we waited: start over
      if (docId !== this.docId || view !== this.view) continue;
      if (ev.reset || ev.resync) {
        await this.onReset?.();
        continue;
      }
      if (C.getVersion(this.view.state) !== version) continue;
      if (ev.steps && ev.steps.length) {
        const steps = ev.steps.map((j) => Step.fromJSON(schema, j));
        const tr = C.receiveTransaction(this.view.state, steps, ev.clientIDs, { mapSelectionBackward: true });
        this.view.dispatch(tr);
      }
      if (ev.users) this.setUsers(ev.users);
      if (ev.path !== undefined) this.onPath?.(ev.path);
      this.maybeSnapshot();
      this.send();
    }
    this.loopRunning = false;
  }

  maybeSnapshot() {
    if (!this.view) return;
    const version = C.getVersion(this.view.state);
    if (version - this.lastSnapshot < 50 || C.sendableSteps(this.view.state)) return;
    this.lastSnapshot = version;
    post("/api/collab/snapshot", { docId: this.docId, version, doc: this.view.state.doc.toJSON() }).catch(() => {});
  }

  async heartbeat() {
    this.beatRunning = true;
    while (!this.stopped) {
      try {
        const r = await post("/api/collab/presence", { clientID: this.clientID, name: this.name, color: this.color });
        this.setUsers(r.users);
      } catch { /* ignore */ }
      await sleep(10000);
    }
    this.beatRunning = false;
  }

  setUsers(users) {
    this.users = users || [];
    this.onUsers?.(this.users.filter((u) => u.clientID !== this.clientID));
  }
}
