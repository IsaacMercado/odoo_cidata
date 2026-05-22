import collections
import logging
import queue
import threading

from werkzeug.wrappers import Response

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.tools import config

GROUP = "odoo_shell_terminal.group_shell_terminal_user"
TAIL_LINES = 200
MAX_SLEEP = 0.1
# Max lines kept in the ring buffer (shared across all browser tabs)
RING_SIZE = 2000

# ── Global state (module-level singleton) ────────────────────────────────────

_ring_buffer = collections.deque(maxlen=RING_SIZE)  # recent log lines
_ring_lock = threading.Lock()
_subscriber_queues: list[queue.SimpleQueue] = []  # one per open SSE connection
_subscriber_lock = threading.Lock()
_handler_installed = False
_handler_lock = threading.Lock()


class _ShellLogHandler(logging.Handler):
    """Captures every log record and fans it out to all open SSE subscribers."""

    def emit(self, record: logging.LogRecord):
        try:
            line = self.format(record)
        except Exception:
            return
        with _ring_lock:
            _ring_buffer.append(line)
        with _subscriber_lock:
            dead = []
            for q in _subscriber_queues:
                try:
                    q.put_nowait(line)
                except Exception:
                    dead.append(q)
            for q in dead:
                _subscriber_queues.remove(q)


def _ensure_handler_installed():
    global _handler_installed
    with _handler_lock:
        if _handler_installed:
            return
        handler = _ShellLogHandler()
        # Use the same formatter Odoo uses so the output looks identical
        fmt = logging.Formatter(
            "%(asctime)s %(process)d %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S,%f"[:-3],
        )
        handler.setFormatter(fmt)
        logging.getLogger().addHandler(handler)
        _handler_installed = True


# ── Controller ───────────────────────────────────────────────────────────────


class LogStreamController(http.Controller):

    @http.route(
        "/odoo_shell_terminal/clear_log_buffer",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def clear_log_buffer(self):
        if not request.env.user.has_group(GROUP):
            raise AccessError("You are not allowed to use the Odoo Shell Terminal.")
        with _ring_lock:
            _ring_buffer.clear()
        return {"ok": True}

    @http.route(
        "/odoo_shell_terminal/log_stream",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def log_stream(self):
        if not request.env.user.has_group(GROUP):
            raise AccessError("You are not allowed to use the Odoo Shell Terminal.")

        _ensure_handler_installed()

        log_file = config.get("logfile")

        # Snapshot the ring buffer BEFORE subscribing so we don't miss lines
        # that arrive between snapshot and subscribe.
        with _ring_lock:
            backlog = list(_ring_buffer)

        sub_queue: queue.SimpleQueue = queue.SimpleQueue()
        with _subscriber_lock:
            _subscriber_queues.append(sub_queue)

        def generate():
            try:
                # 1. Send recent history from the ring buffer
                for line in backlog:
                    yield f"data: {line}\n\n".encode()

                # 2. If a log file exists, fill any gap between ring buffer
                #    and current end of file that might not be captured yet.
                #    (Usually unnecessary when the handler is already installed,
                #    but useful on first connect before the handler saw much.)
                if log_file:
                    try:
                        with open(log_file, "r", errors="replace") as f:
                            all_lines = f.readlines()
                        tail = (
                            all_lines[-TAIL_LINES:]
                            if len(all_lines) > TAIL_LINES
                            else all_lines
                        )
                        for line in tail:
                            stripped = line.rstrip()
                            if stripped not in backlog:  # rough dedup
                                yield f"data: {stripped}\n\n".encode()
                    except Exception:
                        pass

                # 3. Stream live lines from the subscriber queue
                while True:
                    try:
                        line = sub_queue.get(timeout=MAX_SLEEP)
                        yield f"data: {line}\n\n".encode()
                    except queue.Empty:
                        yield b": keepalive\n\n"
            except GeneratorExit:
                pass
            finally:
                with _subscriber_lock:
                    try:
                        _subscriber_queues.remove(sub_queue)
                    except ValueError:
                        pass

        return Response(
            generate(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
            direct_passthrough=True,
        )
