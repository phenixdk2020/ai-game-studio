"""Deterministic prop QA, independent of Blender and Unreal."""
import math


DEFAULT_PROFILE = {
    "triangle_warning": 60000,
    "triangle_limit": 150000,
    "require_uv": True,
    "require_materials": True,
    "non_manifold_limit": 0,
}


def validate_profile(profile=None):
    if profile is not None and (not isinstance(profile, dict) or set(profile) - set(DEFAULT_PROFILE)):
        raise ValueError("Unknown QA profile options")
    policy = {**DEFAULT_PROFILE, **(profile or {})}
    for key in ("triangle_warning", "triangle_limit", "non_manifold_limit"):
        if type(policy[key]) is not int or policy[key] < 0:
            raise ValueError(f"Invalid QA threshold: {key}")
    if policy["triangle_warning"] > policy["triangle_limit"]:
        raise ValueError("Warning threshold exceeds triangle limit")
    for key in ("require_uv", "require_materials"):
        if type(policy[key]) is not bool:
            raise ValueError(f"Invalid QA flag: {key}")
    return policy


def evaluate(metrics, profile=None):
    policy = validate_profile(profile)
    for key in ("mesh_count", "vertices", "triangles", "non_manifold_edges", "missing_textures"):
        if type(metrics.get(key)) is not int or metrics[key] < 0:
            raise ValueError(f"Missing or invalid metric: {key}")
    dims = metrics.get("dimensions_m")
    if not isinstance(dims, list) or len(dims) != 3 or any(
        type(x) not in (float, int) or not math.isfinite(x) or x < 0 for x in dims
    ):
        raise ValueError("Invalid dimensions_m")
    for key in ("has_uv", "has_materials"):
        if type(metrics.get(key)) is not bool:
            raise ValueError(f"Missing or invalid metric: {key}")
    checks = {
        "mesh_readable": "pass" if metrics["mesh_count"] > 0 and metrics["vertices"] > 0 and metrics["triangles"] > 0 else "fail",
        "scale": "pass" if max(dims) > 0 else "fail",
        "triangle_budget": "fail" if metrics["triangles"] > policy["triangle_limit"] else (
            "warning" if metrics["triangles"] > policy["triangle_warning"] else "pass"),
        "non_manifold": "warning" if metrics["non_manifold_edges"] > policy["non_manifold_limit"] else "pass",
        "uv": "fail" if policy["require_uv"] and not metrics["has_uv"] else "pass",
        "materials": "fail" if policy["require_materials"] and not metrics["has_materials"] else "pass",
        "textures": "fail" if metrics["missing_textures"] else "pass",
    }
    status = "fail" if "fail" in checks.values() else "warning" if "warning" in checks.values() else "pass"
    return {"schemaVersion": 1, "status": status, "checks": checks, "metrics": metrics,
            "profile": policy, "warnings": [key for key, value in checks.items() if value == "warning"],
            "recommended_actions": [f"Inspect or repair {key}" for key, value in checks.items() if value != "pass"]}


def markdown(report):
    rows = ["# Asset QA", "", f"Status: {report['status']}", "", "| Check | Result |", "| --- | --- |"]
    rows.extend(f"| {key} | {value} |" for key, value in report["checks"].items())
    rows.extend(["", "## Recommended actions", ""] + [f"- {item}" for item in report["recommended_actions"]])
    return "\n".join(rows) + "\n"
