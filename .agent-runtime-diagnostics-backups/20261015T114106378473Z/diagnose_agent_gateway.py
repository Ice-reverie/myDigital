#!/usr/bin/env python3
"""Read-only myDigital Agent v1 gateway diagnosis (Python 3.10+).

Usage (from the project directory):
  D:\\anaconda\\python.exe diagnose_agent_gateway.py --project D:\\myDigital

Loads the project's .env (process environment wins) and reuses config.model_config.
Uses httpx and python-dotenv already required by the project. Sends ONLY fixed
synthetic prompts to the configured gateway; no chat history, SQL, appointment
or notification operations. Does not change source, .env, or business databases.
Writes a metadata-only report. No response/error prose, model reasoning, API
keys, authorization headers, session tokens, or proxy URLs are printed/saved.
A same-host /v1 probe is made only for an empty-path base that looks incorrect.
A successful run is a protocol diagnostic, NOT an end-to-end business test.
"""
from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import sys
import time
import types
from urllib.parse import urlsplit, urlunsplit

VERSION = "1.0.0"
MAX_BYTES = 262144
CONFIG_NAMES = (
    "DIGITALHELPER_LLM_PROTOCOL", "DIGITALHELPER_LLM_API_KEY",
    "DIGITALHELPER_LLM_BASE_URL", "DIGITALHELPER_LLM_MODEL",
    "DIGITALHELPER_LLM_HTTP_ALLOWLIST",
)
PROXY_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
               "http_proxy", "https_proxy", "all_proxy", "no_proxy")
SIGNALS = (
    "tool_choice", "tools", "enable_auto_tool_choice", "enable-auto-tool-choice",
    "tool_call_parser", "tool-call-parser", "reasoning_content", "max_tokens",
    "max_completion_tokens", "context_length", "api_key", "api key",
    "unauthorized", "forbidden", "model_not_found", "model not found",
    "quota", "rate limit", "insufficient", "thinking",
)
KNOWN_FINISH = {"stop", "tool_calls", "length", "content_filter", "function_call",
                "insufficient_system_resource"}
TOY_SCHEMA = [{"type": "function", "function": {
    "name": "diagnostic_ping", "description": "Read-only connectivity test. No side effects.",
    "parameters": {"type": "object", "properties": {"marker": {"type": "string"}},
                   "required": ["marker"], "additionalProperties": False},
}}]


def safe_label(value, allowed):
    """Never display arbitrary text returned by the provider."""
    if value is None:
        return None
    return value if isinstance(value, str) and value in allowed else "other"


def inspect_response(status: int, content_type: str, body: bytes, known_tools=()):
    """Return safe metadata and in-memory JSON. Raw data is NOT put in metadata."""
    lowered_type = content_type.lower()
    media = ("json" if "json" in lowered_type else "html" if "html" in lowered_type
             else "event_stream" if "event-stream" in lowered_type else "other")
    meta = {"http_status": status, "media_type": media, "response_bytes": len(body),
            "chat_response": False}
    try:
        document = json.loads(body)
    except (ValueError, UnicodeError):
        meta["result"] = "http_error" if not 200 <= status < 300 else "not_json"
        return meta, None
    if isinstance(document, dict) and "error" in document:
        # Match only a fixed vocabulary; never save the error text itself.
        err = document["error"]
        if isinstance(err, dict):
            text = " ".join(str(err.get(k, "")) for k in ("message", "type", "code", "param"))
        else:
            text = str(err)
        lower = text.lower()
        meta["error_signals"] = [s for s in SIGNALS if s in lower]
        meta["result"] = "provider_error"
        return meta, document
    if not 200 <= status < 300:
        meta["result"] = "http_error"
        return meta, document
    try:
        if not isinstance(document, dict) or not isinstance(document.get("choices"), list):
            raise ValueError
        choice = document["choices"][0]
        message = choice["message"]
        if not isinstance(choice, dict) or not isinstance(message, dict):
            raise ValueError
    except (KeyError, IndexError, TypeError, ValueError):
        meta["result"] = "unexpected_json_shape"
        return meta, document
    meta["chat_response"] = True
    meta["finish_reason"] = safe_label(choice.get("finish_reason"), KNOWN_FINISH)
    for field in ("content", "reasoning_content"):
        value = message.get(field)
        meta[field + "_present"] = isinstance(value, str) and bool(value)
        meta[field + "_chars"] = len(value) if isinstance(value, str) else 0
    if isinstance(message.get("reasoning"), str):
        meta["other_reasoning_field_present"] = True
    calls = message.get("tool_calls") or []
    meta["tool_calls_is_list"] = isinstance(calls, list)
    meta["tool_count"] = len(calls) if isinstance(calls, list) else 0
    details = []
    if isinstance(calls, list):
        for call in calls[:4]:
            if not isinstance(call, dict):
                details.append({"valid_shape": False})
                continue
            fn = call.get("function")
            fn = fn if isinstance(fn, dict) else {}
            args = fn.get("arguments")
            parsed = None
            if isinstance(args, str):
                try:
                    parsed = json.loads(args)
                except ValueError:
                    pass
            details.append({
                "name": safe_label(fn.get("name"), set(known_tools) | {"diagnostic_ping"}),
                "id_present": isinstance(call.get("id"), str) and bool(call.get("id")),
                "type_function": call.get("type") == "function",
                "arguments_is_string": isinstance(args, str),
                "arguments_is_json_object": isinstance(parsed, dict),
            })
    meta["tools"] = details
    usage = document.get("usage")
    if isinstance(usage, dict):
        meta["usage"] = {k: usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens")
                         if type(usage.get(k)) is int}
        comp = usage.get("completion_tokens_details")
        if isinstance(comp, dict) and type(comp.get("reasoning_tokens")) is int:
            meta["usage"]["reasoning_tokens"] = comp["reasoning_tokens"]
    meta["result"] = ("truncated" if meta["finish_reason"] == "length"
                      else "tool_calls" if meta["tool_count"] else "no_tool_calls")
    return meta, document


def exception_category(exc, httpx):
    # Do not use str(exc), repr(exc), traceback, or exception URLs.
    pairs = [(httpx.ConnectTimeout, "connect_timeout"), (httpx.ReadTimeout, "read_timeout"),
             (httpx.WriteTimeout, "write_timeout"), (httpx.PoolTimeout, "pool_timeout"),
             (httpx.ProxyError, "proxy_error"), (httpx.ConnectError, "connect_error"),
             (httpx.RemoteProtocolError, "remote_protocol_error"),
             (httpx.DecodingError, "decoding_error"), (httpx.TimeoutException, "timeout"),
             (httpx.HTTPError, "http_transport_error")]
    return next((code for kind, code in pairs if isinstance(exc, kind)), "local_probe_error")


def probe(httpx, config, payload, *, label, timeout, trust_env, known_tools=(), transport=None):
    """Return safe metadata, transient parsed JSON, transient raw body."""
    started = time.monotonic()
    meta = {"test": label, "read_timeout_s": timeout, "max_tokens": payload.get("max_tokens")}
    raw, document = b"", None
    try:
        options = dict(timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
                       follow_redirects=False, trust_env=trust_env)
        if transport is not None:
            options["transport"] = transport
        with httpx.Client(**options) as client:
            with client.stream("POST", config["base"] + "/chat/completions",
                               headers={"Authorization": "Bearer " + config["key"],
                                        "Content-Type": "application/json"}, json=payload) as res:
                meta["http_status"] = res.status_code
                meta["headers_after_s"] = round(time.monotonic() - started, 3)
                if 300 <= res.status_code < 400:
                    meta["result"] = "redirect_not_followed"
                    meta["redirect_location_present"] = bool(res.headers.get("location"))
                    return meta | {"elapsed_s": round(time.monotonic() - started, 3)}, None, b""
                body = bytearray()
                for chunk in res.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        meta["result"] = "response_too_large"
                        return meta | {"elapsed_s": round(time.monotonic() - started, 3)}, None, b""
                    if time.monotonic() - started > timeout * 2:
                        meta["result"] = "diagnostic_time_budget"
                        return meta | {"elapsed_s": round(time.monotonic() - started, 3)}, None, b""
                raw = bytes(body)
                details, document = inspect_response(res.status_code, res.headers.get("content-type", ""),
                                                     raw, known_tools)
                meta.update(details)
    except Exception as exc:
        meta["result"] = exception_category(exc, httpx)
    meta["elapsed_s"] = round(time.monotonic() - started, 3)
    return meta, document, raw


def v1_candidate(base, meta):
    """Never move credentials to another host, port, or scheme."""
    u = urlsplit(base)
    path_suspect = (meta.get("http_status") in {404, 405} or
                    (meta.get("http_status") == 200 and meta.get("result") in
                     {"not_json", "unexpected_json_shape"}))
    if path_suspect and not u.path.strip("/"):
        return urlunsplit((u.scheme, u.netloc, "/v1", "", ""))
    return None


def replay_parser(httpx, llm_module, config, raw, meta):
    """Check the *installed* parser using a replay; no second network request."""
    if not raw or not meta.get("chat_response"):
        return None
    try:
        transport = httpx.MockTransport(lambda req: httpx.Response(200, content=raw,
                                                  headers={"Content-Type": "application/json"}))
        instance = llm_module.LLMClient(config=config, transport=transport)
        # trust_env=False avoids environment proxy mounts during an offline replay.
        real_client = httpx.Client
        from unittest.mock import patch
        def offline_client(*args, **kwargs):
            kwargs["trust_env"] = False
            return real_client(*args, **kwargs)
        with patch.object(httpx, "Client", side_effect=offline_client):
            result = instance.next([], TOY_SCHEMA, time.monotonic() + 30)
        meta["installed_parser_accepts"] = True
        return result
    except Exception:
        meta["installed_parser_accepts"] = False
        return None


def load_modules(project):
    """Load only config/schema/transport/tool definitions, never AgentService."""
    sys.dont_write_bytecode = True
    folder = project / "vrm_demo" / "agent"
    package_name = "_mydigital_gateway_probe"
    package = types.ModuleType(package_name)
    package.__path__ = [str(folder)]
    sys.modules[package_name] = package
    loaded = {}
    # tools imports schema/store definitions but does not instantiate storage.
    for name in ("config", "llm", "tools"):
        fullname = package_name + "." + name
        spec = importlib.util.spec_from_file_location(fullname, folder / (name + ".py"))
        if spec is None or spec.loader is None:
            raise ImportError
        mod = importlib.util.module_from_spec(spec)
        sys.modules[fullname] = mod
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            spec.loader.exec_module(mod)
        loaded[name] = mod
    return loaded


def compact_assistant(message, preserve_reasoning=False):
    """Matches v1's outgoing shape; any reasoning stays ONLY in request memory."""
    value = {"role": "assistant", "content": "", "tool_calls": message.get("tool_calls", [])}
    if preserve_reasoning and isinstance(message.get("reasoning_content"), str):
        value["reasoning_content"] = message["reasoning_content"]
    return value


def mock_tool_results(message):
    """NEVER dispatch a model-selected function. Supply fixed test fixtures only."""
    results = []
    for call in message.get("tool_calls", []):
        name = call["function"]["name"]
        if name == "get_departments":
            outcome = {"ok": True, "tool": name, "fictional": True, "data": [
                {"dept_id": "diagnostic-internal", "dept_name": "内科", "location": "测试楼一层",
                 "services": "仅为协议测试，不是真实医院", "opening_hours": "09:00-17:00"}]}
        elif name == "diagnostic_ping":
            outcome = {"ok": True, "marker": "probe-one", "fictional": True}
        else:
            outcome = {"ok": False, "error": "diagnostic_does_not_execute_tools"}
        results.append({"role": "tool", "tool_call_id": call["id"],
                        "content": json.dumps(outcome, ensure_ascii=False)})
    return results


def conclusions(report):
    steps = report.get("tests", [])
    flags = []
    if report.get("same_host_v1_succeeded"):
        flags.append("BASE_PREFIX_V1_SUCCEEDED__check_BASE_URL")
    for s in steps:
        status, result = s.get("http_status"), s.get("result")
        prefix = s.get("test", "test") + ": "
        if status in {401, 403}:
            flags.append(prefix + "AUTH_OR_ACCESS_POLICY__check_key_permissions_and_gateway_access")
        elif status == 404:
            flags.append(prefix + "NOT_FOUND__check_endpoint_prefix_or_model_route")
        elif status == 429:
            flags.append(prefix + "RATE_OR_QUOTA_LIMIT__do_not_retry_repeatedly")
        elif status == 400:
            flags.append(prefix + "BAD_REQUEST__inspect_error_signals_for_protocol_or_schema")
        elif status and status >= 500:
            flags.append(prefix + "GATEWAY_OR_UPSTREAM_SERVER_ERROR")
        if result in {"read_timeout", "connect_timeout", "connect_error", "proxy_error", "remote_protocol_error"}:
            flags.append(prefix + result.upper() + "__check_network_or_service_latency")
        if result == "redirect_not_followed":
            flags.append(prefix + "REDIRECT__use_documented_API_not_login_page")
        if result in {"not_json", "unexpected_json_shape"}:
            flags.append(prefix + "NOT_CHAT_COMPLETIONS_JSON__check_API_path")
        if result == "truncated":
            flags.append(prefix + "OUTPUT_TRUNCATED__650_tokens_may_be_insufficient")
        if s.get("installed_parser_accepts") is False:
            flags.append(prefix + "CURRENT_PROJECT_PARSER_REJECTS_RESPONSE")
        if s.get("elapsed_s", 0) > 8:
            flags.append(prefix + "EXCEEDS_8S_WALL_TIME__latency_clue_not_proof_of_ReadTimeout")
        if s.get("chat_response") and result == "no_tool_calls" and s.get("tool_probe"):
            flags.append(prefix + "NO_STRUCTURED_TOOL_CALL__not_proof_model_never_supports_tools")
        if s.get("project_arguments_valid") is False:
            flags.append(prefix + "PROJECT_ARGUMENT_SCHEMA_REJECTED_CALL")
    current = next((s for s in steps if s["test"] == "project_tools_auto"), {})
    if (current.get("installed_parser_accepts") and current.get("tool_count", 0) and
            current.get("project_arguments_valid") is True):
        flags.append("PROJECT_FIRST_TOOL_REQUEST_PASSED__not_a_database_or_booking_test")
    stripped = next((s for s in steps if s["test"] == "return_tool_result_current_shape"), {})
    retained = next((s for s in steps if s["test"] == "return_tool_result_preserve_reasoning"), {})
    if stripped.get("http_status") == 400 and retained.get("chat_response"):
        flags.append("REASONING_FIELD_ROUNDTRIP_DIFFERENCE__current_client_discards_that_field")
    if any(s.get("tool_count", 0) for s in steps):
        flags.append("STRUCTURED_TOOL_CALL_OBSERVED__tool_execution_was_not_performed")
    if not flags:
        flags.append("SEE_TEST_METADATA__no_end_to_end_success_claim")
    return flags


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, default=Path.cwd())
    ap.add_argument("--timeout", type=float, default=45.0, help="Diagnostic read timeout only (default 45s).")
    ap.add_argument("--max-tokens", type=int, default=650, help="Default matches v1. Explicitly choose 2048 to test truncation.")
    ap.add_argument("--no-env-proxy", action="store_true", help="Ignore proxy environment variables for THIS probe only.")
    ap.add_argument("--no-v1-probe", action="store_true", help="Do not try the same-host /v1 path after a route mismatch.")
    ap.add_argument("--report", type=Path, help="Optional metadata JSON output (never overwrite an existing file).")
    args = ap.parse_args(argv)
    if not 1 <= args.timeout <= 120 or not 64 <= args.max_tokens <= 4096:
        ap.error("timeout must be 1..120; max-tokens must be 64..4096")
    logging.disable(logging.CRITICAL)
    project = args.project.resolve()
    if not (project / "vrm_demo" / "agent" / "config.py").is_file():
        print("[STOP] Agent files not found. Check --project.")
        return 2
    try:
        import httpx
        from dotenv import load_dotenv
    except ImportError:
        print("[STOP] Use the project's Python interpreter; httpx/python-dotenv are required.")
        return 2
    inherited = [name for name in CONFIG_NAMES if name in os.environ]
    try:
        load_dotenv(project / ".env", override=False, interpolate=False, encoding="utf-8-sig")
        modules = load_modules(project)
        config = modules["config"].model_config()
    except Exception:
        print("[STOP] Project config/import failed. No key or exception text is printed.")
        return 2
    if not config:
        print("[STOP] Config not accepted by installed agent/config.py. No requests sent.")
        return 2
    secret = config["key"]
    def redacted(value):
        if isinstance(value, str):
            return value.replace(secret, "[REDACTED]") if secret else value
        if isinstance(value, list):
            return [redacted(v) for v in value]
        if isinstance(value, dict):
            return {k: redacted(v) for k, v in value.items()}
        return value
    report = {"diagnostic_version": VERSION, "config_accepted": True,
              "endpoint": config["base"] + "/chat/completions", "model": config["model"],
              "inherited_config_names": inherited,
              "proxy_variable_names_present": [n for n in PROXY_NAMES if os.getenv(n)],
              "trust_env": not args.no_env_proxy, "tests": [],
              "privacy": "fixed prompts only; no raw response, reasoning, key, SQL or business tools",
              "source_or_env_modified": False, "real_business_tools_executed": False}
    print("myDigital gateway diagnosis " + VERSION)
    print("Endpoint:", redacted(report["endpoint"]))
    print("Model:", redacted(config["model"]))
    print("No source/.env/database changes. Only fixed prompts; real API quota may be used.")
    print("Read timeout here is", args.timeout, "seconds; the application's timeout is NOT changed.")
    if urlsplit(config["base"]).scheme == "http":
        print("[WARNING] Configured HTTP is unencrypted; use only an approved trusted network and dummy data.")
    print("Process config overrides:", ", ".join(inherited) or "none")
    print("Proxy variable names:", ", ".join(report["proxy_variable_names_present"]) or "none")
    sys.stdout.flush()
    schemas = modules["tools"].tool_schemas()
    specs = modules["tools"].SPECS
    known = tuple(specs)
    base_payload = {"model": config["model"], "stream": False, "max_tokens": args.max_tokens}
    def run(label, messages, *, tools=None, tool_choice="auto", replay=False):
        payload = base_payload | {"messages": messages}
        if tools is not None:
            payload.update(tools=tools, tool_choice=tool_choice)
        print("\n[TEST]", label, flush=True)
        meta, doc, raw = probe(httpx, config, payload, label=label, timeout=args.timeout,
                               trust_env=not args.no_env_proxy, known_tools=known)
        meta["tool_probe"] = tools is not None
        normalized = replay_parser(httpx, modules["llm"], config, raw, meta) if replay else None
        if normalized and normalized.get("tool_calls") and tools is schemas:
            valid = True
            for call in normalized["tool_calls"]:
                name = call["function"]["name"]
                try:
                    if name not in specs:
                        raise ValueError
                    specs[name].arguments.model_validate(json.loads(call["function"]["arguments"]))
                except Exception:
                    valid = False
            meta["project_arguments_valid"] = valid
        report["tests"].append(meta)
        print(json.dumps(redacted(meta), ensure_ascii=True, indent=2), flush=True)
        return meta, doc, normalized
    plain_messages = [{"role": "user", "content": "This is a connectivity test. Reply only OK."}]
    try:
        meta, doc, _ = run("basic_chat", plain_messages)
        alternative = None if args.no_v1_probe else v1_candidate(config["base"], meta)
        if alternative:
            print("[PATH] Trying ONLY the same host's /v1 prefix; no configuration file changes.")
            config = dict(config, base=alternative)
            meta, doc, _ = run("basic_chat_same_host_v1", plain_messages)
            report["same_host_v1_succeeded"] = bool(meta.get("chat_response"))
            if report["same_host_v1_succeeded"]:
                report["working_base_candidate"] = alternative
        if meta.get("chat_response"):
            today = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
            messages = [{"role": "system", "content": modules["llm"].SYSTEM + "\n北京时间日期：" + today},
                        {"role": "user", "content": "查询科室"}]
            m, d, norm = run("project_tools_auto", messages, tools=schemas, replay=True)
            chosen_messages, chosen_schema = messages, schemas
            if not (norm and norm.get("tool_calls")) and m.get("http_status") not in {401, 403, 429}:
                # A tiny schema isolates project JSON-schema incompatibility from tool support.
                toy_messages = [{"role": "system", "content": "Use the diagnostic_ping tool. Do not answer in prose."},
                                {"role": "user", "content": "Call diagnostic_ping with marker probe-one."}]
                m, d, norm = run("minimal_tool_auto", toy_messages, tools=TOY_SCHEMA, replay=True)
                chosen_messages, chosen_schema = toy_messages, TOY_SCHEMA
                if (m.get("chat_response") and not m.get("tool_count") and
                        m.get("finish_reason") == "stop"):
                    m, d, norm = run("minimal_tool_named_choice", toy_messages, tools=TOY_SCHEMA,
                                    tool_choice={"type": "function", "function": {"name": "diagnostic_ping"}}, replay=True)
            if norm and norm.get("tool_calls") and d and d.get("choices"):
                original_message = d["choices"][0]["message"]
                tool_messages = mock_tool_results(norm)
                second_messages = chosen_messages + [norm] + tool_messages
                second, _, _ = run("return_tool_result_current_shape", second_messages,
                                    tools=chosen_schema, replay=True)
                if (second.get("http_status") == 400 and
                        isinstance(original_message.get("reasoning_content"), str) and
                        "reasoning_content" not in norm):
                    # Only retransmit to the configured provider in memory; never display/save it.
                    retained = compact_assistant(norm)
                    retained["reasoning_content"] = original_message["reasoning_content"]
                    run("return_tool_result_preserve_reasoning", chosen_messages + [retained] + tool_messages,
                        tools=chosen_schema, replay=True)
        else:
            print("[STOP] Basic Chat Completions response not obtained; further tool probes skipped.")
    except KeyboardInterrupt:
        report["interrupted"] = True
        print("\n[STOP] Interrupted. No business operation was performed.")
    except Exception:
        report["local_diagnostic_error"] = True
        print("[STOP] Local probe failure. Raw exception text intentionally hidden.")
    report["conclusions"] = conclusions(report)
    output = redacted(report)
    print("\n=== DIAGNOSIS ===")
    for flag in output["conclusions"]:
        print("-", flag)
    print("No raw provider error or reasoning text was saved. No tool/database operation was executed.")
    if args.report:
        target = args.report.resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = project / "output" / "agent" / ("gateway-diagnosis-" + stamp + ".json")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as stream:
            json.dump(output, stream, ensure_ascii=True, indent=2)
        print("Report:", str(target))
    except Exception:
        print("[NOTE] Report not saved (existing file or permission issue). Console metadata remains usable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
