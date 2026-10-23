from __future__ import annotations

import json
import time
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from .runtime_trace import log_backend_event, log_backend_events
from .state import SessionStore
from .version import backend_version_payload


MAX_JSON_BODY_BYTES = 16 * 1024 * 1024
MAX_MULTIPART_BODY_BYTES = 64 * 1024 * 1024


def _set_cors_headers(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header(
        "Access-Control-Allow-Headers",
        "Content-Type, Accept, X-Requested-With, X-Unity-Version",
    )
    handler.send_header("Access-Control-Allow-Private-Network", "true")


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    _set_cors_headers(handler)
    handler.end_headers()
    handler.wfile.write(data)


def _content_length(
    handler: BaseHTTPRequestHandler,
    *,
    body_kind: str,
    maximum_bytes: int,
) -> int:
    raw_length = handler.headers.get("Content-Length", "0")
    try:
        length = int(raw_length)
    except (TypeError, ValueError) as exc:
        raise ValueError("Content-Length ist ungültig.") from exc
    if length < 0:
        raise ValueError("Content-Length darf nicht negativ sein.")
    if length > maximum_bytes:
        raise ValueError(
            f"{body_kind}-Body ist zu groß "
            f"(maximal {maximum_bytes} Bytes)."
        )
    return length


def _read_json(handler: BaseHTTPRequestHandler) -> Dict[str, Any]:
    length = _content_length(
        handler,
        body_kind="JSON",
        maximum_bytes=MAX_JSON_BODY_BYTES,
    )
    if length <= 0:
        return {}
    raw = handler.rfile.read(length).decode("utf-8", errors="replace")
    if not raw.strip():
        return {}
    return json.loads(raw)


def _read_multipart(handler: BaseHTTPRequestHandler) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    content_type = handler.headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("Content-Type muss multipart/form-data sein.")

    length = _content_length(
        handler,
        body_kind="Multipart",
        maximum_bytes=MAX_MULTIPART_BODY_BYTES,
    )
    if length <= 0:
        raise ValueError("Multipart-Body fehlt.")

    raw = handler.rfile.read(length)
    msg = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw
    )
    if not msg.is_multipart():
        raise ValueError("Multipart-Body konnte nicht gelesen werden.")

    fields: Dict[str, Any] = {}
    files: Dict[str, Dict[str, Any]] = {}
    for part in msg.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        data = part.get_payload(decode=True) or b""
        filename = part.get_filename()
        if filename is None:
            fields[name] = data.decode(part.get_content_charset("utf-8"), errors="replace")
        else:
            files[name] = {
                "filename": filename,
                "content_type": part.get_content_type(),
                "content": data,
            }
    return fields, files


def _binary_response(handler: BaseHTTPRequestHandler, status: int, payload: bytes, content_type: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(payload)))
    _set_cors_headers(handler)
    handler.end_headers()
    handler.wfile.write(payload)


def start_http_server(host: str, port: int, store: SessionStore) -> None:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: N802
            # Slightly quieter default logging
            print("[HTTP]", format % args, flush=True)

        def _log_action(self, message: str) -> None:
            print(f"[ProjectAPI] {message}", flush=True)

        def _log_request(self) -> None:
            print(f"[HTTP] -> {self.command} {self.path}", flush=True)

        def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
            print(f"[HTTP] <- {self.command} {self.path} {status}", flush=True)
            _json_response(self, status, payload)

        def _send_binary(self, status: int, payload: bytes, content_type: str) -> None:
            print(f"[HTTP] <- {self.command} {self.path} {status}", flush=True)
            _binary_response(self, status, payload, content_type)

        def do_OPTIONS(self) -> None:  # noqa: N802
            self._log_request()
            self.send_response(204)
            _set_cors_headers(self)
            self.end_headers()
            print(f"[HTTP] <- {self.command} {self.path} 204", flush=True)

        def do_GET(self) -> None:  # noqa: N802
            self._log_request()
            path = urlparse(self.path).path
            try:
                if path == "/":
                    return self._send_json(
                        200,
                        {
                            "message": "Backend läuft.",
                            "endpoints": {
                                "GET /health": "Status-Check",
                                "GET /version": "Backend-Version",
                                "POST /setup": "Session/Agenten Setup",
                                "POST /chat": "Chat mit Agent",
                                "GET /projects": "Projekte auflisten",
                                "POST /projects/create": "Projekt erstellen",
                                "POST /projects/arrow/analyze": "RDLI analysieren",
                                "POST /projects/arrow/chat": "RDLI-Chat fortsetzen",
                                "POST /projects/arrow/commit": "Projekt aus RDLI erstellen",
                                "POST /projects/arrow/placement": "Agentenpositionen im Wizard aktualisieren",
                                "POST /projects/arrow/authoring/inspect": "Aktuellen Placement-Authoring-Stand laden",
                                "POST /projects/arrow/authoring/preview": "Strukturierte Placement-Änderung prüfen",
                                "POST /projects/arrow/authoring/apply": "Placement anwenden, regenerieren und validieren",
                                "POST /projects/arrow/authoring/accept": "Validierte Placement-Änderung akzeptieren",
                                "POST /projects/arrow/authoring/discard": "Offene Placement-Änderung verwerfen",
                                "POST /projects/arrow/authoring/undo": "Letzte akzeptierte Placement-Änderung rückgängig machen",
                                "GET /projects/{id}": "Projekt-Details laden",
                                "GET /projects/{id}/roomcontract-v2": "Native RoomContract-V2-Instanz laden",
                                "POST /projects/{id}/metadata": "Projekt-Metadaten speichern",
                                "POST /projects/{id}/agents": "Agenten speichern",
                                "POST /projects/{id}/room-plan": "Room-Plan speichern",
                                "GET /projects/{id}/knowledge": "Wissensliste",
                                "POST /projects/{id}/knowledge": "Wissen erstellen/aktualisieren/löschen",
                                "POST /projects/{id}/knowledge/read": "Wissen laden",
                                "POST /stt": "Speech-to-Text transkribieren",
                                "POST /tts": "Text-to-Speech erzeugen",
                            },
                            "examples": {
                                "room_plan_path": "examples/room_plan.example.json",
                                "agents_path": "examples/agents.example.json",
                            },
                        },
                    )
                if path in {"/health", "/version"}:
                    return self._send_json(200, backend_version_payload())
                if path == "/projects":
                    self._log_action("Liste Projekte abrufen")
                    projects = store.project_manager.list_projects()
                    return self._send_json(200, {"projects": projects})
                parts = [p for p in path.split("/") if p]
                if len(parts) >= 2 and parts[0] == "projects":
                    project_id = parts[1]
                    if len(parts) == 2:
                        self._log_action(f"Projekt laden: {project_id}")
                        details = store.project_manager.get_project_details(project_id)
                        return self._send_json(200, details)
                    if len(parts) == 3 and parts[2] == "roomcontract-v2":
                        self._log_action(f"RoomContract V2 laden: {project_id}")
                        return self._send_binary(
                            200,
                            store.roomcontract_v2_bytes(project_id),
                            "application/json; charset=utf-8",
                        )
                    if len(parts) == 3 and parts[2] == "knowledge":
                        self._log_action(f"Wissenliste laden: {project_id}")
                        knowledge = store.project_manager.list_knowledge(project_id)
                        return self._send_json(200, {"knowledge": knowledge})
                return self._send_json(404, {"error": "Not found", "path": path})
            except ValueError as exc:
                self._log_action(f"Fehler GET {path}: {exc}")
                return self._send_json(400, {"error": str(exc), "code": getattr(exc, "code", "E_SCHEMA")})
            except Exception as exc:
                self._log_action(f"Fehler GET {path}: {exc}")
                return self._send_json(500, {"error": "Server error", "details": str(exc), "code": getattr(exc, "code", "E_INTERNAL")})

        def do_POST(self) -> None:  # noqa: N802
            self._log_request()
            path = urlparse(self.path).path
            if path == "/stt":
                try:
                    fields, files = _read_multipart(self)
                    audio_info = files.get("audio") or files.get("file") or {}
                    self._log_action(
                        "STT anfordern: "
                        f"filename={audio_info.get('filename')}, bytes={len(audio_info.get('content') or b'')}"
                    )
                    out = store.stt(fields, files)
                    return self._send_json(200, out)
                except ValueError as exc:
                    self._log_action(f"Fehler POST {path}: {exc}")
                    return self._send_json(400, {"error": str(exc), "code": getattr(exc, "code", "E_SCHEMA")})
                except Exception as exc:
                    self._log_action(f"Fehler POST {path}: {exc}")
                    return self._send_json(500, {"error": "Server error", "details": str(exc), "code": getattr(exc, "code", "E_INTERNAL")})

            try:
                payload = _read_json(self)
            except json.JSONDecodeError as e:
                return self._send_json(400, {"error": "Invalid JSON", "details": str(e)})
            except ValueError as e:
                self._log_action(f"Fehler POST {path}: {e}")
                return self._send_json(400, {"error": str(e), "code": getattr(e, "code", "E_SCHEMA")})

            try:
                if path == "/setup":
                    started = time.perf_counter()
                    project_id = str(payload.get("project_id") or "").strip() or None
                    requested_session_id = str(payload.get("session_id") or "").strip()
                    previous_session = store.sessions.get(requested_session_id) if requested_session_id else None
                    out = store.setup_from_request(payload)
                    session_id = str(out.get("session_id") or "").strip()
                    preflight = {}
                    try:
                        preflight = store.preflight_runtime_action(session_id, "setup")
                        log_backend_event(
                            project_manager=store.project_manager,
                            project_id=project_id,
                            action_kind="setup",
                            event_type="backend_setup_completed",
                            session_id=session_id or None,
                            agent_id=None,
                            input_summary={
                                "project_id": project_id,
                                "memory_mode": payload.get("memory_mode"),
                                "has_inline_room_plan": "room_plan" in payload,
                                "has_inline_agents": "agents" in payload or "agent_specs" in payload,
                            },
                            output_summary={
                                "memory_mode": out.get("memory_mode"),
                                "agent_count": len(out.get("agents") or []),
                            },
                            duration_ms=round((time.perf_counter() - started) * 1000, 3),
                            metadata={"agent_count": len(out.get("agents") or [])},
                            expected_contract_fingerprint=preflight.get("contract_fingerprint") or None,
                            expected_action=preflight.get("action"),
                            publication_protocol=store.guard_config.publication_protocol,
                            expected_publication_generation=getattr(store.sessions.get(session_id), "publication_generation", None),
                            commit_variant=store.guard_config.commit_variant,
                            pinned_contract=getattr(store.sessions.get(session_id), "pinned_contract", None),
                            skip_declared_action_check=store.guard_config.routing_mode == "reach_only",
                        )
                    except Exception:
                        # A V2 setup is only committed if its success event and
                        # validation evidence were durably appended.  Preserve the
                        # legacy path's existing best-effort logging behavior.
                        created_session = store.sessions.get(session_id)
                        if (
                            preflight.get("kind") == "v2"
                            or getattr(created_session, "roomcontract_contract_kind", "") == "v2"
                        ):
                            if previous_session is not None:
                                store.sessions[session_id] = previous_session
                            else:
                                store.sessions.pop(session_id, None)
                        raise
                    return self._send_json(200, out)
                if path == "/switch_agent":
                    return self._send_json(200, store.switch_agent(payload))
                if path == "/chat":
                    with store.session_turn_scope(str(payload.get("session_id") or "")):
                        started = time.perf_counter()
                        session_id = str(payload.get("session_id") or "").strip()
                        session_before_chat = store.sessions.get(session_id)
                        is_v2 = (
                            getattr(
                                session_before_chat,
                                "roomcontract_contract_kind",
                                "",
                            )
                            == "v2"
                        )
                        session_snapshot = store.snapshot_session_mutation(session_id) if is_v2 else None
                        try:
                            out = store.chat(
                                payload,
                                include_runtime_actions=is_v2,
                            )
                            runtime_actions = (
                                out.pop("_roomcontract_runtime_actions", {})
                                if isinstance(out, dict)
                                else {}
                            )
                            chat_action = (
                                runtime_actions.get("chat")
                                if isinstance(runtime_actions, dict)
                                else None
                            )
                            handoff_action = (
                                runtime_actions.get("handoff")
                                if isinstance(runtime_actions, dict)
                                else None
                            )
                            contract_fingerprint = (
                                runtime_actions.get("contract_fingerprint")
                                if isinstance(runtime_actions, dict)
                                else None
                            )
                            if is_v2 and not isinstance(chat_action, dict):
                                raise RuntimeError(
                                    "V2 chat did not return its preselected runtime "
                                    "action."
                                )
                            session_id = str(out.get("session_id") or session_id).strip()
                            session = store.sessions.get(session_id)
                            project_id = session.project_id if session else None
                            ignored_proposals = out.pop("_guard_ignored_proposals", [])
                            events = out.get("events") or []
                            handoff = out.get("handoff")
                            chat_entry = {
                                "action_kind": "chat",
                                "event_type": "backend_chat_completed",
                                "session_id": session_id or None,
                                "agent_id": str(out.get("active_agent_id") or payload.get("active_agent_id") or "").strip() or None,
                                "input_summary": {
                                    "active_agent_id": payload.get("active_agent_id"),
                                    "user_text_length": len(str(payload.get("user_text") or "")),
                                },
                                "output_summary": {
                                    "active_agent_id": out.get("active_agent_id"),
                                    "event_count": len(events),
                                    "handoff": bool(handoff),
                                },
                                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                                "status": "success",
                                "metadata": {"event_count": len(events), "handoff": bool(handoff), "ignored_handoff_proposals": ignored_proposals},
                                "expected_action": chat_action,
                            }
                            handoff_entry = None
                            if handoff:
                                if is_v2 and not isinstance(handoff_action, dict):
                                    raise RuntimeError(
                                        "V2 handoff did not return its preselected "
                                        "runtime action."
                                    )
                                handoff_entry = {
                                    "action_kind": "handoff",
                                    "event_type": "backend_handoff_completed",
                                    "session_id": session_id or None,
                                    "agent_id": str(handoff.get("to") or out.get("active_agent_id") or "").strip() or None,
                                    "input_summary": {
                                        "from": handoff.get("from"),
                                        "to": handoff.get("to"),
                                        "reason_present": bool(handoff.get("reason")),
                                    },
                                    "output_summary": {
                                        "active_agent_id": out.get("active_agent_id"),
                                        "event_count": len(events),
                                    },
                                    "duration_ms": None,
                                    "status": "success",
                                    "metadata": {"from": handoff.get("from"), "to": handoff.get("to")},
                                    "expected_action": handoff_action,
                                }
                            if is_v2:
                                entries = [chat_entry] + ([handoff_entry] if handoff_entry else [])
                                logged = log_backend_events(
                                    project_manager=store.project_manager,
                                    project_id=project_id,
                                    entries=entries,
                                    expected_contract_fingerprint=contract_fingerprint or None,
                                    publication_protocol=store.guard_config.publication_protocol,
                                    expected_publication_generation=getattr(session, "publication_generation", None),
                                    commit_variant=store.guard_config.commit_variant,
                                    pinned_contract=getattr(session, "pinned_contract", None),
                                    skip_declared_action_check=store.guard_config.routing_mode == "reach_only",
                                )
                                if len(logged) != len(entries):
                                    raise RuntimeError("V2 runtime evidence transaction was not fully committed.")
                            else:
                                log_backend_event(
                                    project_manager=store.project_manager,
                                    project_id=project_id,
                                    **{key: value for key, value in chat_entry.items() if key != "expected_action"},
                                )
                                if handoff_entry:
                                    log_backend_event(
                                        project_manager=store.project_manager,
                                        project_id=project_id,
                                        **{key: value for key, value in handoff_entry.items() if key != "expected_action"},
                                    )
                        except Exception:
                            if is_v2 and session_snapshot is not None:
                                store.restore_session_mutation(session_id, session_snapshot)
                            raise
                        store.commit_chat_active(session_id, out)
                        return self._send_json(200, out)
                if path == "/tts":
                    text_preview = str(payload.get("text") or "")
                    text_len = len(text_preview.strip())
                    voice = str(payload.get("voice") or "").strip() or "alloy"
                    tts_model = str(payload.get("tts_model") or "").strip() or "gpt-4o-mini-tts"
                    response_format = str(payload.get("response_format") or "mp3").strip() or "mp3"
                    self._log_action(
                        "TTS anfordern: "
                        f"text_len={text_len}, voice={voice}, model={tts_model}, format={response_format}"
                    )
                    audio, content_type = store.tts(payload)
                    self._log_action(
                        "TTS bereitgestellt: "
                        f"bytes={len(audio)}, content_type={content_type}"
                    )
                    return self._send_binary(200, audio, content_type)
                if path == "/projects/create":
                    display_name = str(payload.get("display_name") or "").strip()
                    if not display_name:
                        raise ValueError("display_name fehlt.")
                    project_id = str(payload.get("project_id") or "").strip() or None
                    description = str(payload.get("description") or "").strip()
                    self._log_action(f"Projekt erstellen: name='{display_name}', id='{project_id or ''}'")
                    out = store.project_manager.create_project(
                        display_name=display_name,
                        project_id=project_id,
                        description=description,
                    )
                    return self._send_json(200, {"project": out})
                if path == "/projects/arrow/analyze":
                    self._log_action("RDLI analysieren")
                    out = store.analyze_arrow(payload)
                    return self._send_json(200, out)
                if path == "/projects/arrow/chat":
                    self._log_action("RDLI-Chat fortsetzen")
                    out = store.arrow_chat(payload)
                    return self._send_json(200, out)
                if path == "/projects/arrow/commit":
                    self._log_action("Projekt aus RDLI erstellen")
                    out = store.commit_arrow_project(payload)
                    return self._send_json(200, out)
                if path == "/projects/arrow/placement":
                    self._log_action("RDLI-Agentenplatzierung aktualisieren")
                    out = store.update_arrow_placement(payload)
                    return self._send_json(200, out)
                if path == "/projects/arrow/authoring/inspect":
                    self._log_action("Placement-Authoring-Stand laden")
                    out = store.inspect_arrow_authoring(payload)
                    return self._send_json(200, out)
                if path == "/projects/arrow/authoring/preview":
                    self._log_action("Placement-Änderung prüfen")
                    out = store.preview_arrow_authoring(payload)
                    return self._send_json(200, out)
                if path == "/projects/arrow/authoring/apply":
                    self._log_action("Placement-Änderung anwenden und validieren")
                    out = store.apply_arrow_authoring(payload)
                    return self._send_json(200, out)
                if path == "/projects/arrow/authoring/accept":
                    self._log_action("Placement-Änderung akzeptieren")
                    out = store.accept_arrow_authoring(payload)
                    return self._send_json(200, out)
                if path == "/projects/arrow/authoring/discard":
                    self._log_action("Placement-Änderung verwerfen")
                    out = store.discard_arrow_authoring(payload)
                    return self._send_json(200, out)
                if path == "/projects/arrow/authoring/undo":
                    self._log_action("Placement-Änderung rückgängig machen")
                    out = store.undo_arrow_authoring(payload)
                    return self._send_json(200, out)
                parts = [p for p in path.split("/") if p]
                if len(parts) >= 2 and parts[0] == "projects":
                    project_id = parts[1]
                    if len(parts) == 3 and parts[2] == "metadata":
                        display_name = payload.get("display_name")
                        description = payload.get("description")
                        self._log_action(f"Metadaten speichern: {project_id}")
                        out = store.project_manager.update_metadata(project_id, display_name=display_name, description=description)
                        return self._send_json(200, {"project": out})
                    if len(parts) == 3 and parts[2] == "agents":
                        agents = payload.get("agents") or []
                        if not isinstance(agents, list):
                            raise ValueError("agents muss eine Liste sein.")
                        self._log_action(f"Agenten speichern: {project_id} ({len(agents)})")
                        store.project_manager.save_agents(project_id, agents)
                        return self._send_json(200, {"status": "ok"})
                    if len(parts) == 3 and parts[2] == "room-plan":
                        room_plan = payload.get("room_plan") or {}
                        if not isinstance(room_plan, dict):
                            raise ValueError("room_plan muss ein Objekt sein.")
                        self._log_action(f"Room-Plan speichern: {project_id}")
                        store.project_manager.save_room_plan(project_id, room_plan)
                        return self._send_json(200, {"status": "ok"})
                    if len(parts) == 3 and parts[2] == "knowledge":
                        action = str(payload.get("action") or "upsert").strip().lower()
                        tag = str(payload.get("tag") or "").strip()
                        name = str(payload.get("name") or "").strip()
                        if action == "delete":
                            self._log_action(f"Wissen löschen: {project_id} {tag}/{name}")
                            store.project_manager.delete_knowledge(project_id, tag=tag, name=name)
                            store.refresh_project_kb(project_id)
                            return self._send_json(200, {"status": "ok"})
                        text = str(payload.get("text") or "")
                        overwrite = bool(payload.get("overwrite", True))
                        self._log_action(f"Wissen speichern: {project_id} {tag}/{name}")
                        entry = store.project_manager.upsert_knowledge(
                            project_id=project_id,
                            tag=tag,
                            name=name,
                            text=text,
                            overwrite=overwrite,
                        )
                        store.refresh_project_kb(project_id)
                        return self._send_json(200, {"entry": entry})
                    if len(parts) == 4 and parts[2] == "knowledge" and parts[3] == "read":
                        tag = str(payload.get("tag") or "").strip()
                        name = str(payload.get("name") or "").strip()
                        self._log_action(f"Wissen laden: {project_id} {tag}/{name}")
                        entry = store.project_manager.read_knowledge(project_id, tag=tag, name=name)
                        return self._send_json(200, entry)
                return self._send_json(404, {"error": "Not found", "path": path})
            except ValueError as e:
                self._log_action(f"Fehler POST {path}: {e}")
                return self._send_json(400, {"error": str(e), "code": getattr(e, "code", "E_SCHEMA")})
            except Exception as e:
                self._log_action(f"Fehler POST {path}: {e}")
                return self._send_json(500, {"error": "Server error", "details": str(e), "code": getattr(e, "code", "E_INTERNAL")})

    httpd = ThreadingHTTPServer((host, port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[Backend] Beende Server…")
    finally:
        httpd.server_close()
