"""Extracts a JSON-renderable form schema from ACE-Step-1.5's own
`GenerateMusicRequest` Pydantic model (its real `/release_task` request
contract) by parsing that file's actual source with Python's `ast` module —
not hand-maintained, not guessed from the Gradio UI (which has no stable API
contract — its "Generate" button is wired through internal lambda/chained
event handlers with no declared `api_name`, confirmed by reading that code).

This can't be done by querying the running server's `/openapi.json`: the
`/release_task` route takes a raw `Request` and parses the body itself (to
support both JSON and multipart file uploads), so FastAPI never sees a typed
parameter and never documents the schema. Reading the model class straight
from the installed copy on disk is the only way to stay genuinely in sync
with whatever fields the currently-installed ACE-Step version actually
defines — called automatically after every install/update/reset (see
`ace_step.py`'s `install()`/`update_to_official()`), not just once by hand.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

RELEASE_TASK_MODELS_RELATIVE_PATH = "acestep/api/http/release_task_models.py"
TARGET_CLASS_NAME = "GenerateMusicRequest"
CONSTANTS_RELATIVE_PATH = "acestep/constants.py"

# A few request-model fields are plain `str` in GenerateMusicRequest (no
# Literal/enum in the type itself — confirmed by reading that class), but
# ACE-Step's own Gradio UI wires them up from a real, shared module-level
# constant elsewhere in its codebase (e.g. vocal_language's dropdown is
# built from constants.py's VALID_LANGUAGES, not hardcoded in the UI file).
# Pulling the choices from that constant — rather than hand-typing ACE-Step's
# language list ourselves — keeps this auto-derived: if ACE-Step adds a
# language to VALID_LANGUAGES, it shows up here next regeneration with no
# code change. The field-name -> constant-name association itself is the
# only hand-maintained part, and it's small and rarely-changing (renaming
# either side is a one-line fix here, not a recurring maintenance burden).
FIELD_ENUM_CONSTANTS = {"vocal_language": "VALID_LANGUAGES", "task_type": "TASK_TYPES"}


class SchemaExtractionError(RuntimeError):
    pass


def _literal(node: ast.expr | None) -> Any:
    """Best-effort literal value of an AST node — falls back to its source
    text for anything not a plain literal (e.g. `DEFAULT_DIT_INSTRUCTION`, a
    module-level constant reference we can't resolve without importing
    ACE-Step's own code, which this script deliberately avoids)."""
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node)


def _annotation_info(annotation: ast.expr) -> dict:
    """Reduces a type annotation (e.g. `bool`, `Optional[int]`,
    `Literal["a", "b"]`, `Union[int, str]`) to a simple
    {type, enumValues, optional} the renderer can act on without needing a
    real Python type system."""
    text = ast.unparse(annotation)
    optional = "Optional[" in text or "None]" in text or text.endswith("| None")

    # Literal["a", "b", ...] -> a dropdown of those exact choices.
    if isinstance(annotation, ast.Subscript):
        base = ast.unparse(annotation.value)
        if base == "Literal":
            elts = annotation.slice.elts if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
            return {"type": "enum", "enumValues": [_literal(e) for e in elts], "optional": optional}

    lowered = text.lower()
    if "bool" in lowered:
        kind = "boolean"
    elif "float" in lowered:
        kind = "number"
    elif "int" in lowered:
        kind = "integer"
    elif "list" in lowered:
        kind = "list"
    else:
        # str, Union[int, str] (e.g. `seed`), or anything else not worth a
        # dedicated widget — a plain text input lets the user type whatever
        # the field actually needs, even if our heuristics don't have a
        # purpose-built control for it.
        kind = "string"
    return {"type": kind, "enumValues": None, "optional": optional}


# Field names whose values are routinely long free text (prompts, lyrics,
# instructions) — rendered as a multi-line textarea instead of a single-line
# input. Matched by substring since e.g. `lm_negative_prompt` should count
# too, not just the exact field name `prompt`.
_MULTILINE_HINTS = ("prompt", "lyric", "caption", "instruction", "query")


def _field_from_assign(node: ast.AnnAssign) -> dict | None:
    if not isinstance(node.target, ast.Name):
        return None
    name = node.target.id

    info = _annotation_info(node.annotation)
    description = ""
    default = None
    minimum = None
    maximum = None

    value = node.value
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "Field":
        for kw in value.keywords:
            if kw.arg == "default":
                default = _literal(kw.value)
            elif kw.arg == "description":
                description = _literal(kw.value) or ""
            elif kw.arg == "ge":
                minimum = _literal(kw.value)
            elif kw.arg == "le":
                maximum = _literal(kw.value)
        # `Field(...)` with no explicit `default=` (positional-only) — first
        # positional arg is the default, matching Pydantic's own signature.
        if default is None and value.args:
            default = _literal(value.args[0])
    else:
        default = _literal(value)

    return {
        "name": name,
        "type": info["type"],
        "enumValues": info["enumValues"],
        "optional": info["optional"],
        "multiline": info["type"] == "string" and any(h in name.lower() for h in _MULTILINE_HINTS),
        "default": default,
        "description": description,
        "min": minimum,
        "max": maximum,
    }


def _load_constants(ace_step_dir: Path) -> dict[str, list]:
    """Module-level `NAME = [...]` list-literal assignments in
    constants.py — a real, stable source of truth for choice lists that
    aren't expressed as a Literal type in the request model itself (see
    FIELD_ENUM_CONSTANTS)."""
    path = ace_step_dir / CONSTANTS_RELATIVE_PATH
    if not path.exists():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    constants: dict[str, list] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            try:
                value = ast.literal_eval(stmt.value)
            except (ValueError, TypeError):
                continue
            if isinstance(value, list):
                constants[stmt.targets[0].id] = value
    return constants


def extract_schema(ace_step_dir: Path) -> dict:
    source_path = ace_step_dir / RELEASE_TASK_MODELS_RELATIVE_PATH
    if not source_path.exists():
        raise SchemaExtractionError(f"{source_path} not found — is ACE-Step-1.5 actually installed/cloned?")

    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    target = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == TARGET_CLASS_NAME),
        None,
    )
    if target is None:
        raise SchemaExtractionError(f"Class {TARGET_CLASS_NAME} not found in {source_path}.")

    constants = _load_constants(ace_step_dir)

    fields = []
    for stmt in target.body:
        if isinstance(stmt, ast.AnnAssign):
            field = _field_from_assign(stmt)
            if field is None:
                continue
            constant_name = FIELD_ENUM_CONSTANTS.get(field["name"])
            if constant_name and constant_name in constants:
                field["type"] = "enum"
                field["enumValues"] = [str(v) for v in constants[constant_name]]
            fields.append(field)

    if not fields:
        raise SchemaExtractionError(f"No fields extracted from {TARGET_CLASS_NAME} — its definition may have changed shape.")

    return {"fields": fields}


def write_schema(ace_step_dir: Path, out_path: Path) -> dict:
    schema = extract_schema(ace_step_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return schema
