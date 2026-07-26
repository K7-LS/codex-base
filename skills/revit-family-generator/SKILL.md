---
name: revit-family-generator
description: Use when нужно сгенерировать определение семейства Revit.
---

# Revit Family Generator

You are helping the user create Revit families by generating structured JSON definitions. The input
can be a text description, an uploaded image, or both. The JSON conforms to a specific schema and is
consumed by a C# executor running inside the Revit Family Editor.

Your job is to understand what the user wants to build, ask targeted questions to fill in the details,
and then produce a validated JSON file they can feed into the executor.

## Before Generating Anything

Read `references/family-schema.json` to understand the full schema specification. Read
`references/example-cabinet.json` to see a complete working example for a base cabinet.

The schema supports three geometry types (extrusion, sweep, blend), four profile primitives (rectangle,
circle, l_shape, custom), and parametric expressions that reference family parameters.

## Input Detection

Determine which native custom agent plan to follow based on the user's input:

**Text path:** The user describes what they want in words ("create a 36 inch bookshelf with 4 shelves").
Follow the Text Questioning Flow below.

**Image path:** The user uploads a photo, catalog screenshot, sketch, or spec sheet. Follow the Image
Analysis Flow below.

**Combined:** The user uploads an image AND provides text context ("make a family that looks like this,
it should be about 30 inches wide"). Use the image for shape and proportion, use the text for dimensions
and constraints. Follow the Image Analysis Flow but skip questions that the text already answered.

---

## Image Analysis Flow

When the user uploads an image, analyze it systematically before asking questions.

### Step 1: Identify the Object

Determine what the object is and what Revit category it belongs to. Look for:

- Object type (chair, table, cabinet, shelf unit, desk, bench, fixture, etc.)
- Category (Furniture, Casework, Specialty Equipment, Generic Models, etc.)
- Style cues (modern, traditional, industrial, mid-century) that inform geometry choices

### Step 2: Decompose into Components

Break the object into geometric components that map to extrusions in the schema. Work from large
to small:

- Primary mass (tabletop, cabinet box, seat, etc.)
- Structural supports (legs, panel sides, base, pedestal)
- Secondary elements (aprons, stretchers, shelves, doors, drawers)
- Details (trim, edge profiles, hardware knockouts)

For each component, note:

- Basic shape (rectangular solid, cylinder, L-shape, custom profile)
- Approximate proportional size relative to the whole (legs are about 1/3 of total height, etc.)
- Which sketch plane it would be drawn on
- Whether it is solid or void

### Step 3: Estimate Proportions

Even without dimensions, images carry proportional information. Use these techniques:

- **Relative ratios:** If the tabletop looks 3x wider than it is thick, record that ratio.
- **Known object cues:** A dinner plate is roughly 10 to 11 inches. A door handle is about 36 inches
  from the floor. A standard outlet is about 12 inches from the floor. Use anything visible in the
  image as a scale reference.
- **Human scale:** If a person is visible, use standard body proportions (seated elbow height is about
  28 inches, standing hip height is about 36 inches).
- **Standard sizes:** Many object types have well-known standard dimensions. Use these as starting
  assumptions (see Standard Dimensions Reference below).

### Step 4: Ask Questions (Image Path)

After analyzing the image, ask the user a maximum of 3 to 4 questions. Always include these two:

**Question 1: Detail level.** Present three options:

- **Quick:** Overall shape only. One to three extrusions capturing the bounding volume. Good for
  space planning and early design.
- **Standard:** Major visible components as separate geometry. Legs, top, shelves, panels are all
  distinct. Subcategories applied. Good for presentations and design development.
- **Detailed:** Everything in Standard plus secondary elements like aprons, stretchers, toe kicks,
  panel thickness differences, and edge details. As close to the photo as the schema supports.

**Question 2: Dimensions.** Propose dimensions based on the object type and standard sizes. Present
them as defaults the user can accept or adjust:

> "This looks like a rectangular dining table. Standard dimensions would be about 72 inches long,
> 36 inches wide, and 30 inches tall. Do those work, or do you have specific measurements?"

**Question 3 (only if needed):** Ask about anything ambiguous in the image:

- "I can see legs but cannot tell if there is a stretcher between them. Is there one?"
- "The back of this cabinet is not visible. Should I include a back panel?"
- "This appears to have two drawers on top and a door below. Is that right?"

**Question 4 (only if needed):** Ask about features the image hints at but does not clearly show:

- "Should the shelves be adjustable or fixed?"
- "Do you want the door to be a separate subcategory for visibility control?"

Do not ask about things the image clearly shows. If you can see four legs, do not ask "how many legs."

### Detail Level Geometry Guidelines

**Quick level:**
- Tabletop/seat/shelf: single rectangular extrusion at overall dimensions
- Support structure: single extrusion or omit entirely if the footprint is what matters
- No subcategories needed
- Minimal parameters (Width, Height, Depth only)
- Target: 1 to 3 geometry elements total

**Standard level:**
- Each major visible component gets its own extrusion
- Legs are individual elements (not merged into one)
- Subcategories for distinct component types (Top, Legs, Shelves, etc.)
- Standard parameter set (primary dims + key construction values like leg width, material thickness)
- Target: 5 to 15 geometry elements depending on complexity

**Detailed level:**
- Everything in Standard
- Secondary structure (aprons, stretchers, cross braces, nailers)
- Toe kicks modeled as voids
- Panel thickness differences where visible (thicker top, thinner back)
- More parameters for fine control (apron height, leg setback, stretcher position)
- Target: 10 to 25 geometry elements depending on complexity

---

## Text Questioning Flow

When the user describes what they want in text (no image), follow this flow.

### Question 1: What are you building?

Understand the family at a high level. The user might say something precise like "a 30 inch base cabinet
with two drawers" or vague like "a bookshelf." Either is fine. Extract:

- The general type (cabinet, shelf, table, door, window, etc.)
- The Revit category it belongs to (Casework, Furniture, Doors, Windows, Generic Models, Specialty Equipment)
- Any specific features mentioned (drawers, doors, shelves, legs, etc.)

If the category is obvious from context, do not ask the user to confirm it. Just note it.

### Question 2: What are the key dimensions?

Ask for the primary dimensions: width, height, depth. If the user gave some in their initial description,
confirm them and ask for any missing ones. Also ask about:

- Material thickness (if relevant to the family type)
- Any other critical measurements (toe kick height for cabinets, leg height for tables, etc.)

If reasonable defaults exist for the family type, propose them and let the user accept or adjust.

### Question 3: What should be parametric?

Ask which dimensions the user wants to be adjustable parameters versus fixed values. Propose a sensible
default based on the family type. For example, for a cabinet, Width, Height, and Depth are almost always
parametric, while Material Thickness is often a type parameter with a default.

### Questions 4 and 5 (only if needed):

Ask these only if the family has complexity that the first three questions did not cover. Examples:

- "How many shelves, and should the count be adjustable?"
- "Should the door swing be configurable (left/right/double)?"
- "Do you need any voids or cutouts?"
- "Should any geometry be assigned to subcategories for visibility control?"

If the family is straightforward (like a simple table or shelf), skip directly to generation after
question 3.

---

## Standard Dimensions Reference

Use these as starting assumptions when the user does not provide specific measurements. Always present
them to the user for confirmation.

### Seating
- Dining chair: 18"W x 20"D x 34"H, seat height 18"
- Office chair: 24"W x 24"D x 34"H, seat height 17" to 20"
- Bar stool: 16"W x 16"D x 40" to 42"H, seat height 28" to 30"
- Lounge chair: 32"W x 34"D x 32"H, seat height 15" to 17"
- Sofa (3 seat): 84"W x 36"D x 34"H, seat height 17"
- Bench: 48"W x 16"D x 18"H

### Tables
- Dining table (4 person): 48"L x 30"W x 30"H
- Dining table (6 person): 72"L x 36"W x 30"H
- Coffee table: 48"L x 24"W x 18"H
- Side/end table: 24"W x 24"D x 24"H
- Console table: 48"W x 14"D x 30"H
- Desk: 60"W x 30"D x 30"H
- Standing desk: 60"W x 30"D x 42"H
- Counter height table: 36"H

### Casework
- Base cabinet: 24"W x 24"D x 36"H (counter at 36")
- Upper cabinet: 24"W x 12"D x 30"H (mounted at 54" AFF)
- Tall cabinet/pantry: 24"W x 24"D x 84"H
- Vanity cabinet: 30"W x 21"D x 34"H
- Material thickness: 0.75" (plywood/MDF standard)
- Toe kick: 4" height, 3" setback

### Shelving
- Bookshelf: 36"W x 12"D x 72"H
- Shelf spacing: 10" to 14" between shelves
- Open shelving: 36"W x 10"D x any height
- TV console: 60"W x 18"D x 24"H

### Beds
- Twin: 39"W x 75"L, headboard 48"H
- Full: 54"W x 75"L, headboard 52"H
- Queen: 60"W x 80"L, headboard 56"H
- King: 76"W x 80"L, headboard 58"H
- Platform height: 14" to 18"

### Common Construction Values
- Solid wood leg: 2" to 3" square
- Metal leg: 1" to 1.5" square or round
- Tabletop thickness: 1" to 1.5" (wood), 0.75" (laminate)
- Apron height: 3" to 5"
- Stretcher: 1" to 2" square, positioned 4" to 8" above floor
- Back panel: 0.25" to 0.5" (plywood or hardboard)
- Drawer face height: 6" to 8"
- Door panel: 0.75"

---

## Generating the JSON

Once you have enough information (from either the text path or image path), generate the JSON file.
Follow these rules:

### Metadata

- Set `schema_version` to `"0.1"`
- Set `category` based on the family type
- Include the user's original prompt (or a description of the uploaded image) in the `prompt` field
- Write a clear `description` summarizing what the family is and its key features
- Include `origin_offset` only if the insertion point should differ from the geometric center

### Units

- Default to `"inches"` for US users unless the user specifies otherwise
- If the user gives dimensions in metric, set the units field accordingly

### Reference Planes

Create reference planes for every major boundary and feature line of the family. At minimum:

- Left, Right (x direction, symmetric about origin using Width / 2)
- Front, Back (y direction)
- Top, Bottom (z direction)
- Any internal feature planes (shelf positions, drawer dividers, etc.)

Use parameter expressions for offsets so the planes move when parameters change. For evenly spaced
elements like shelves, use the offset formula from the Spacing Calculations section that accounts for
the material thickness of all elements below the reference plane.

### Parameters

- Use human readable names with spaces (e.g., "Shelf Spacing" not "shelf_spacing")
- In expressions, replace spaces with underscores (e.g., `Shelf_Spacing`)
- Make primary dimensions (Width, Height, Depth) instance parameters
- Make construction details (Material Thickness, gaps) type parameters
- Include a `group` for every parameter: Dimensions, Construction, Identity Data, Graphics, or Other
- Provide sensible defaults for all parameters
- When calculating default values for spacing or derived dimensions, do the full math accounting for
  material thickness of all elements in the stack. Do not round or estimate. Show the calculation in
  the parameter description so the user can verify it.

### Geometry

- Prefer shape primitives (rectangle, circle, l_shape) over custom profiles for reliability
- Use custom profiles only when no primitive fits
- Name every geometry element descriptively (e.g., "Left Side Panel" not "Extrusion 1")
- Assign subcategories when the family has distinct component types (Carcass, Doors, Drawers, etc.)
- Use voids for cutouts (toe kicks, openings) rather than modeling around them
- Keep extrusion_start and extrusion_end as expressions referencing parameters for parametric behavior

### Constraints

- At minimum, align major geometry to its corresponding reference planes
- Use alignment constraints to lock side panels to Left/Right, shelves to their reference planes, etc.
- Keep constraints simple for v1. Do not try to replicate every possible dimensional constraint.

### Spacing Calculations

When calculating even spacing for repeated elements (shelves, dividers, drawers), account for the material
thickness of every element in the stack. The formula for N evenly spaced shelves is:

```
spacing = (total_height - (N + 2) * material_thickness) / (N + 1)
```

Where N is the number of shelves, and (N + 2) accounts for the top panel, bottom panel, and all N shelves.
The (N + 1) divisor creates equal gaps between all horizontal surfaces.

Example: 4 shelves in a 72" bookshelf with 0.75" material:
- Total material: (4 + 2) * 0.75 = 4.5"
- Available space: 72 - 4.5 = 67.5"
- Spacing: 67.5 / 5 = 13.5" between each shelf

Always verify the math adds up: (N + 1) gaps + (N + 2) thicknesses should equal the total height. In
the example: 5 * 13.5 + 6 * 0.75 = 67.5 + 4.5 = 72". Correct.

When setting reference plane offsets for evenly spaced elements, the offset for shelf K (counting from 1)
measured from the bottom is:

```
offset = K * Shelf_Spacing + (K + 1) * Material_Thickness
```

This places each reference plane at the top of the Kth gap, accounting for the bottom panel and all
shelves below it.

### Repetitive Geometry

When a family has multiple identical elements (like shelves), each one needs its own geometry entry and
reference plane in the current schema. This is expected and correct for v1. When generating repetitive
elements:

- Give each a unique, numbered name: "Shelf 1", "Shelf 2", etc.
- Create a corresponding reference plane for each
- Use expressions for offsets so they all respond to parameter changes
- Create an alignment constraint for each element to its reference plane

A future schema version may support array/repeat patterns to reduce this repetition.

### Expression Syntax

All parametric values are written as string expressions:

- Parameter references use underscores for spaces: `Material_Thickness`, `Toe_Kick_Height`
- Basic arithmetic is supported: `+`, `-`, `*`, `/`, parentheses
- Literal numbers are fine for fixed values: `0`, `0.75`
- Mixed expressions: `"Width - 2 * Material_Thickness"`

### What to Skip (v1 Limitations)

- Material assignments (planned for future)
- Nested family references (hardware, hinges)
- Connector points
- Type catalogs
- 2D symbolic/detail geometry
- Visibility parameters

Include these as entries in the `_TODO` array so the user knows what is planned.

## After Generating

### Validate the JSON

First, verify the math. Before running the schema validator, check that:

- Spacing calculations add up correctly (gaps + material thicknesses = total dimension)
- Default values for derived parameters match the formulas (e.g., if Width=36, Material Thickness=0.75,
  then "Width - 2 * Material_Thickness" should equal 34.5)
- No geometry overlaps when defaults are applied (shelf positions don't collide, panels don't extend
  beyond the bounding box)

Then use the validation script in the computer environment:

```bash
python3 scripts/validate_family.py <generated_json_path> references/family-schema.json
```

The script validates against the JSON Schema and performs semantic checks: verifying that geometry
references valid sketch planes, subcategories exist, constraints point to real geometry and planes,
and parameter expressions reference defined parameters.

If validation fails, fix the issue and re-validate before presenting to the user.

### Present a Plain Language Summary

Before showing the JSON file, give the user a brief summary of what you built. Structure it like this:

**Family:** [name and category]
**Detail Level:** [Quick / Standard / Detailed] (include for image path)
**Dimensions:** [width x height x depth with defaults]
**Components:** [list the major geometry pieces]
**Parameters:** [list adjustable parameters with defaults]
**Notes:** [anything the user should know, gotchas, limitations]

Then present the JSON file for download.

### Invite Iteration

After presenting, ask the user if they want to make changes. Examples of what they might say:

- "Add a middle shelf at 18 inches"
- "Make it 36 inches wide instead"
- "Add a second drawer"
- "Remove the back panel"
- "Can you add more detail to the legs?"
- "Switch to Quick, I just need the footprint"

When iterating, regenerate the complete JSON (clear and rebuild approach). Do not try to patch the
previous version. The JSON is always the single source of truth.

## Coordinate System Reference

Understanding how sketch planes map to 3D space is critical for correct geometry:

| Sketch Plane Direction | Plane Faces | u axis maps to | v axis maps to |
|----------------------|-------------|-----------------|-----------------|
| x (Left/Right)       | YZ plane    | y (depth)       | z (height)      |
| y (Front/Back)       | XZ plane    | x (width)       | z (height)      |
| z (Top/Bottom)       | XY plane    | x (width)       | y (depth)       |

Extrusion direction is always perpendicular to the sketch plane (along the plane's normal direction).
Positive extrusion_end goes in the positive axis direction from the plane.

## Common Family Patterns

Use these as starting points when the user requests common family types:

**Base Cabinet:** Side panels, bottom shelf, back panel, toe kick void, door(s), drawer(s). Origin centered
on width, front face at y=0.

**Upper Cabinet:** Side panels, top/bottom shelves, back panel, door(s). No toe kick. Origin centered on
width, front face at y=0.

**Bookshelf:** Side panels, top, bottom, fixed/adjustable shelves, back panel, optional base. Origin
centered on width, front face at y=0. Shelves and top/bottom panels fit between side panels (width reduced
by 2 * Material Thickness). Shelf depth is reduced by Material Thickness to account for the back panel.
Use the spacing formula from the Spacing Calculations section for even shelf placement.

**Dining Table:** Tabletop, four legs (or panel legs), apron frame. Origin centered on length, front edge
at y=0, floor at z=0. Legs run from floor to underside of top. Aprons connect between legs.

**Desk:** Top surface, legs or panel supports, optional drawers/cabinet section, optional modesty panel.
Origin centered on width, front at y=0.

**Chair:** Seat, backrest, legs, optional arms. Origin centered on width, front legs at y=0. Seat at
standard 18" height. Quick level: just the seat box and backrest box.

**Door (simplified):** Panel, frame elements. Wall hosted, origin at wall face center bottom.

**Window (simplified):** Frame, glazing panel(s), sill. Wall hosted, origin at wall face center at sill.

## Reference Files

| File | Purpose |
|------|---------|
| `references/family-schema.json` | The complete JSON Schema specification. Read this first. |
| `references/example-cabinet.json` | A working example of a base cabinet. Use as a template for similar families. |
| `scripts/validate_family.py` | Validation script that checks both schema conformance and semantic correctness. Run after every generation. |
