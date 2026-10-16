"""Text-only model transport. It has no Toolbox/Store reference or write tools.

This deliberately does not relax LLMClient.next(), which still discards free
business prose. Only validated content (never reasoning_content) leaves here.
"""
from __future__ import annotations
import json
import time
import httpx
from .config import MODEL_READ_TIMEOUT_SECONDS
from .llm import ModelFailure


class TextClient:
    def __init__(self, tool_client):
        self.config = getattr(tool_client, "config", None)
        self.transport = getattr(tool_client, "transport", None)

    @property
    def configured(self):
        return bool(self.config)

    def complete(self, messages: list, deadline: float, *, max_tokens: int = 800) -> str:
        if not self.config:
            raise ModelFailure("not_configured")
        remaining = deadline - time.monotonic()
        if remaining <= .1:
            raise ModelFailure("budget_exceeded")
        # No tools/response_format/provider-specific flags: compatible with the
        # gateway's already-working basic Chat Completions request. Knowledge
        # JSON is requested in the prompt and parsed strictly by the caller.
        payload = {"model": self.config["model"], "messages": messages,
                   "stream": False, "max_tokens": max_tokens}
        timeout = httpx.Timeout(connect=min(remaining, 8), write=min(remaining, 8),
                                pool=min(remaining, 8), read=min(remaining, MODEL_READ_TIMEOUT_SECONDS))
        try:
            with httpx.Client(timeout=timeout, follow_redirects=False, transport=self.transport) as client:
                with client.stream("POST", self.config["base"] + "/chat/completions",
                                   headers={"Authorization": "Bearer " + self.config["key"]}, json=payload) as response:
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise ModelFailure("response_limit")
                        if time.monotonic() > deadline:
                            raise ModelFailure("budget_exceeded")
            try:
                doc = json.loads(body)
            except (ValueError, UnicodeError):
                raise ModelFailure("response_not_json") from None
            if (not isinstance(doc, dict) or not isinstance(doc.get("choices"), list)
                    or not doc["choices"] or not isinstance(doc["choices"][0], dict)):
                raise ModelFailure("response_shape")
            choice = doc["choices"][0]
            message = choice.get("message")
            if not isinstance(message, dict):
                raise ModelFailure("response_shape")
            if message.get("tool_calls") or message.get("function_call"):
                # Ignore rather than execute any unsolicited tool instruction.
                raise ModelFailure("invalid_tool_calls")
            if choice.get("finish_reason") != "stop":
                raise ModelFailure("incomplete")
            text = message.get("content")
            if not isinstance(text, str) or not text.strip() or len(text) > 10000:
                raise ModelFailure("response_shape")
            return text.strip()
        except ModelFailure:
            raise
        except httpx.HTTPStatusError as exc:
            raise ModelFailure("http_error", http_status=exc.response.status_code) from None
        except httpx.TimeoutException as exc:
            kinds = ((httpx.ConnectTimeout, "connect_timeout"), (httpx.ReadTimeout, "read_timeout"),
                     (httpx.WriteTimeout, "write_timeout"), (httpx.PoolTimeout, "pool_timeout"))
            raise ModelFailure(next((code for cls, code in kinds if isinstance(exc, cls)), "timeout")) from None
        except httpx.ProxyError:
            raise ModelFailure("proxy_error") from None
        except httpx.ConnectError:
            raise ModelFailure("connect_error") from None
        except httpx.ProtocolError:
            raise ModelFailure("protocol_error") from None
        except httpx.NetworkError:
            raise ModelFailure("network_error") from None
        except Exception:
            # Never include upstream errors, model text, URLs, keys or prompts.
            raise ModelFailure("provider_unavailable_or_invalid") from None
