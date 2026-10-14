# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Optional AI helper (Claude, via the Anthropic API).

Off unless the ``anthropic`` package is installed and credentials are
configured the usual way (``ANTHROPIC_API_KEY``, ``ANTHROPIC_AUTH_TOKEN`` or
an ``ant auth login`` profile; set ``MAXBOOK_AI=1`` to enable with a profile).
The key stays in this process; the browser never sees it.  Whatever the user
asks about is sent to Anthropic, and the UI says so before the first request.

Tasks: explain, steps, simplify, maxima (write Maxima code), ask (free
question), and image (photo or scan of math -> Markdown with LaTeX).
"""

from __future__ import annotations

import base64
import os
import re

DEFAULT_MODEL = "claude-opus-5-5"
# Server-side refusal fallback ("default" routes by refusal category).
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = (
    "You are the assistant inside Maxbook, a notebook for mathematics computed with the Maxima "
    "computer algebra system. Answer in Markdown. Write all mathematics in LaTeX between $...$ "
    "(inline) or $$...$$ (display). When you give Maxima code, put it in a ```maxima fenced block, "
    "terminate every statement with ; or $, and use only functions that exist in Maxima. Be "
    "correct and concise; say so plainly when something is uncertain or cannot be done."
)

TASKS = {
    "explain": "Explain what this means and where it comes from, for a reader of the notebook.",
    "steps": "Work this out step by step, showing each intermediate result, and state the final result.",
    "simplify": ("Give the simplest equivalent form you can justify, the reasoning, and Maxima code "
                 "that checks the equivalence."),
    "maxima": ("Write Maxima code that does what is described. Reply with one ```maxima block and at "
               "most two sentences of explanation."),
    "ask": "Answer the question.",
}

IMAGE_PROMPT = (
    "Transcribe this image of mathematics into Markdown. Keep the prose, write every formula in "
    "LaTeX ($...$ inline, $$...$$ display), keep the structure (headings, lists, numbered equations "
    "as display math). Output only the transcription. If something is illegible write [illegible]."
)
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


class AIError(Exception):
    pass


def _maxima_blocks(text: str) -> list[str]:
    return [m.strip() for m in re.findall(r"```maxima\s*\n(.*?)```", text, re.DOTALL)]


class AIHelper:
    Error = AIError

    def __init__(self, client=None, model: str = DEFAULT_MODEL, enabled: bool = False, reason: str = ""):
        self.client = client
        self.model = model
        self.enabled = enabled and client is not None
        self.reason = reason

    @classmethod
    def from_environment(cls) -> AIHelper:
        model = os.environ.get("MAXBOOK_AI_MODEL", DEFAULT_MODEL)
        if os.environ.get("MAXBOOK_AI", "").lower() in ("0", "off", "false"):
            return cls(model=model, reason="switched off with MAXBOOK_AI=0")
        has_creds = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                         or os.environ.get("MAXBOOK_AI"))
        if not has_creds:
            return cls(model=model, reason="no Anthropic credentials (set ANTHROPIC_API_KEY, or "
                                           "MAXBOOK_AI=1 after `ant auth login`)")
        try:
            import anthropic
        except ImportError:
            return cls(model=model, reason="the anthropic package is not installed (pip install maxbook[ai])")
        try:
            client = anthropic.Anthropic()
        except Exception as exc:  # noqa: BLE001 - any construction failure means "not available"
            return cls(model=model, reason=f"could not create the API client: {exc}")
        return cls(client=client, model=model, enabled=True)

    def info(self) -> dict:
        return {"enabled": self.enabled, "model": self.model, "reason": self.reason,
                "notice": "Requests send the selected content to Anthropic's API."}

    # ------------------------------------------------------------------ calls
    def _call(self, content) -> str:
        import anthropic

        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                betas=[FALLBACK_BETA],
                fallbacks="default",
                messages=[{"role": "user", "content": content}],
            )
        except anthropic.AuthenticationError as exc:
            raise AIError("the API key was rejected") from exc
        except anthropic.PermissionDeniedError as exc:
            raise AIError("the API key may not use this model") from exc
        except anthropic.RateLimitError as exc:
            raise AIError("rate limited by the API; try again shortly") from exc
        except anthropic.BadRequestError as exc:
            raise AIError(f"the request was rejected: {exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise AIError(f"API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise AIError("cannot reach the Anthropic API (network)") from exc
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            why = getattr(details, "explanation", None) or "the model declined this request"
            raise AIError(f"declined: {why}")
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        if response.stop_reason == "max_tokens":
            text += "\n\n*(answer cut off at the length limit)*"
        if not text:
            raise AIError("the model returned no text")
        return text

    def ask(self, task: str, content: str, context: str = "") -> dict:
        if task not in TASKS:
            raise AIError(f"unknown task {task!r}")
        if not content.strip():
            raise AIError("select some text or a formula first")
        parts = []
        if context.strip():
            parts.append("Notebook context (earlier definitions and text):\n" + context[-6000:])
        parts.append(f"{TASKS[task]}\n\nSelection:\n{content[:12000]}")
        text = self._call("\n\n".join(parts))
        return {"markdown": text, "maxima": _maxima_blocks(text), "model": self.model}

    def image_to_markdown(self, data_url: str) -> dict:
        m = re.match(r"data:([\w/+.-]+);base64,(.+)$", data_url or "", re.DOTALL)
        if not m or m.group(1) not in IMAGE_TYPES:
            raise AIError("expected a PNG, JPEG, GIF or WebP image")
        data = m.group(2).replace("\n", "")
        if len(data) * 3 // 4 > 5 * 1024 * 1024:
            raise AIError("image is larger than 5 MB")
        try:
            base64.b64decode(data, validate=True)
        except ValueError as exc:
            raise AIError("the image data is not valid base64") from exc
        text = self._call([
            {"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": data}},
            {"type": "text", "text": IMAGE_PROMPT},
        ])
        return {"markdown": text, "model": self.model}
