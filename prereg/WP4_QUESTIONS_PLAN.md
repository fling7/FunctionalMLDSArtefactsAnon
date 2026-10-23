# WP4 frozen-question generation plan

Separate judges-share authorization and hash are required before generation. This does not authorize semantic judging.

```json
{
  "version": 1,
  "experiment_id": "WP4.questions",
  "share": "judges",
  "model": "gpt-4.1-mini-2025-04-14",
  "temperature": 0.3,
  "input_limit": 6000,
  "output_limit": 256,
  "max_source_rooms_including_example": 21,
  "max_objects_per_room": 18,
  "max_calls": 378,
  "per_call_ceiling_usd": "0.0028096",
  "total_ceiling_usd": "1.0620288",
  "questions_per_object": 2,
  "validity_checks": "Both nonempty string fields must differ and each must contain the supplied object name or source identifier, case-insensitively; failures are retained without repair.",
  "prompt_path": "experiments/prompts/wp4/questions.txt",
  "prompt_sha256": "342a2c29466cc41bd1b4ed4ed4acebd00e8fb5af02cfb1c3757944a8bf914b01",
  "code_paths": [
    "experiments/routing_baselines.py",
    "experiments/lib/wp4_common.py"
  ],
  "code_sha256": {
    "experiments/routing_baselines.py": "57189cad13ab6c1a733860dc7bb2d066374ee0b6548d8f0bf1e525b975083892",
    "experiments/lib/wp4_common.py": "d269ab8fd47b580bd1c36b578f4050b3147a0daef18f7470b21acee3021ac1e8"
  },
  "selection": "Union of primary object, fifteen admitted pair objects, primary mismatch object, and turn mismatch object; at most eighteen distinct objects. Same frozen questions reused across every model and condition.",
  "input": "Object name/id/type, full source specification, four deterministic KB.search excerpts with no content truncation.",
  "failure": "One generation attempt per object, gateway at most five HTTP retries. API/input-limit/format failures retained; no regenerated question. Freeze questions.json SHA256 before any routing/HTTP evaluation; never replace missing questions with fabricated natural questions."
}
```
