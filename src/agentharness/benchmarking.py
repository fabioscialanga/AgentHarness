from __future__ import annotations

import json
from pathlib import Path
from typing import Any

RUN_ID_PLACEHOLDER = "__RUN_ID__"


def _render_placeholders(value: Any, *, run_id: str) -> Any:
    if isinstance(value, str):
        return value.replace(RUN_ID_PLACEHOLDER, run_id)
    if isinstance(value, list):
        return [_render_placeholders(item, run_id=run_id) for item in value]
    if isinstance(value, dict):
        return {key: _render_placeholders(item, run_id=run_id) for key, item in value.items()}
    return value


def render_json_template(template_path: str | Path, *, run_id: str) -> dict[str, Any]:
    candidate_run_id = run_id.strip()
    if not candidate_run_id:
        raise ValueError("run_id must be non-empty")
    resolved_template = Path(template_path).resolve()
    payload = json.loads(resolved_template.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Template JSON must parse to an object")
    rendered = _render_placeholders(payload, run_id=candidate_run_id)
    if not isinstance(rendered, dict):
        raise ValueError("Rendered template must be an object")
    return rendered


def write_rendered_json_template(
    template_path: str | Path,
    *,
    run_id: str,
    output_path: str | Path,
) -> Path:
    rendered = render_json_template(template_path, run_id=run_id)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(rendered, indent=2) + "\n", encoding="utf-8")
    return destination.resolve()