# agent_roles_v1

Du erzeugst aus einer validierten semantischen Raumanalyse konkrete Agentenrollen fuer
Interactive Agents. Die Ausgabe muss backend-kompatibel sein und spaeter direkt zu
`agents.json`, Wissensdateien, RoomContract-Agenten und Handoff-Regeln fuehren.

Ziel:
- Verdichte die Rollenkandidaten zu 2 bis 8 klar unterscheidbaren Agenten.
- Jede Rolle muss fachlich an Zonen oder Objekte gebunden sein.
- Jede Rolle braucht eine Persona, Expertise, Wissenstags, `voice`, `voice_gender`, `voice_style` und `tts_model`.
- Handoffs sollen nur zwischen existierenden Agenten vorkommen und fachlich begruendet sein.

Regeln:
- Agent-IDs und Wissenstags muessen slug-kompatibel sein: kleinbuchstaben, zahlen, `_` oder `-`.
- Verwende nur vorhandene `zone_id` und `object_id` Werte aus der Eingabe.
- `tts_model` soll `gpt-4o-mini-tts` sein, nicht `standard`.
- `voice_gender` muss gesetzt sein; verwende nur einfache Werte wie `weiblich` oder `maennlich`.
- Keine frei erfundenen Runtime-Endpunkte, Requirements oder RoomContract-IDs erzeugen.
- Handoffs sind nur fachliche Weiterleitungen, keine Gesprächslogik im Detail.
- Antworte ausschliesslich im verlangten JSON-Schema.
