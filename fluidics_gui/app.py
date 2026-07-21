"""Flask entry point for Fluidics Studio."""

from __future__ import annotations

from io import BytesIO
import re
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file

from .octoprint import OctoPrintError, printer_status, upload_gcode
from .slicer import DesignError, generate_gcode, preview_payload


def _job_name(payload: dict[str, Any]) -> str:
    raw_name = str(payload.get("name") or payload.get("design", {}).get("name") or "fluidics-slide")
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw_name).strip("-.")
    return (cleaned or "fluidics-slide")[:80]


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=4 * 1024 * 1024)
    if test_config:
        app.config.update(test_config)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify(ok=True, app="Fluidics Studio")

    @app.post("/api/slice")
    def slice_preview():
        payload = request.get_json(silent=True) or {}
        result = preview_payload(payload.get("design", {}), payload.get("settings"))
        return jsonify(result)

    @app.post("/api/gcode")
    def download_gcode():
        payload = request.get_json(silent=True) or {}
        name = _job_name(payload)
        gcode, _, _ = generate_gcode(payload.get("design", {}), payload.get("settings"), name)
        return send_file(
            BytesIO(gcode.encode()),
            mimetype="text/x.gcode",
            as_attachment=True,
            download_name=f"{name}.gcode",
        )

    @app.post("/api/octoprint/test")
    def test_octoprint():
        payload = request.get_json(silent=True) or {}
        status = printer_status(str(payload.get("url", "")), str(payload.get("apiKey", "")))
        return jsonify(
            ok=True,
            state=status.get("state", {}).get("text", "Connected"),
            temperature=status.get("temperature", {}),
        )

    @app.post("/api/octoprint/send")
    def send_to_octoprint():
        payload = request.get_json(silent=True) or {}
        name = _job_name(payload)
        action = payload.get("action", "upload")
        if action not in {"upload", "select", "print"}:
            raise DesignError("Unknown OctoPrint action")
        gcode, stats, warnings = generate_gcode(
            payload.get("design", {}), payload.get("settings"), name
        )
        response = upload_gcode(
            str(payload.get("url", "")),
            str(payload.get("apiKey", "")),
            f"{name}.gcode",
            gcode,
            select_file=action in {"select", "print"},
            start_print=action == "print",
        )
        return jsonify(ok=True, action=action, octoprint=response, stats=stats, warnings=warnings)

    @app.errorhandler(DesignError)
    @app.errorhandler(OctoPrintError)
    def expected_error(exc: Exception):
        return jsonify(error=str(exc)), 400

    @app.errorhandler(413)
    def too_large(_exc):
        return jsonify(error="The design is too large to process"), 413

    return app


app = create_app()


def main() -> None:
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
