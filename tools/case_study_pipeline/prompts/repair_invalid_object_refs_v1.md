# Repair Prompt: Invalid Object References v1

Repair only the invalid parts of the previously generated scene semantics.

Constraints:
- Use only object IDs listed in `scene.allowed_object_ids`.
- Keep all valid visitor goals, semantic zones, important objects, interaction topics and role candidates unchanged.
- Remove or replace references to unknown objects.
- Do not invent new RDL objects.
- Preserve the intended room semantics as much as possible.
- Return the full corrected JSON object, not a patch.

Use the supplied `validation_errors` as the primary repair target.
