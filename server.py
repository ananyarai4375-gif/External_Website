import json
import os
import threading
import time
import uuid
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

MAX_ACTIVE_USERS = max(1, int(os.getenv("MAX_ACTIVE_USERS", "50")))
SESSION_TIMEOUT_SECONDS = max(30, int(os.getenv("SESSION_TIMEOUT_SECONDS", "60")))
VM_CAPACITY = max(1, int(os.getenv("VM_CAPACITY", "10")))
MAX_SIMULATED_VMS = max(1, int(os.getenv("MAX_SIMULATED_VMS", "5")))
SCALE_DOWN_AFTER_SECONDS = max(30, int(os.getenv("SCALE_DOWN_AFTER_SECONDS", "120")))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def configured_origins() -> set[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000")
    return {origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()}


class SharedUserStore:
    """Shared active-session and simulated VM state, PostgreSQL-backed when configured."""

    def __init__(self, database_url: str = "") -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, float] = {}
        self._events: list[dict] = []
        self._vm_count = 1
        self._last_scale_at = time.monotonic()
        self._last_scale_event = ""
        self._db = None
        if database_url:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("DATABASE_URL is set but psycopg[binary] is not installed") from exc
            self._db = psycopg.connect(database_url, autocommit=True, row_factory=dict_row)
            self._initialize_database()

    def _initialize_database(self) -> None:
        with self._db.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_sessions (
                    session_id TEXT PRIMARY KEY,
                    last_seen DOUBLE PRECISION NOT NULL
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS demo_state (
                    state_key TEXT PRIMARY KEY,
                    state_value JSONB NOT NULL
                )
            """)
            initial_state = json.dumps({"vm_count": 1, "events": [], "last_event": "", "last_scale_at": 0})
            cursor.execute(
                "INSERT INTO demo_state (state_key, state_value) VALUES ('vm_state', %s::jsonb) "
                "ON CONFLICT (state_key) DO NOTHING",
                (initial_state,),
            )

    def _purge_expired_db(self, cursor, now: float) -> None:
        cursor.execute("DELETE FROM active_sessions WHERE last_seen < %s", (now - SESSION_TIMEOUT_SECONDS,))

    def _lock_capacity_db(self, cursor) -> None:
        cursor.execute("SELECT pg_advisory_xact_lock(2026100701)")

    def _remove_expired_memory(self, now: float) -> None:
        for session_id, last_seen in list(self._sessions.items()):
            if now - last_seen > SESSION_TIMEOUT_SECONDS:
                del self._sessions[session_id]

    def _active_count_locked(self, now: float) -> int:
        if self._db:
            with self._db.cursor() as cursor:
                self._purge_expired_db(cursor, now)
                cursor.execute("SELECT COUNT(*) AS count FROM active_sessions")
                return int(cursor.fetchone()["count"])
        self._remove_expired_memory(now)
        return len(self._sessions)

    def _read_vm_state_db(self, cursor, lock: bool = False) -> dict:
        suffix = " FOR UPDATE" if lock else ""
        cursor.execute(f"SELECT state_value FROM demo_state WHERE state_key = 'vm_state'{suffix}")
        row = cursor.fetchone()
        if row is None:
            return {"vm_count": 1, "events": [], "last_event": "", "last_scale_at": 0}
        return row["state_value"]

    def _auto_scale_locked(self, active_users: int) -> None:
        now = time.time()
        if not self._db:
            new_event = None
            if active_users >= max(1, int(self._vm_count * VM_CAPACITY * 0.8)) and self._vm_count < MAX_SIMULATED_VMS:
                self._vm_count += 1
                self._last_scale_event = f"Auto-scaled up to {self._vm_count} simulated VMs"
                new_event = {"at": now, "message": self._last_scale_event, "type": "scale-up"}
            elif self._vm_count > 1 and active_users <= int((self._vm_count - 1) * VM_CAPACITY * 0.5) and now - self._last_scale_at > SCALE_DOWN_AFTER_SECONDS:
                self._vm_count -= 1
                self._last_scale_event = f"Scaled down to {self._vm_count} simulated VMs"
                new_event = {"at": now, "message": self._last_scale_event, "type": "scale-down"}
            if new_event:
                self._events.append(new_event)
                self._events = self._events[-20:]
                self._last_scale_at = now
            return

        with self._db.transaction():
            with self._db.cursor() as cursor:
                state = self._read_vm_state_db(cursor, lock=True)
                vm_count = int(state.get("vm_count", 1))
                events = state.get("events", [])
                last_event = state.get("last_event", "No scaling events yet")
                last_scale_at = float(state.get("last_scale_at", 0))
                new_event = None
                if active_users >= max(1, int(vm_count * VM_CAPACITY * 0.8)) and vm_count < MAX_SIMULATED_VMS:
                    vm_count += 1
                    last_event = f"Auto-scaled up to {vm_count} simulated VMs"
                    new_event = {"at": now, "message": last_event, "type": "scale-up"}
                elif vm_count > 1 and active_users <= int((vm_count - 1) * VM_CAPACITY * 0.5) and now - last_scale_at > SCALE_DOWN_AFTER_SECONDS:
                    vm_count -= 1
                    last_event = f"Scaled down to {vm_count} simulated VMs"
                    new_event = {"at": now, "message": last_event, "type": "scale-down"}
                if new_event:
                    events = (events + [new_event])[-20:]
                    state = {"vm_count": vm_count, "events": events, "last_event": last_event, "last_scale_at": now}
                    cursor.execute(
                        "UPDATE demo_state SET state_value = %s::jsonb WHERE state_key = 'vm_state'",
                        (json.dumps(state),),
                    )

    def add_session(self, session_id: str) -> int:
        now = time.time()
        with self._lock:
            if self._db:
                with self._db.transaction():
                    with self._db.cursor() as cursor:
                        self._lock_capacity_db(cursor)
                        self._purge_expired_db(cursor, now)
                        cursor.execute(
                            "INSERT INTO active_sessions (session_id, last_seen) VALUES (%s, %s) "
                            "ON CONFLICT (session_id) DO UPDATE SET last_seen = EXCLUDED.last_seen",
                            (session_id, now),
                        )
                        count = self._active_count_locked(now)
                        self._auto_scale_locked(count)
                        return count
            else:
                self._remove_expired_memory(now)
                self._sessions[session_id] = now
            count = self._active_count_locked(now)
            self._auto_scale_locked(count)
            return count

    def register_visit(self, session_id: str) -> tuple[int, bool]:
        now = time.time()
        with self._lock:
            if self._db:
                with self._db.transaction():
                    with self._db.cursor() as cursor:
                        self._lock_capacity_db(cursor)
                        self._purge_expired_db(cursor, now)
                        cursor.execute("SELECT 1 FROM active_sessions WHERE session_id = %s", (session_id,))
                        is_existing = cursor.fetchone() is not None
                        current_count = self._active_count_locked(now)
                        self._auto_scale_locked(current_count)
                        if not is_existing and current_count >= self._capacity_limit_locked():
                            return current_count, True
                        cursor.execute(
                            "INSERT INTO active_sessions (session_id, last_seen) VALUES (%s, %s) "
                            "ON CONFLICT (session_id) DO UPDATE SET last_seen = EXCLUDED.last_seen",
                            (session_id, now),
                        )
                        active_users = self._active_count_locked(now)
                        self._auto_scale_locked(active_users)
                        return active_users, active_users > self._capacity_limit_locked()

            self._remove_expired_memory(now)
            current_count = len(self._sessions)
            self._auto_scale_locked(current_count)
            if session_id not in self._sessions and current_count >= self._capacity_limit_locked():
                return current_count, True
            self._sessions[session_id] = now
            active_users = len(self._sessions)
            self._auto_scale_locked(active_users)
            return active_users, active_users > self._capacity_limit_locked()

    def remove_session(self, session_id: str) -> int:
        now = time.time()
        with self._lock:
            if self._db:
                with self._db.transaction():
                    with self._db.cursor() as cursor:
                        self._lock_capacity_db(cursor)
                        cursor.execute("DELETE FROM active_sessions WHERE session_id = %s", (session_id,))
                        count = self._active_count_locked(now)
                        self._auto_scale_locked(count)
                        return count
            else:
                self._sessions.pop(session_id, None)
            count = self._active_count_locked(now)
            self._auto_scale_locked(count)
            return count

    def count(self) -> int:
        with self._lock:
            return self._active_count_locked(time.time())

    def _capacity_limit_locked(self) -> int:
        if self._db:
            with self._db.transaction():
                with self._db.cursor() as cursor:
                    state = self._read_vm_state_db(cursor)
                    vm_count = int(state.get("vm_count", 1))
        else:
            vm_count = self._vm_count
        return min(MAX_ACTIVE_USERS, vm_count * VM_CAPACITY)

    def capacity_limit(self) -> int:
        with self._lock:
            if self._db:
                with self._db.transaction():
                    active_users = self._active_count_locked(time.time())
                    self._auto_scale_locked(active_users)
                    return self._capacity_limit_locked()
            return self._capacity_limit_locked()

    def booking_allowed(self, session_id: str) -> bool:
        now = time.time()
        with self._lock:
            if self._db:
                with self._db.transaction():
                    with self._db.cursor() as cursor:
                        self._lock_capacity_db(cursor)
                        self._purge_expired_db(cursor, now)
                        cursor.execute("SELECT 1 FROM active_sessions WHERE session_id = %s", (session_id,))
                        registered = cursor.fetchone() is not None
                        active_count = self._active_count_locked(now)
                        self._auto_scale_locked(active_count)
                        return registered and active_count <= self._capacity_limit_locked()
            else:
                self._remove_expired_memory(now)
                registered = session_id in self._sessions
            active_count = self._active_count_locked(now)
            self._auto_scale_locked(active_count)
            return registered and active_count <= self._capacity_limit_locked()

    def dashboard(self) -> dict:
        now = time.time()
        with self._lock:
            if self._db:
                with self._db.transaction():
                    return self._dashboard_locked(now)
            return self._dashboard_locked(now)

    def _dashboard_locked(self, now: float) -> dict:
        with self._lock:
            active_users = self._active_count_locked(now)
            self._auto_scale_locked(active_users)
            if self._db:
                with self._db.cursor() as cursor:
                    state = self._read_vm_state_db(cursor)
                    vm_count = int(state.get("vm_count", 1))
                    events = state.get("events", [])
                    last_event = state.get("last_event", "No scaling events yet")
            else:
                vm_count = self._vm_count
                events = self._events
                last_event = self._last_scale_event or "No scaling events yet"
            cpu = min(96, round((active_users / max(vm_count * VM_CAPACITY, 1)) * 100))
            memory = min(96, round(24 + cpu * 0.62))
            return {
                "activeUsers": active_users,
                "vmCount": vm_count,
                "vms": [
                    {"id": f"VM-{index + 1}", "status": "healthy", "cpu": min(96, cpu + ((index * 7) % 11)), "memory": min(96, memory + ((index * 5) % 9))}
                    for index in range(vm_count)
                ],
                "capacity": {"current": self._capacity_limit_locked(), "perVm": VM_CAPACITY, "maxVms": min(MAX_SIMULATED_VMS, max(1, (MAX_ACTIVE_USERS + VM_CAPACITY - 1) // VM_CAPACITY))},
                "scalingEvents": list(reversed(events[-10:])),
                "selfHealing": "active",
                "lastEvent": last_event,
                "updatedAt": now,
            }


class MovieBookingHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, store=None, **kwargs):
        self.store = store
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self):
        origin = self.headers.get("Origin", "").rstrip("/")
        allowed = configured_origins()
        if origin and ("*" in allowed or origin in allowed):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Session-ID")
            self.send_header("Access-Control-Max-Age", "600")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"status": "healthy"})
            return
        if parsed.path == "/api/health":
            self._send_json({"status": "healthy", "activeUsers": self.store.count()})
            return
        if parsed.path == "/api/admin/dashboard":
            self._send_json(self.store.dashboard())
            return
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/visit":
            self._handle_visit()
            return
        if parsed.path == "/api/leave":
            self._handle_leave()
            return
        if parsed.path == "/api/booking":
            self._handle_booking()
            return
        self._send_error(404, "Not found")

    def _session_id(self) -> str:
        header_session_id = self.headers.get("X-Session-ID", "").strip()
        if header_session_id:
            return header_session_id[:128]
        cookie = self.headers.get("Cookie", "")
        for item in cookie.split(";"):
            name, _, value = item.strip().partition("=")
            if name == "cineverse_session" and value:
                return value[:128]
        return str(uuid.uuid4())

    def _handle_visit(self):
        session_id = self._session_id()
        active_users, is_busy = self.store.register_visit(session_id)
        body = json.dumps({"activeUsers": active_users, "busy": is_busy}).encode()
        self.send_response(HTTPStatus.SERVICE_UNAVAILABLE if is_busy else HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_leave(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length) if content_length else b""
        try:
            body_session_id = json.loads(payload).get("sessionId", "")
        except (json.JSONDecodeError, AttributeError):
            body_session_id = ""
        session_id = self.headers.get("X-Session-ID", "").strip() or body_session_id or self._session_id()
        active_users = self.store.remove_session(session_id)
        self._send_json({"activeUsers": active_users})

    def _handle_booking(self):
        session_id = self._session_id()
        if not self.store.booking_allowed(session_id):
            self._send_json({"error": "Server busy"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
            return
        self._send_json({"message": "Booking accepted"})

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code, message):
        self._send_json({"error": message}, status=code)


def create_server(data_path: str | None = None, host: str | None = None, port: int | None = None):
    directory = str(Path(__file__).resolve().parent)
    store = SharedUserStore(DATABASE_URL)
    bind_host = host or os.getenv("HOST", "0.0.0.0")
    bind_port = port if port is not None else int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((bind_host, bind_port), lambda *args, **kwargs: MovieBookingHandler(*args, directory=directory, store=store, **kwargs))
    server.store = store
    server.thread = threading.Thread(target=server.serve_forever, daemon=True)
    return server


def main():
    server = create_server()
    print(f"CineVerse backend listening on {server.server_address[0]}:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
