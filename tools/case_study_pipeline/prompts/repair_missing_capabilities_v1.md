# Repair Prompt: Missing Capabilities v1

Repair only missing or invalid RoomContract capability coverage.

Constraints:
- Every executable or observable ScenarioStep that requires system behaviour must reference a CapabilityUse.
- Every CapabilityUse must point to an existing Capability.
- Every Capability that needs execution must have a RuntimeBinding.
- RuntimeBindings must use valid RuntimeAction entries.
- Keep valid UseCases, Scenarios, ScenarioSteps, Requirements and ValidationCases unchanged.
- Do not invent platform endpoints when a deterministic tool binding is already available.
- Return the full corrected JSON object, not a patch.

Use the supplied `validation_errors` as the primary repair target.
