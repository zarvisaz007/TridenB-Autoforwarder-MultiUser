"""
NetGuard — Network connectivity monitor.

Spawns a Node.js subprocess that pings reliable hosts and toggles Wi-Fi
on macOS when connectivity drops. The subprocess exits automatically when
the parent Python process dies (stdin pipe closes).

Usage:
    from netguard import start_netguard, stop_netguard, is_netguard_running
"""

import os
import shutil
import logging
import subprocess

logger = logging.getLogger("bot.netguard")

_process = None
_MONITOR_SCRIPT = os.path.join(os.path.dirname(__file__), "monitor.js")


def start_netguard():
    """Start the NetGuard network monitor as a background subprocess.
    Returns True if started successfully, False otherwise."""
    global _process

    if _process is not None and _process.poll() is None:
        logger.info("NetGuard already running (pid %d)", _process.pid)
        return True

    node_bin = shutil.which("node")
    if not node_bin:
        logger.warning("NetGuard: Node.js not found — network monitor disabled")
        return False

    if not os.path.isfile(_MONITOR_SCRIPT):
        logger.warning("NetGuard: monitor.js not found at %s", _MONITOR_SCRIPT)
        return False

    try:
        _process = subprocess.Popen(
            [node_bin, _MONITOR_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        logger.info("NetGuard started (pid %d)", _process.pid)
        return True
    except Exception as e:
        logger.error("NetGuard failed to start: %s", e)
        return False


def stop_netguard():
    """Stop the NetGuard subprocess gracefully."""
    global _process
    if _process is None:
        return

    if _process.poll() is None:
        try:
            _process.stdin.close()
        except Exception:
            pass
        try:
            _process.terminate()
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
        except Exception:
            pass
        logger.info("NetGuard stopped")
    _process = None


def is_netguard_running():
    """Check if NetGuard subprocess is alive."""
    return _process is not None and _process.poll() is None


def get_netguard_output(max_lines=20):
    """Read recent output lines from NetGuard (non-blocking)."""
    if _process is None or _process.stdout is None:
        return []
    lines = []
    try:
        import select
        while select.select([_process.stdout], [], [], 0)[0]:
            line = _process.stdout.readline()
            if not line:
                break
            lines.append(line.rstrip())
            if len(lines) >= max_lines:
                break
    except Exception:
        pass
    return lines
