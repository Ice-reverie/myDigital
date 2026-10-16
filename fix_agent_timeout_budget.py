#!/usr/bin/env python3
"""Coordinated timeout patch for myDigital Agent v1 + diagnostics 1.1.0.

Stop the backend first. Preview by default; --apply creates backups.
No dependencies, network requests, .env reads/changes or business DB writes.
Use --rollback BACKUP_DIRECTORY --apply to restore unchanged patched sources.
This tunes finite waiting budgets, not model speed or server availability.
"""
from __future__ import annotations
import argparse
import ast
import codecs
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

VERSION = 'gateway-30-60-v1'
BACKUP_ROOT = '.agent-timeout-backups'
CONFIG_IMPORT = '''from .config import (Settings, AGENT_TIMEOUT_PROFILE, MODEL_READ_TIMEOUT_SECONDS,
                     AGENT_BROWSER_TIMEOUT_MS, SESSION_LEASE_SECONDS)'''
CONFIG_CONSTANTS = '''ROOT = Path(__file__).resolve().parents[2]

# AGENT_TIMEOUT_PROFILE_V1: local-demo finite waiting limits.
AGENT_TIMEOUT_PROFILE = "gateway-30-60-v1"
MODEL_READ_TIMEOUT_SECONDS = 30.0
AGENT_BROWSER_TIMEOUT_MS = 100000
SESSION_LEASE_SECONDS = 180
'''
OLD_STATUS = '''                "mode":"llm_tools" if self.client.configured else "rules_demo", "diagnostics_version":"1.1.0"}'''
NEW_STATUS = '''                "mode":"llm_tools" if self.client.configured else "rules_demo", "diagnostics_version":"1.1.0",
                "timeout_profile":AGENT_TIMEOUT_PROFILE,
                "timeouts":{"model_read_seconds":MODEL_READ_TIMEOUT_SECONDS,
                            "model_turn_budget_seconds":self.settings.model_budget,
                            "browser_agent_seconds":AGENT_BROWSER_TIMEOUT_MS / 1000,
                            "session_lease_seconds":SESSION_LEASE_SECONDS}}'''
JS_OLD_IMPORT = "import { agentChatTransport, agentFailureHint, installAgentControls } from './agent-client.js';"
JS_NEW_IMPORT = "import { agentChatTransport, agentFailureHint, installAgentControls, agentChatTimeoutMs } from './agent-client.js';"
JS_OLD_MODE = "export const isAgentMode = () => typeof window !== 'undefined' && new URL(window.location.href).searchParams.get('agent') === '1';"
JS_NEW_MODE = JS_OLD_MODE + '''
// AGENT_TIMEOUT_PROFILE_V1: only the Agent route gets the longer wait.
export const agentChatTimeoutMs = () => isAgentMode() ? 100000 : 25000;
'''
CHANGES = {
    'vrm_demo/agent/config.py': [
        ('ROOT = Path(__file__).resolve().parents[2]\n', CONFIG_CONSTANTS),
        ('    model_budget: float = 18.0', '    model_budget: float = 60.0'),
    ],
    'vrm_demo/agent/llm.py': [
        ('from .config import model_config', 'from .config import model_config, MODEL_READ_TIMEOUT_SECONDS'),
        ('            with httpx.Client(timeout=min(remaining,8), follow_redirects=False, transport=self.transport) as client:',
         '''            # The turn deadline still caps each phase's available wait.
            # A read timeout is network inactivity, NOT an end-to-end stopwatch.
            phase_timeout = httpx.Timeout(
                connect=min(remaining,8), read=min(remaining,MODEL_READ_TIMEOUT_SECONDS),
                write=min(remaining,8), pool=min(remaining,8),
            )
            with httpx.Client(timeout=phase_timeout, follow_redirects=False, transport=self.transport) as client:'''),
    ],
    'vrm_demo/agent/service.py': [
        ('from .config import Settings\n', CONFIG_IMPORT + '\n'),
        (OLD_STATUS, NEW_STATUS),
    ],
    'vrm_demo/agent/store.py': [
        ('import uuid\n', 'import uuid\nfrom .config import SESSION_LEASE_SECONDS\n'),
        ('(owner, time.time()+120, sid, time.time())', '(owner, time.time()+SESSION_LEASE_SECONDS, sid, time.time())'),
    ],
    'vrm_demo/static/js/agent-client.js': [(JS_OLD_MODE, JS_NEW_MODE)],
    'vrm_demo/static/js/VRMCharacter.js': [
        (JS_OLD_IMPORT, JS_NEW_IMPORT),
        ('const chatTimer = setTimeout(() => chatController.abort(), 25000);',
         'const chatTimer = setTimeout(() => chatController.abort(), agentChatTimeoutMs());'),
    ],
}

class PatchError(Exception):
    """Messages contain fixed source names, never configuration values."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def text_of(raw: bytes) -> str:
    return raw.decode('utf-8-sig').replace('\r\n', '\n')


def encode_like(raw: bytes, text: str) -> bytes:
    newline = '\r\n' if b'\r\n' in raw else '\n'
    return (codecs.BOM_UTF8 if raw.startswith(codecs.BOM_UTF8) else b'') + text.replace('\n', newline).encode('utf-8')


def safe_path(project: Path, relative: str, *, must_exist=True) -> Path:
    parts = Path(relative).parts
    if Path(relative).is_absolute() or '..' in parts:
        raise PatchError('Refusing an unsafe relative path.')
    path = project / relative
    for parent in (path, *path.parents):
        if parent == project:
            break
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise PatchError('Refusing symlink/junction: ' + relative)
    if not path.resolve().is_relative_to(project):
        raise PatchError('Refusing outside-project target: ' + relative)
    if must_exist and not path.is_file():
        raise PatchError('Missing source file: ' + relative)
    return path


def transform(source: str, relative: str) -> str:
    # Entire-file state must be either old or patched; do not silently repair a
    # partially edited timeout patch. Unrelated source, including HTTP rules,
    # remains unchanged.
    pairs = CHANGES[relative]
    matched_new = [source.count(new) == 1 for _, new in pairs]
    if all(matched_new):
        return source
    if any(matched_new):
        raise PatchError('Partial/local timeout changes detected: ' + relative)
    for old, new in pairs:
        if source.count(old) != 1:
            raise PatchError('Source mismatch; nothing applied: ' + relative)
        source = source.replace(old, new, 1)
    if relative.endswith('.py'):
        ast.parse(source, filename=relative)
    return source


def plan(project: Path):
    planned = []
    # Require diagnostics version used by the reported runtime logs.
    service = text_of(safe_path(project, 'vrm_demo/agent/service.py').read_bytes())
    if 'RUNTIME_DIAGNOSTICS_V1_1' not in service:
        raise PatchError('Expected runtime diagnostics 1.1.0; source version differs.')
    for relative in CHANGES:
        path = safe_path(project, relative)
        before = path.read_bytes()
        after = encode_like(before, transform(text_of(before), relative))
        if before != after:
            planned.append((relative, path, before, after))
    return planned


def atomic_write(path: Path, content: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.agent-timeout-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install(project: Path, apply: bool) -> Path | None:
    entries = plan(project)  # Validate ALL files before writing anything.
    if not entries:
        print('[OK] Timeout profile is already installed; no files changed.')
        return None
    for name, _, _, _ in entries:
        print('[PLAN]', name)
    if not apply:
        print('[PREVIEW] No files changed. Stop the backend, then use --apply.')
        return None
    backup_base = safe_path(project, BACKUP_ROOT, must_exist=False)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = backup_base / stamp
    backup.mkdir(parents=True, exist_ok=False)
    manifest = {'version':VERSION, 'project':str(project), 'files':[]}
    for name, _, before, after in entries:
        saved = backup / 'files' / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(before)
        manifest['files'].append({'path':name, 'before':sha(before), 'after':sha(after)})
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    # Detect edits between planning and writing. Backend must be stopped.
    for name, target, before, _ in entries:
        if target.read_bytes() != before:
            raise PatchError('Source changed during installation: ' + name)
    done = []
    try:
        for _, target, before, after in entries:
            atomic_write(target, after)
            done.append((target, before, after))
    except BaseException:
        for target, before, after in reversed(done):
            if target.read_bytes() == after:
                atomic_write(target, before)
        raise
    print('[OK] Installed timeout profile:', VERSION)
    print('[OK] Backup:', backup)
    print('[UNCHANGED] .env, key/URL/model, HTTP allowlist, LangGraph routing, booking tools, database, confirmation tokens.')
    print('[NEXT] Restart the backend. Ctrl+F5 the Agent page. Send a NEW chat query (do not replay a cached partial reply).')
    return backup


def rollback(project: Path, backup: Path, apply: bool) -> None:
    root = safe_path(project, BACKUP_ROOT, must_exist=False)
    backup = backup.absolute()
    if not backup.is_relative_to(root) or backup == root:
        raise PatchError('Rollback directory must be inside ' + BACKUP_ROOT)
    safe_path(project, str(backup.relative_to(project)), must_exist=False)
    manifest_path = safe_path(project, str((backup / 'manifest.json').relative_to(project)))
    meta = json.loads(manifest_path.read_text(encoding='utf-8'))
    if meta.get('version') != VERSION or meta.get('project') != str(project):
        raise PatchError('Backup belongs to another patch/project.')
    files = meta.get('files')
    if not isinstance(files, list) or not 1 <= len(files) <= len(CHANGES):
        raise PatchError('Invalid backup manifest.')
    changes, seen = [], set()
    for entry in files:
        name = entry['path']
        if name not in CHANGES or name in seen:
            raise PatchError('Unexpected/duplicate backup target.')
        seen.add(name)
        target = safe_path(project, name)
        saved = safe_path(project, str((backup / 'files' / name).relative_to(project)))
        original, current = saved.read_bytes(), target.read_bytes()
        if sha(original) != entry['before']:
            raise PatchError('Backup checksum differs: ' + name)
        if sha(current) == entry['before']:
            continue
        if sha(current) != entry['after']:
            raise PatchError('Local changes since patch; refusing rollback: ' + name)
        changes.append((name, target, current, original))
    for name, _, _, _ in changes:
        print('[ROLLBACK PLAN]', name)
    if not apply:
        print('[PREVIEW] No files changed. Add --apply to restore these sources.')
        return
    done=[]
    try:
        for name, target, current, original in changes:
            if target.read_bytes() != current:
                raise PatchError('Source changed during rollback: ' + name)
            atomic_write(target, original)
            done.append((target, current, original))
    except BaseException:
        for target, current, original in reversed(done):
            if target.read_bytes() == original:
                atomic_write(target, current)
        raise
    print('[OK] Source rollback complete; no databases or .env changed.')


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path.cwd())
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--rollback', type=Path)
    args=parser.parse_args()
    project=args.project.resolve()
    try:
        if args.rollback:
            rollback(project, args.rollback, args.apply)
        else:
            install(project, args.apply)
    except PatchError as exc:
        print('[STOP]', str(exc))
        return 1
    except Exception as exc:
        print('[STOP]', type(exc).__name__, '- no raw exception/config data printed. Backups remain available.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
