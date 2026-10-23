# roomcontract_assembly_v1

Diese Prompt-Version dokumentiert die optionale LLM-Variante der RoomContract-
Assemblierung. Die aktuelle Case-Study-Pipeline erzeugt die normative
RoomContract-Instanz deterministisch aus validierten Artefakten, damit
Kardinalitaeten, XOR-Regeln und Runtime-Trennung reproduzierbar bleiben.

Ein LLM darf in spaeteren Varianten nur beschreibende Texte verbessern. Es darf nicht:
- ScenarioSteps direkt auf RuntimeActions abbilden,
- Endpoints, Tools oder Topics in Capability oder ScenarioStep schreiben,
- Satisfy-Beziehungen erzeugen, die gleichzeitig Requirement und UseCase referenzieren,
- Actor und Agent vermischen,
- ValidationCases ohne erwartete StateAssertions erzeugen.
