"""Validate API v2 responses against docs/v2/api/openapi.yaml.

    from padel_league.tests.contract import assert_matches_spec
    resp = client.get("/api/v2/competitions")
    assert_matches_spec(resp, "/competitions", "get")

Path templates are the spec's (`/groups/{groupId}`), not the concrete URL.
OpenAPI 3.1 schemas are JSON Schema 2020-12, so `jsonschema` validates them
directly; `$ref`s resolve against the whole spec document.
"""

from functools import lru_cache
from pathlib import Path

import jsonschema
import yaml

SPEC_PATH = Path(__file__).resolve().parents[2] / "docs" / "v2" / "api" / "openapi.yaml"


@lru_cache(maxsize=1)
def spec():
    return yaml.safe_load(SPEC_PATH.read_text())


def _resolve(node):
    while isinstance(node, dict) and "$ref" in node:
        target = spec()
        for part in node["$ref"].lstrip("#/").split("/"):
            target = target[part]
        node = target
    return node


def response_schema(path, method, status):
    operation = spec()["paths"][path][method.lower()]
    responses = operation["responses"]
    response = _resolve(responses.get(str(status)) or responses.get("default"))
    if response is None:
        raise AssertionError(f"{method.upper()} {path} does not document status {status}")
    content = response.get("content", {}).get("application/json")
    return content["schema"] if content else None


def assert_matches_spec(response, path, method="get"):
    """Assert a Flask test response's status is documented and its JSON body matches."""
    schema = response_schema(path, method, response.status_code)
    if schema is None:
        return
    # Validate inside the spec document so "#/components/..." refs resolve.
    wrapper = {**spec(), "$ref": "#/__target__", "__target__": schema}
    validator = jsonschema.Draft202012Validator(wrapper)
    errors = sorted(validator.iter_errors(response.get_json()), key=lambda e: list(e.path))
    if errors:
        lines = [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors[:10]]
        raise AssertionError(f"{method.upper()} {path} {response.status_code} breaks the spec:\n" + "\n".join(lines))
