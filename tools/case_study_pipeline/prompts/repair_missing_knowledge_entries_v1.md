# Repair Prompt: Missing Knowledge Entries v1

Repair only missing or invalid knowledge entries.

Constraints:
- Cover every required agent knowledge tag.
- Cover every non-structural object group listed in `required_room_groups`.
- Keep valid knowledge entries unchanged.
- Do not remove a knowledge entry unless the validator identifies it as invalid or unrelated.
- Ground every knowledge entry in scene objects, zones, agent expertise or interaction topics from the payload.
- Use `source_object_ids` so each required room/object group is represented by at least one real object ID.
- Ensure every entry has at least one `intended_agents` value.
- Include enough room knowledge for object/zone questions such as "Welche Objekte gibt es hier?".
- Keep entries compact and suitable for retrieval by the Interactive Agents backend.
- Return the full corrected JSON object, not a patch.

Use the supplied `validation_errors` as the primary repair target.
