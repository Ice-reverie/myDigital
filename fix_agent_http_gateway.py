#!/usr/bin/env python3
"""Opt-in HTTP allowlist patch for myDigital Agent v1.

No network requests. Never edits .env or reads/prints a key during patching.
Prefer HTTPS. An allowlist does NOT encrypt HTTP traffic.
Usage:
  python fix_agent_http_gateway.py --project D:\\myDigital --apply
  python fix_agent_http_gateway.py --project D:\\myDigital --check
"""
from __future__ import annotations

import argparse
import ast
import codecs
from datetime import datetime, timezone
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile

OLD = '''        valid = (url.scheme == "https" or (url.scheme == "http" and url.hostname in
                 {"localhost", "127.0.0.1", "::1"}))'''
NEW = '''        # Remote HTTP is denied unless this exact hostname is explicitly allowed.
        # This is a development exception, NOT encryption. Prefer verified HTTPS.
        http_allowlist = {
            host.strip().lower()
            for host in os.getenv("DIGITALHELPER_LLM_HTTP_ALLOWLIST", "").split(",")
            if host.strip() and "*" not in host
        }
        valid = (
            url.scheme == "https"
            or (url.scheme == "http" and (
                url.hostname in {"localhost", "127.0.0.1", "::1"}
                or url.hostname in http_allowlist
            ))
        )'''


def patch(target: Path, apply: bool) -> None:
    raw = target.read_bytes()
    bom = raw.startswith(codecs.BOM_UTF8)
    text = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in text else "\n"
    normalized = text.replace("\r\n", "\n")
    if NEW in normalized:
        print("[OK] The HTTP allowlist patch is already installed.")
        return
    if normalized.count(OLD) != 1:
        raise ValueError("Source mismatch; no files were changed.")
    updated = normalized.replace(OLD, NEW, 1)
    ast.parse(updated, filename=str(target))
    encoded = updated.replace("\n", newline).encode("utf-8")
    if bom:
        encoded = codecs.BOM_UTF8 + encoded
    if not apply:
        print("[PREVIEW] One URL-validation block matches. Use --apply to install.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = target.with_name(target.name + ".before-http-allowlist-" + stamp + ".bak")
    shutil.copy2(target, backup)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, delete=False) as f:
            temp_name = f.name
            f.write(encoded)
        os.replace(temp_name, target)
        temp_name = None
    finally:
        if temp_name:
            Path(temp_name).unlink(missing_ok=True)
    print("[OK] Updated:", target)
    print("[OK] Backup:", backup)
    print("[NOTE] .env was NOT changed. Remote HTTP is still denied by default.")
    print("[NOTE] Only for an approved HTTP-only gateway on a trusted network, add:")
    print("DIGITALHELPER_LLM_HTTP_ALLOWLIST=aigw.dlut.edu.cn")
    print("[WARNING] HTTP does not encrypt API keys or prompts. Prefer HTTPS.")
    print("[NEXT] Restart the backend after editing .env.")


def check(project: Path, target: Path) -> None:
    # Match the project's .env loading policy: process environment wins; no interpolation.
    from dotenv import load_dotenv
    names = (
        "DIGITALHELPER_LLM_API_KEY", "DIGITALHELPER_LLM_BASE_URL",
        "DIGITALHELPER_LLM_MODEL", "DIGITALHELPER_LLM_PROTOCOL",
        "DIGITALHELPER_LLM_HTTP_ALLOWLIST",
    )
    inherited = [n for n in names if n in os.environ]
    env_file = project / ".env"
    print(".env exists:", env_file.is_file())
    load_dotenv(env_file, override=False, interpolate=False, encoding="utf-8-sig")
    print("API key set:", bool(os.getenv(names[0], "").strip()))
    print("Base URL set:", bool(os.getenv(names[1], "").strip()))
    print("Model name set:", bool(os.getenv(names[2], "").strip()))
    print("Protocol is openai-compatible:",
          os.getenv(names[3], "openai-compatible").strip() == "openai-compatible")
    print("HTTP allowlist configured:", bool(os.getenv(names[4], "").strip()))
    if inherited:
        print("Process environment overrides .env for these names (values hidden):")
        for name in inherited:
            print(" -", name)
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("_agent_config_diagnostic", target)
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load config module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    accepted = module.model_config() is not None
    print("Agent config accepted:", accepted)
    print("This is an offline configuration check, NOT an API connection test.")
    print("No key, prompt or upstream response was printed; no network call was made.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    project = args.project.resolve()
    target = project / "vrm_demo" / "agent" / "config.py"
    if not target.is_file():
        print("[ERROR] Agent config.py not found under the specified project.")
        return 1
    try:
        if args.check:
            check(project, target)
        else:
            patch(target, args.apply)
    except Exception as exc:
        # Avoid leaking .env values through arbitrary exception messages.
        print("[ERROR] Operation stopped:", type(exc).__name__)
        print("No .env changes or network requests were made.")
        if isinstance(exc, ValueError):
            print("The source may differ from Agent v1. Do not force replacement.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
