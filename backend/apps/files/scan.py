"""Virus scan through ClamAV's clamd daemon (INSTREAM over TCP).

The protocol: `zINSTREAM\\0`, then chunks each prefixed with a 4-byte
big-endian length, then a zero length; clamd answers `stream: OK`,
`stream: <signature> FOUND` or `... ERROR`, NUL-terminated.
"""

import socket
import struct

from django.conf import settings

CHUNK = 64 * 1024


class ScanError(OSError):
    """clamd could not scan the file (unreachable, size limit, ...): retry later."""


def enabled() -> bool:
    return bool(settings.CLAMD_HOST)


def scan(data: bytes) -> str | None:
    """None when clean, otherwise the name of what clamd found."""
    try:
        with socket.create_connection(
            (settings.CLAMD_HOST, settings.CLAMD_PORT), timeout=settings.CLAMD_TIMEOUT
        ) as conn:
            conn.sendall(b"zINSTREAM\0")
            for start in range(0, len(data), CHUNK):
                chunk = data[start : start + CHUNK]
                conn.sendall(struct.pack(">I", len(chunk)) + chunk)
            conn.sendall(struct.pack(">I", 0))
            reply = b""
            while not reply.endswith(b"\0"):
                part = conn.recv(4096)
                if not part:
                    break
                reply += part
    except OSError as exc:
        raise ScanError(f"clamd unreachable: {exc}") from exc
    answer = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
    if answer.endswith("OK"):
        return None
    if answer.endswith("FOUND"):
        return answer.removeprefix("stream:").removesuffix("FOUND").strip()
    raise ScanError(f"clamd could not scan the file: {answer or 'no answer'}")
