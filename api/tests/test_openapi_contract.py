"""The implemented operations match openapi.yaml: paths, methods, status codes, schemas."""

from __future__ import annotations

from typing import Any

import yaml
from fastapi import FastAPI

from tests.conftest import REPO_ROOT

IMPLEMENTED = {
    "adminLogin",
    "getCurrentAdmin",
    "createContract",
    "listContracts",
    "getContract",
    "cancelContract",
    "getContractDownloadUrl",
    "sendContractLink",
    "getContractByToken",
    "submitSignature",
}


def _operations(spec: dict[str, Any]) -> dict[str, tuple[str, str, dict[str, Any]]]:
    ops: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, item in spec["paths"].items():
        for method, op in item.items():
            if method in {"get", "post", "put", "patch", "delete"}:
                ops[op["operationId"]] = (path, method, op)
    return ops


def _schema_name(response: dict[str, Any]) -> str | None:
    content = response.get("content", {}).get("application/json", {})
    ref = content.get("schema", {}).get("$ref")
    return ref.rsplit("/", 1)[-1] if ref else None


def test_implemented_operations_match_contract(app: FastAPI) -> None:
    contract = yaml.safe_load((REPO_ROOT / "openapi.yaml").read_text())
    expected = _operations(contract)
    actual = _operations(app.openapi())

    assert IMPLEMENTED <= set(expected), "operation ids must come from openapi.yaml"
    assert set(actual) == IMPLEMENTED, "no undocumented operations"

    for op_id in IMPLEMENTED:
        c_path, c_method, c_op = expected[op_id]
        a_path, a_method, a_op = actual[op_id]
        assert a_path == f"/api/v1{c_path}", op_id
        assert a_method == c_method, op_id
        assert set(a_op["responses"]) == set(c_op["responses"]), op_id
        for code, c_resp in c_op["responses"].items():
            c_resp = _resolve(contract, c_resp)
            want = _schema_name(c_resp)
            got = _schema_name(a_op["responses"][code])
            assert got == want, (op_id, code, got, want)
        assert bool(c_op.get("security")) == bool(a_op.get("security")), op_id


def _resolve(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    if "$ref" in node:
        parts = node["$ref"].lstrip("#/").split("/")
        cur: Any = spec
        for p in parts:
            cur = cur[p]
        return dict(cur)
    return node


def test_error_codes_and_statuses_are_the_contracts(app: FastAPI) -> None:
    contract = yaml.safe_load((REPO_ROOT / "openapi.yaml").read_text())
    codes = set(contract["components"]["schemas"]["ErrorCode"]["enum"])
    statuses = set(contract["components"]["schemas"]["ContractStatus"]["enum"])
    events = set(contract["components"]["schemas"]["EventType"]["enum"])
    from app.models.contract import ContractStatus
    from app.models.event import EventType
    from app.schemas.common import ErrorCode

    assert {c.value for c in ErrorCode} == codes
    assert {s.value for s in ContractStatus} == statuses
    assert {e.value for e in EventType} == events
    components = app.openapi()["components"]["schemas"]
    assert "Error" in components and components["Error"]["required"] == ["error"]
    assert "HTTPValidationError" not in components
