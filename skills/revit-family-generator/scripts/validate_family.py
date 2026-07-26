#!/usr/bin/env python3
"""
Validate a Revit family JSON definition against the schema.
Also performs semantic checks beyond what JSON Schema can enforce.

Usage:
    python validate_family.py <family_json_path> [schema_path]

If schema_path is omitted, looks for family-schema.json in the same directory
as this script's parent references/ folder.
"""

import json
import sys
import os


def find_schema_path(explicit_path=None):
    """Locate the schema file."""
    if explicit_path and os.path.exists(explicit_path):
        return explicit_path

    # Look relative to this script's location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    references_path = os.path.join(script_dir, "..", "references", "family-schema.json")
    if os.path.exists(references_path):
        return references_path

    return None


def validate_schema(family, schema):
    """Run JSON Schema validation. Returns list of error strings."""
    try:
        from jsonschema import validate, ValidationError
        validate(instance=family, schema=schema)
        return []
    except ValidationError as e:
        path = " > ".join(str(p) for p in e.absolute_path)
        return [f"Schema error at [{path}]: {e.message}"]
    except ImportError:
        return ["WARNING: jsonschema not installed, skipping schema validation"]


def validate_semantics(family):
    """Run semantic checks that JSON Schema cannot enforce. Returns list of error/warning strings."""
    issues = []

    # Collect defined names
    ref_plane_names = {rp["name"] for rp in family.get("reference_planes", [])}
    param_names = {p["name"] for p in family.get("parameters", [])}
    geometry_names = {g["name"] for g in family.get("geometry", [])}
    subcategories = set(family.get("subcategories", []))

    # Check geometry references
    for geom in family.get("geometry", []):
        name = geom.get("name", "unnamed")

        # Check sketch_plane references a defined reference plane
        sketch_plane = geom.get("sketch_plane", "")
        if sketch_plane and sketch_plane not in ref_plane_names:
            issues.append(
                f"ERROR: Geometry '{name}' references undefined sketch plane '{sketch_plane}'. "
                f"Defined planes: {sorted(ref_plane_names)}"
            )

        # Check subcategory references
        subcat = geom.get("subcategory")
        if subcat and subcat not in subcategories:
            issues.append(
                f"ERROR: Geometry '{name}' references undefined subcategory '{subcat}'. "
                f"Defined subcategories: {sorted(subcategories)}"
            )

    # Check constraint references
    for constraint in family.get("constraints", []):
        desc = constraint.get("description", "unnamed")

        geom_ref = constraint.get("geometry", "")
        if geom_ref and geom_ref not in geometry_names:
            issues.append(
                f"ERROR: Constraint '{desc}' references undefined geometry '{geom_ref}'. "
                f"Defined geometry: {sorted(geometry_names)}"
            )

        plane_ref = constraint.get("reference_plane", "")
        if plane_ref and plane_ref not in ref_plane_names:
            issues.append(
                f"ERROR: Constraint '{desc}' references undefined plane '{plane_ref}'. "
                f"Defined planes: {sorted(ref_plane_names)}"
            )

    # Check parameter references in expressions
    param_tokens = {p["name"].replace(" ", "_") for p in family.get("parameters", [])}

    def check_expression(expr, context):
        """Check if a string expression references undefined parameters."""
        if not isinstance(expr, str):
            return
        # Simple token extraction: split on operators and whitespace
        import re
        tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', expr)
        for token in tokens:
            # Skip pure numbers and common math tokens
            if token.isdigit():
                continue
            if token not in param_tokens:
                issues.append(
                    f"WARNING: Expression '{expr}' in {context} references token '{token}' "
                    f"which may not match any parameter. Defined parameter tokens: {sorted(param_tokens)}"
                )

    # Check expressions in reference planes
    for rp in family.get("reference_planes", []):
        check_expression(rp.get("offset"), f"reference plane '{rp['name']}'")

    # Check expressions in geometry
    for geom in family.get("geometry", []):
        name = geom.get("name", "unnamed")
        geom_type = geom.get("type", "")

        if geom_type == "extrusion":
            check_expression(geom.get("extrusion_start"), f"geometry '{name}' extrusion_start")
            check_expression(geom.get("extrusion_end"), f"geometry '{name}' extrusion_end")

        if geom_type == "blend":
            check_expression(geom.get("bottom_offset"), f"geometry '{name}' bottom_offset")
            check_expression(geom.get("top_offset"), f"geometry '{name}' top_offset")

        # Check profile expressions
        profile = geom.get("profile") or geom.get("bottom_profile") or geom.get("top_profile")
        if profile:
            for key in ["width", "height", "radius"]:
                if key in profile:
                    check_expression(profile[key], f"geometry '{name}' profile.{key}")
            origin = profile.get("origin") or profile.get("center")
            if origin:
                check_expression(origin.get("u"), f"geometry '{name}' profile origin.u")
                check_expression(origin.get("v"), f"geometry '{name}' profile origin.v")

    # Check for duplicate names
    all_geom_names = [g["name"] for g in family.get("geometry", [])]
    seen = set()
    for name in all_geom_names:
        if name in seen:
            issues.append(f"ERROR: Duplicate geometry name '{name}'")
        seen.add(name)

    all_param_names = [p["name"] for p in family.get("parameters", [])]
    seen = set()
    for name in all_param_names:
        if name in seen:
            issues.append(f"ERROR: Duplicate parameter name '{name}'")
        seen.add(name)

    all_plane_names = [rp["name"] for rp in family.get("reference_planes", [])]
    seen = set()
    for name in all_plane_names:
        if name in seen:
            issues.append(f"ERROR: Duplicate reference plane name '{name}'")
        seen.add(name)

    return issues


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_family.py <family_json_path> [schema_path]")
        sys.exit(1)

    family_path = sys.argv[1]
    schema_path = find_schema_path(sys.argv[2] if len(sys.argv) > 2 else None)

    # Load family JSON
    try:
        with open(family_path) as f:
            family = json.load(f)
    except json.JSONDecodeError as e:
        print(f"FATAL: Invalid JSON in {family_path}: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"FATAL: File not found: {family_path}")
        sys.exit(1)

    all_issues = []

    # Schema validation
    if schema_path:
        with open(schema_path) as f:
            schema = json.load(f)
        all_issues.extend(validate_schema(family, schema))
    else:
        all_issues.append("WARNING: Schema file not found, skipping schema validation")

    # Semantic validation
    all_issues.extend(validate_semantics(family))

    # Report results
    errors = [i for i in all_issues if i.startswith("ERROR")]
    warnings = [i for i in all_issues if i.startswith("WARNING")]

    if not all_issues:
        print("PASSED: All validations passed successfully")
        print(f"  Category: {family.get('metadata', {}).get('category', 'unknown')}")
        print(f"  Geometry elements: {len(family.get('geometry', []))}")
        print(f"  Parameters: {len(family.get('parameters', []))}")
        print(f"  Reference planes: {len(family.get('reference_planes', []))}")
        print(f"  Constraints: {len(family.get('constraints', []))}")
        sys.exit(0)
    else:
        for issue in all_issues:
            print(f"  {issue}")
        print(f"\nSummary: {len(errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
