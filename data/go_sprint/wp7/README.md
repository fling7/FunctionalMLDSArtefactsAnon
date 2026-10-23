# Cooperative protocol data

This bounded dataset contains the selected completed protocol runs, their row-level data and processed summaries. JSON and JSONL files are copied byte-for-byte; source paths and SHA-256 digests are recorded in source_manifest.json.

The retained index reports 12 interleaving cells and 281,000 reachable abstract states, with zero cooperative violating schedules. Packet and direct-edit counterexamples each occur in four cells. There are 20 append-fault cells, four post-fix atomic restore cells and 32 synthetic scope rows. The selected stress run contains 400 sessions: 250 committed and 150 aborted. Its cooperative monitored subset contains 100 commits with zero observed generation or manifest mismatch.

These units must not be pooled. Abstract states are not independent observations; monitored commits do not prove safety for arbitrary unlocked readers or external side effects. Model responses were scripted. Use the original per-cell rows for distinctions between strategies.

The historical summary's natural-pairs value of zero describes that old protocol run only. Later natural/evolution comparisons are delivered separately in ../wp4_wp5; they do not retroactively extend this cohort.

Included: top-level JSON/JSONL records from the selected closed raw runs and existing processed WP7 summaries. Excluded from this compact data delivery: duplicated source snapshots, project trees, lock files and per-project runtime directories. Those remain in the original workspace; this package is data for analysis, not a complete experiment rerunner.
