"""
Thin adapter around the Gemini API (google-genai SDK).

The agent loop (agent.py) only talks to this small interface:
    start(question)              -> LLMTurn
    send_tool_results(results)   -> LLMTurn
An LLMTurn is either a final text answer or a list of tool calls.

Keeping the provider behind an adapter means the loop is testable with a fake
model (see tests/) and you can swap Gemini for another provider by writing one
more class with the same two methods.

Why a manual loop instead of the SDK's automatic function calling? Because for
evaluation we need the full trace (every tool call, argument, result, token
count) and control over max steps. It is also easier to explain.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    args: dict


@dataclass
class LLMTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class GeminiLLM:
    def __init__(self, system_prompt: str, tool_specs: list[dict], model: str | None = None,
                 temperature: float | None = None, api_key: str | None = None,
                 max_retries: int = 5):
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"])
        self.model = model or os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
        if temperature is None and os.environ.get("GEMINI_TEMPERATURE"):
            temperature = float(os.environ["GEMINI_TEMPERATURE"])
        self.config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            # tool specs are plain JSON-schema dicts, so they stay provider-neutral
            tools=[types.Tool(function_declarations=tool_specs)],
            temperature=temperature,  # None = model default (recommended for Gemini 3)
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.max_retries = max_retries
        self.contents: list = []

    def start(self, question: str) -> LLMTurn:
        t = self.types
        self.contents = [t.Content(role="user", parts=[t.Part(text=question)])]
        return self._generate()

    def send_tool_results(self, results: list[tuple[ToolCall, str]]) -> LLMTurn:
        t = self.types
        parts = [t.Part.from_function_response(name=call.name, response={"result": output})
                 for call, output in results]
        self.contents.append(t.Content(role="user", parts=parts))
        return self._generate()

    def _generate(self) -> LLMTurn:
        response = self._call_with_retry()
        candidate = response.candidates[0]
        # Append the model's content object as-is: it carries the "thought signatures"
        # Gemini needs to keep reasoning across multi-step tool calls.
        self.contents.append(candidate.content)
        calls = [ToolCall(fc.name, dict(fc.args or {})) for fc in (response.function_calls or [])]
        text = "".join(p.text for p in (candidate.content.parts or [])
                       if getattr(p, "text", None) and not getattr(p, "thought", False))
        usage = response.usage_metadata
        return LLMTurn(text=text, tool_calls=calls,
                       input_tokens=getattr(usage, "prompt_token_count", 0) or 0,
                       output_tokens=getattr(usage, "candidates_token_count", 0) or 0)

    def _call_with_retry(self):
        delay = 2.0
        for attempt in range(self.max_retries):
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=self.contents, config=self.config)
            except Exception as exc:  # noqa: BLE001
                code = getattr(exc, "code", None)
                retryable = code in (429, 500, 502, 503, 504) or "RESOURCE_EXHAUSTED" in str(exc)
                if not retryable or attempt == self.max_retries - 1:
                    raise
                time.sleep(delay)
                delay *= 2
