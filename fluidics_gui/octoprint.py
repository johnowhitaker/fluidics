"""Small dependency-free OctoPrint client used by the local Flask app."""

from __future__ import annotations

import json
from urllib import error, parse, request


class OctoPrintError(RuntimeError):
    pass


def _validated_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    parsed = parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OctoPrintError("Enter a complete OctoPrint http:// or https:// address")
    return value


def _open(req: request.Request, timeout: int = 15) -> dict:
    try:
        with request.urlopen(req, timeout=timeout) as response:
            payload = response.read().decode("utf-8", "replace")
            return json.loads(payload) if payload else {}
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise OctoPrintError(f"OctoPrint returned HTTP {exc.code}: {detail or exc.reason}") from exc
    except (error.URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise OctoPrintError(f"Could not reach OctoPrint: {reason}") from exc


def printer_status(url: str, api_key: str) -> dict:
    base_url = _validated_url(url)
    if not api_key:
        raise OctoPrintError("Enter an OctoPrint API key")
    req = request.Request(
        f"{base_url}/api/printer",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        method="GET",
    )
    return _open(req)


def upload_gcode(
    url: str,
    api_key: str,
    filename: str,
    gcode: str,
    *,
    select_file: bool = True,
    start_print: bool = False,
) -> dict:
    base_url = _validated_url(url)
    if not api_key:
        raise OctoPrintError("Enter an OctoPrint API key")
    boundary = "----fluidics-studio-boundary"
    body = bytearray()
    fields = {
        "select": "true" if select_file or start_print else "false",
        "print": "true" if start_print else "false",
    }
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(f"{value}\r\n".encode())
    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        (
            f'Content-Disposition: form-data; name="file"; filename="{safe_filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
    )
    body.extend(gcode.encode())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    req = request.Request(
        f"{base_url}/api/files/local",
        data=bytes(body),
        headers={
            "X-Api-Key": api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    return _open(req, timeout=30)
