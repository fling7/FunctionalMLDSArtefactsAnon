from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
from typing import Any, Dict, Optional

from .kb import KnowledgeBase
from .openai_client import OpenAIResponsesClient
from .projects import ProjectManager
from .state import SessionStore, normalize_memory_mode
from .server import start_http_server
from .version import BACKEND_VERSION


@dataclass
class AppConfig:
    openai_api_key: str
    openai_base_url: str
    model: str
    server_host: str
    server_port: int
    max_history_turns: int
    memory_mode: str
    max_handoffs: int
    kb_root: str
    kb_chunk_chars: int
    kb_max_snippets: int
    temperature: float
    timeout_seconds: int
    stt_model: str
    stt_language: str
    stt_max_audio_bytes: int


def _project_root() -> Path:
    # backend/app.py -> project root
    return Path(__file__).resolve().parents[1]


def _print_setup_instructions(root: Path) -> None:
    print("\n[Setup] Projekt-Setup")
    print(f"- Lege deine Konfiguration an: {root / 'config.json'}")
    print("  (Vorlage: config.example.json im Projektroot)")
    print("- Beim Start kannst du wählen, ob du eigene Dateien oder das Beispiel nutzt.")
    print("- Wissensbasis: Lege Dateien in kb/<tag>/... ab, z. B. kb/common/intro.txt")
    print("- Agenten/Room-Plan: Nutze examples/agents.example.json und examples/room_plan.example.json")
    print("- API-Check: GET /health auf dem Server")


def _prompt_choice(prompt: str, options: Dict[str, str], default: str) -> str:
    options_line = ", ".join([f"{key}={label}" for key, label in options.items()])
    prompt_line = f"{prompt} ({options_line}) [Default: {default}]: "
    while True:
        raw = input(prompt_line).strip().lower()
        if not raw:
            return default
        if raw in options:
            return raw
        print(f"Ungültige Auswahl: '{raw}'. Bitte erneut versuchen.")


def _prompt_rel_path(root: Path, label: str, default_rel: str) -> str:
    while True:
        raw = input(f"{label} (relativ zum Projekt) [Default: {default_rel}]: ").strip()
        rel = raw or default_rel
        candidate = (root / rel).resolve()
        if root in candidate.parents or candidate == root:
            if candidate.exists():
                return rel
            print(f"Datei nicht gefunden: {rel}")
        else:
            print("Ungültiger Pfad (außerhalb Projekt).")


def _select_setup_paths(root: Path) -> tuple[str, str]:
    print("\n[Setup] Datenquelle wählen")
    options = {"1": "Beispiel-Daten", "2": "Eigene Dateien"}
    choice = _prompt_choice("Bitte wählen", options, default="1")
    default_room = "examples/room_plan.example.json"
    default_agents = "examples/agents.example.json"
    if choice == "1":
        print("[Setup] Beispiel-Daten aktiviert.")
        return default_room, default_agents
    print("[Setup] Eigene Dateien auswählen.")
    room_path = _prompt_rel_path(root, "Pfad zur room_plan.json", default_room)
    agents_path = _prompt_rel_path(root, "Pfad zur agents.json", default_agents)
    return room_path, agents_path


def _env_text(name: str) -> Optional[str]:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _load_openai_key_override() -> Optional[str]:
    direct_key = _env_text("OPENAI_API_KEY")
    key_file = _env_text("OPENAI_API_KEY_FILE")
    if direct_key and key_file:
        raise ValueError(
            "OPENAI_API_KEY und OPENAI_API_KEY_FILE duerfen nicht gleichzeitig gesetzt sein."
        )
    if direct_key:
        return direct_key
    if not key_file:
        return None

    secret_path = Path(key_file)
    try:
        secret = secret_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(
            f"OPENAI_API_KEY_FILE konnte nicht gelesen werden: {secret_path}"
        ) from exc
    if not secret:
        raise ValueError("OPENAI_API_KEY_FILE enthaelt keinen API-Key.")
    return secret


def _parse_server_port(value: Any) -> int:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("SERVER_PORT/server_port muss eine Ganzzahl sein.") from exc
    if not 1 <= port <= 65535:
        raise ValueError("SERVER_PORT/server_port muss zwischen 1 und 65535 liegen.")
    return port


def _prompt_openai_key() -> str:
    print("\n[Setup] OpenAI API Key fehlt in config.json.")
    print("Du kannst ihn jetzt eingeben oder den Prozess mit OPENAI_API_KEY bzw. OPENAI_API_KEY_FILE neu starten.")
    try:
        key = getpass("OpenAI API Key eingeben (Eingabe bleibt unsichtbar): ").strip()
        if key:
            return key
        print("[Setup] Keine Eingabe erkannt. Fallback auf sichtbare Eingabe.")
    except (KeyboardInterrupt, EOFError):
        raise
    except Exception:
        print("[Setup] Unsichtbare Eingabe nicht verfügbar. Fallback auf sichtbare Eingabe.")
    return input("OpenAI API Key eingeben (sichtbar): ").strip()


def load_config() -> AppConfig:
    root = _project_root()
    cfg_path = root / "config.json"
    if not cfg_path.exists():
        _print_setup_instructions(root)
        raise FileNotFoundError(f"config.json nicht gefunden: {cfg_path}")

    raw = json.loads(cfg_path.read_text(encoding="utf-8-sig"))

    def _get(name: str, default: Any = None) -> Any:
        return raw.get(name, default)

    openai_key_override = _load_openai_key_override()
    configured_openai_key = str(_get("openai_api_key", "")).strip()
    server_host = _env_text("SERVER_HOST") or str(_get("server_host", "127.0.0.1")).strip()
    if not server_host:
        raise ValueError("SERVER_HOST/server_host darf nicht leer sein.")
    server_port_override = _env_text("SERVER_PORT")
    server_port = _parse_server_port(
        server_port_override if server_port_override is not None else _get("server_port", 8787)
    )

    cfg = AppConfig(
        openai_api_key=openai_key_override or configured_openai_key,
        openai_base_url=str(_get("openai_base_url", "https://api.openai.com/v1/responses")).strip(),
        model=str(_get("model", "gpt-4.1")).strip(),
        server_host=server_host,
        server_port=server_port,
        max_history_turns=int(_get("max_history_turns", 20)),
        memory_mode=normalize_memory_mode(_get("memory_mode", "shared_history")),
        max_handoffs=int(_get("max_handoffs", 1)),
        kb_root=str(_get("kb_root", "kb")),
        kb_chunk_chars=int(_get("kb_chunk_chars", 900)),
        kb_max_snippets=int(_get("kb_max_snippets", 4)),
        temperature=float(_get("temperature", 0.3)),
        timeout_seconds=int(_get("timeout_seconds", 60)),
        stt_model=str(_get("stt_model", "whisper-1")).strip(),
        stt_language=str(_get("stt_language", "de")).strip(),
        stt_max_audio_bytes=int(_get("stt_max_audio_bytes", 25 * 1024 * 1024)),
    )

    # Environment and file-backed secrets were already resolved. Only a key
    # entered explicitly at an interactive prompt is persisted for backwards
    # compatibility with the local setup flow.
    if not cfg.openai_api_key:
        print("Du kannst ihn jetzt einmalig eingeben (wird in config.json gespeichert).")
        try:
            key = _prompt_openai_key()
        except (KeyboardInterrupt, EOFError):
            print("\nAbgebrochen. Bitte trage openai_api_key in config.json ein.")
            sys.exit(1)

        if not key:
            print("Kein Key eingegeben. Bitte trage openai_api_key in config.json ein.")
            sys.exit(1)

        raw["openai_api_key"] = key
        cfg_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        cfg.openai_api_key = key
        print("[Setup] Key gespeichert in config.json\n")

    return cfg


def run() -> None:
    try:
        cfg = load_config()
    except FileNotFoundError as exc:
        print(f"[Setup] {exc}")
        print("[Setup] Bitte config.json anlegen und erneut starten.\n")
        sys.exit(1)
    except ValueError as exc:
        print(f"[Setup] Ungueltige Konfiguration: {exc}")
        sys.exit(1)
    root = _project_root()
    _print_setup_instructions(root)

    if sys.stdin.isatty():
        try:
            default_room_plan_path, default_agents_path = _select_setup_paths(root)
        except EOFError:
            default_room_plan_path = "examples/room_plan.example.json"
            default_agents_path = "examples/agents.example.json"
            print("[Setup] Keine interaktive Eingabe verfuegbar, nutze Beispiel-Daten.")
    else:
        default_room_plan_path = "examples/room_plan.example.json"
        default_agents_path = "examples/agents.example.json"
        print("[Setup] Kein interaktives Terminal erkannt, nutze Beispiel-Daten.")

    kb = KnowledgeBase(root / cfg.kb_root, chunk_chars=cfg.kb_chunk_chars)
    project_manager = ProjectManager(
        root / "projects",
        template_room_plan=root / "examples" / "room_plan.example.json",
        template_agents=root / "examples" / "agents.example.json",
    )
    store = SessionStore(
        max_history_turns=cfg.max_history_turns,
        max_handoffs=cfg.max_handoffs,
        kb=kb,
        kb_max_snippets=cfg.kb_max_snippets,
        model=cfg.model,
        temperature=cfg.temperature,
        stt_model=cfg.stt_model,
        stt_language=cfg.stt_language,
        stt_max_audio_bytes=cfg.stt_max_audio_bytes,
        openai=OpenAIResponsesClient(
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
            timeout_seconds=cfg.timeout_seconds,
        ),
        project_manager=project_manager,
        default_room_plan_path=default_room_plan_path,
        default_agents_path=default_agents_path,
        default_memory_mode=cfg.memory_mode,
    )

    print("[Backend] KnowledgeBase geladen:", kb.summary())
    print(f"[Backend] Version {BACKEND_VERSION}")
    print(f"[Backend] Starte HTTP Server auf http://{cfg.server_host}:{cfg.server_port}")
    start_http_server(host=cfg.server_host, port=cfg.server_port, store=store)
