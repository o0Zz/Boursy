"""Transports to Claude: the Anthropic API (pay per token) or the Claude Code CLI (subscription).

Both take the same system prompt, user prompt and JSON schema, and return the parsed JSON object
with token usage. Prompts, schemas and storage are shared (analyst/service.py).
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

# USD per million tokens: input, output, cache read. Cache writes cost 1.25x input (5-minute TTL).
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-fable-5-2": (8.0, 40.0, 0.20),
}
WEB_SEARCH_USD = 0.01


class BackendError(RuntimeError):
    pass


@dataclass
class BackendResult:
    output: dict
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0
    cost_usd: float = 0.0
    cost_is_estimate: bool = False
    duration_s: float = 0.0


def estimate_cost(model: str, inp: int, out: int, cache_read: int, cache_write: int, searches: int) -> float:
    p_in, p_out, p_cr = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (
        inp * p_in + out * p_out + cache_read * p_cr + cache_write * p_in * 1.25
    ) / 1_000_000 + searches * WEB_SEARCH_USD


class ApiBackend:
    name = "api"

    def __init__(self, api_key: str, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=600)
        self.client = client

    def run(
        self, system: str, prompt: str, schema: dict, model: str, effort: str, web_search_max_uses: int
    ) -> BackendResult:
        started = time.monotonic()
        tools = []
        if web_search_max_uses > 0:
            tools.append(
                {"type": "web_search_20260209", "name": "web_search", "max_uses": web_search_max_uses}
            )
        messages: list[dict] = [{"role": "user", "content": prompt}]
        totals = {"in": 0, "out": 0, "cr": 0, "cw": 0, "ws": 0}
        response = None
        # Server tools run a sampling loop on Anthropic's side; it can pause and ask to be resumed.
        for _ in range(4):
            kwargs = {
                "model": model,
                "max_tokens": 16000,
                # The system prompt is the same for every call of a task: cache it.
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": messages,
                "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            }
            if tools:
                kwargs["tools"] = tools
            response = self.client.messages.create(**kwargs)
            u = response.usage
            totals["in"] += u.input_tokens or 0
            totals["out"] += u.output_tokens or 0
            totals["cr"] += getattr(u, "cache_read_input_tokens", 0) or 0
            totals["cw"] += getattr(u, "cache_creation_input_tokens", 0) or 0
            stu = getattr(u, "server_tool_use", None)
            totals["ws"] += (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
            if response.stop_reason != "pause_turn":
                break
            messages = [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": response.content},
            ]

        cost = estimate_cost(model, totals["in"], totals["out"], totals["cr"], totals["cw"], totals["ws"])
        result = BackendResult(
            {},
            model,
            totals["in"],
            totals["out"],
            totals["cr"],
            totals["cw"],
            totals["ws"],
            cost,
            duration_s=time.monotonic() - started,
        )
        if response.stop_reason == "refusal":
            raise BackendError("Claude declined this request (refusal)")
        if response.stop_reason == "max_tokens":
            raise BackendError("Answer cut off at max_tokens")
        texts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        if not texts:
            raise BackendError(f"No text in the answer (stop reason {response.stop_reason})")
        try:
            result.output = json.loads(texts[-1])
        except json.JSONDecodeError as exc:
            raise BackendError(f"Answer is not valid JSON: {exc}") from exc
        return result


class SubscriptionBackend:
    """Claude Code in headless mode (`claude -p`), signed in with the user's own subscription token.

    Personal use only (see SPEC section 11). The subprocess gets an explicit environment without
    ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN: in -p mode an API key would silently take precedence.
    """

    name = "subscription"

    def __init__(
        self, oauth_token: str, home: Path, binary: str = "claude", timeout_s: int = 600, runner=None
    ):
        self.token = oauth_token
        self.home = home
        self.binary = binary
        self.timeout_s = timeout_s
        self.runner = runner or subprocess.run

    def env(self) -> dict[str, str]:
        workdir = self.home
        workdir.mkdir(parents=True, exist_ok=True)
        return {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": str(workdir),
            "LANG": "C.UTF-8",
            "CLAUDE_CODE_OAUTH_TOKEN": self.token,
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_UPDATES": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }

    def run(
        self, system: str, prompt: str, schema: dict, model: str, effort: str, web_search_max_uses: int
    ) -> BackendResult:
        started = time.monotonic()
        tools = "WebSearch,WebFetch" if web_search_max_uses > 0 else ""
        cmd = [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--system-prompt",
            system,
            "--model",
            model,
            "--tools",
            tools,
            "--permission-mode",
            "dontAsk",
            "--max-turns",
            "8",
            "--no-session-persistence",
        ]
        workdir = self.home / "work"
        workdir.mkdir(parents=True, exist_ok=True)
        try:
            proc = self.runner(
                cmd,
                env=self.env(),
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BackendError(f"Claude Code CLI not found ({self.binary})") from exc
        except subprocess.TimeoutExpired as exc:
            raise BackendError(f"Claude Code timed out after {self.timeout_s} s") from exc
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            err = (proc.stderr or proc.stdout or "").strip()[:300]
            raise BackendError(f"Claude Code failed (exit {proc.returncode}): {err}") from exc
        usage = data.get("usage") or {}
        stu = usage.get("server_tool_use") or {}
        result = BackendResult(
            output={},
            model=model,
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
            cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
            web_searches=int(stu.get("web_search_requests") or 0),
            # What the API would have cost; the subscription is billed by plan limits, not tokens.
            cost_usd=float(data.get("total_cost_usd") or 0.0),
            cost_is_estimate=True,
            duration_s=time.monotonic() - started,
        )
        if data.get("is_error") or data.get("subtype") not in (None, "success"):
            raise BackendError(f"Claude Code error ({data.get('subtype')}): {str(data.get('result'))[:300]}")
        output = data.get("structured_output")
        if not isinstance(output, dict):
            raise BackendError("Claude Code returned no structured output")
        result.output = output
        return result
