"""The model behind the widgets, on Amazon Bedrock's OpenAI-style API.

There is no backup model on purpose. A Bedrock failure reaches the child as an
error, not as a slower answer from a different model.
"""

import json
import os
import sys

import httpx

BEDROCK_URL = "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1"
MODEL = "us.openai.gpt-6-luna"
# Room for a long project and the reasoning before it.
MAX_ANSWER_TOKENS = 16000
# Both widgets give up after 30 seconds, and "Fix it for me" waits longer.
TIMEOUT_SECONDS = 50.0


class ModelError(RuntimeError):
    """The model could not be reached or returned no usable answer."""


class Model:
    def __init__(self, think: bool = True):
        """think=False turns reasoning off, for the replies a child waits on."""
        key = os.environ.get("BEDROCK_API_KEY")
        if not key:
            raise ModelError("BEDROCK_API_KEY is not set.")
        self.base = os.environ.get("BEDROCK_BASE_URL", BEDROCK_URL)
        self.model = os.environ.get("BEDROCK_MODEL", MODEL)
        self.reasoning = os.environ.get("BEDROCK_REASONING", "medium") if think else "none"
        self._client = httpx.Client(
            timeout=float(os.environ.get("BEDROCK_TIMEOUT", TIMEOUT_SECONDS)),
            headers={"Authorization": f"Bearer {key}"},
        )

    def generate(
        self,
        system: str,
        messages: list[dict],
        json_output: bool = False,
        temperature: float = 0.4,
    ) -> str:
        """messages are {"role": "user" | "model", "text": str}."""
        turns = [
            {"role": "assistant" if message["role"] == "model" else "user", "content": message["text"]}
            for message in messages
        ]
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *turns],
            "reasoning_effort": self.reasoning,
        }
        # Bedrock refuses max_tokens for GPT-6 models, and any temperature but 1 while they reason.
        if "gpt-6" in self.model:
            payload["max_completion_tokens"] = MAX_ANSWER_TOKENS
            if self.reasoning == "none":
                payload["temperature"] = temperature
        else:
            payload["max_tokens"] = MAX_ANSWER_TOKENS
            payload["temperature"] = temperature
        if json_output:
            payload["response_format"] = {"type": "json_object"}
        try:
            response = self._client.post(f"{self.base}/chat/completions", json=payload)
        except httpx.HTTPError as error:
            raise ModelError(f"Could not reach Bedrock: {error}") from error
        if response.status_code != 200:
            raise ModelError(f"Bedrock returned {response.status_code}: {response.text[:300]}")
        choices = response.json().get("choices") or []
        text = (choices[0].get("message", {}).get("content") or "").strip() if choices else ""
        if not text:
            raise ModelError("Bedrock returned an empty answer.")
        return text

    def generate_json(self, system: str, messages: list[dict]) -> object:
        # Asked twice, since a model now and then breaks the JSON of a long project.
        for attempt in range(2):
            text = self.generate(system, messages, json_output=True, temperature=0.2)
            try:
                return json.loads(text)
            except json.JSONDecodeError as error:
                print(f"model returned invalid JSON: {error}", file=sys.stderr)
                if attempt == 1:
                    raise ModelError(f"The model returned invalid JSON: {error}") from error
        raise ModelError("The model returned no JSON.")
