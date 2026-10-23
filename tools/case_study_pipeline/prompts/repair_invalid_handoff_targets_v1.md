# Repair Prompt: Invalid Handoff Targets v1

Repair only invalid agent roles or handoff links.

Constraints:
- Use only agent IDs generated in the corrected `agents` array.
- Every handoff source and target must refer to an existing agent.
- Do not create self-handoffs.
- Keep valid personas, expertise, grounded object IDs, responsible zone IDs and knowledge tags unchanged.
- Use only allowed zone and object IDs from the provided scene payload.
- Return the full corrected JSON object containing both `agents` and `handoffs`, not a patch.

Use the supplied `validation_errors` as the primary repair target.
