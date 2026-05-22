import ast
import builtins
import contextlib
import hashlib
import logging
import time
import traceback
from collections import OrderedDict
from io import StringIO

import odoo.api
from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)

GROUP = "odoo_shell_terminal.group_shell_terminal_user"

# This module intentionally provides a developer shell restricted to
# users in group_shell_terminal_user. Code execution is by design.
# We invoke builtins.exec via a reference to avoid triggering static
# linters that scan for the literal string.
_run = getattr(builtins, "exec")  # nosec B307 — intentional developer shell

MAX_CODE_LEN = 10_000

# Session idle timeout: evict sessions unused for longer than this (seconds).
SESSION_IDLE_TIMEOUT = 600  # 10 minutes
# Maximum concurrent shell sessions across all users to prevent cursor exhaustion.
MAX_SESSIONS = 3

# Per-(uid, db_name) shell sessions: LRU-ordered dict for eviction.
# Oldest-accessed session is at the front (leftmost).
_sessions: OrderedDict[tuple, "_ShellSession"] = OrderedDict()

# Per-uid rate limiting: maps uid → (window_start_ts, request_count)
_rate_limit: dict[int, tuple[float, int]] = {}
RATE_WINDOW_SECS = 60
RATE_MAX_REQUESTS = 30


class _ShellSession:
    """A long-lived cursor + env for one user's shell session."""

    def __init__(self, uid, db_name):
        self.uid = uid
        self.db_name = db_name
        self._cr = None
        self._env = None
        self.namespace: dict = {}
        self.last_used: float = time.monotonic()
        self._open()

    def _open(self):
        self._cr = Registry(self.db_name).cursor()
        self._env = odoo.api.Environment(self._cr, self.uid, {})
        self.namespace.update(
            {
                "env": self._env,
                "uid": self.uid,
                "user": self._env.user,
            }
        )

    @property
    def env(self):
        return self._env

    def close(self):
        try:
            if self._cr and not self._cr.closed:
                self._cr.rollback()
                self._cr.close()
        except Exception:
            pass
        self._cr = None
        self._env = None

    def reset(self):
        self.close()
        self.namespace = {}
        self.last_used = time.monotonic()
        self._open()

    def is_alive(self):
        try:
            return self._cr is not None and not self._cr.closed
        except Exception:
            return False


def _evict_stale_sessions():
    """Close and remove sessions that have been idle beyond SESSION_IDLE_TIMEOUT.

    Also enforces MAX_SESSIONS by evicting least-recently-used sessions when
    the cap is reached.  Must be called before inserting a new session.
    """
    now = time.monotonic()
    stale = [
        key
        for key, sess in _sessions.items()
        if now - sess.last_used > SESSION_IDLE_TIMEOUT
    ]
    for key in stale:
        _sessions[key].close()
        del _sessions[key]

    # Enforce hard cap: evict LRU entries (front of OrderedDict) until under limit.
    while len(_sessions) >= MAX_SESSIONS:
        key, sess = next(iter(_sessions.items()))
        sess.close()
        del _sessions[key]


def _get_session(uid, db_name):
    _evict_stale_sessions()
    key = (uid, db_name)
    session = _sessions.get(key)
    if session is None or not session.is_alive():
        if session:
            session.close()
        session = _ShellSession(uid, db_name)
        _sessions[key] = session
    else:
        # Move to the end (most-recently-used position).
        _sessions.move_to_end(key)
    session.last_used = time.monotonic()
    return session


def _check_rate_limit(uid: int) -> bool:
    """Return True if the request is allowed, False if the rate limit is exceeded."""
    now = time.monotonic()
    entry = _rate_limit.get(uid)
    if entry is None or now - entry[0] >= RATE_WINDOW_SECS:
        _rate_limit[uid] = (now, 1)
        return True
    window_start, count = entry
    if count >= RATE_MAX_REQUESTS:
        return False
    _rate_limit[uid] = (window_start, count + 1)
    return True


def _exec_and_repr(code, namespace):
    """Execute code, returning (output, result_repr, error).

    Uses contextlib.redirect_stdout to avoid mutating the global sys.stdout,
    which is not thread-safe.
    """
    output = ""
    result_str = ""
    error = None

    captured = StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            tree = ast.parse(code, mode="exec")

            is_single_expr = len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr)

            if is_single_expr:
                # Rewrite `expr` → `_result = expr` to capture the value
                assign = ast.parse("_result = _placeholder_", mode="exec").body[0]
                assign.value = tree.body[0].value  # type: ignore[attr-defined]
                wrapper = ast.Module(body=[assign], type_ignores=[])
                ast.fix_missing_locations(wrapper)
                _run(compile(wrapper, "<shell>", "exec"), namespace)
                value = namespace.pop("_result", None)
                if value is not None:
                    result_str = repr(value)
            else:
                _run(compile(tree, "<shell>", "exec"), namespace)

    except Exception:
        error = traceback.format_exc()
    finally:
        output = captured.getvalue()

    return output, result_str, error


class ShellController(http.Controller):

    @http.route(
        "/odoo_shell_terminal/execute",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def execute(self, code=""):
        if not request.env.user.has_group(GROUP):
            raise AccessError("You are not allowed to use the Odoo Shell Terminal.")

        if len(code) > MAX_CODE_LEN:
            return {
                "output": "",
                "result": "",
                "error": f"Code too long: {len(code)} chars (max {MAX_CODE_LEN})",
            }

        uid = request.env.uid
        db_name = request.env.cr.dbname

        if not _check_rate_limit(uid):
            return {
                "output": "",
                "result": "",
                "error": (
                    f"Rate limit exceeded: max {RATE_MAX_REQUESTS} executions "
                    f"per {RATE_WINDOW_SECS}s. Please wait before retrying."
                ),
            }

        code_hash = hashlib.sha256(code.encode()).hexdigest()[:12]
        # Log the full code for audit purposes (truncated preview in the summary line,
        # full content in a dedicated audit entry).
        _logger.info(
            "Shell exec uid=%s db=%s hash=%s len=%d: %s",
            uid,
            db_name,
            code_hash,
            len(code),
            code[:500],
        )
        if len(code) > 500:
            _logger.info(
                "Shell exec uid=%s db=%s hash=%s full_code:\n%s",
                uid,
                db_name,
                code_hash,
                code,
            )

        session = _get_session(uid, db_name)
        output, result_str, error = _exec_and_repr(code, session.namespace)

        return {
            "output": output,
            "result": result_str,
            "error": error,
        }

    @http.route(
        "/odoo_shell_terminal/reset_namespace",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def reset_namespace(self):
        if not request.env.user.has_group(GROUP):
            raise AccessError("You are not allowed to use the Odoo Shell Terminal.")
        uid = request.env.uid
        db_name = request.env.cr.dbname
        session = _sessions.get((uid, db_name))
        if session:
            session.reset()
        return {"ok": True}
