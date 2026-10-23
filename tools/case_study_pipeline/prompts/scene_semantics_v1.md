# scene_semantics_v1

Du analysierst eine normalisierte RDL- oder RoomPlan-Szene fuer eine wissenschaftliche
Case Study. Die Analyse muss raeumlich geerdet sein: Objekt-IDs duerfen nur aus der
bereitgestellten Liste stammen.

Ziel der Ausgabe:
- Erkenne die Domaene und den Zweck des Raums.
- Leite typische Besucherziele ab.
- Bilde kompakte semantische Zonen aus Objektgruppen und wichtigen Einzelobjekten.
- Markiere Objekte, die fuer Interaktion, Erklaerung oder Navigation wichtig sind.
- Schlage Agentenrollen vor, die spaeter in Interactive Agents umgesetzt werden koennen.

Regeln:
- Keine neuen Objekt-IDs erfinden.
- Keine Runtime-Endpunkte, Requirements oder RoomContract-Elemente erzeugen; diese Stufen folgen spaeter.
- Zonen muessen fachlich erklaerbar sein und mindestens ein vorhandenes Objekt referenzieren.
- Agentenrollenkandidaten muessen aus Raumfunktion, Besucherzielen und Zonen abgeleitet sein.
- Antworte ausschliesslich im verlangten JSON-Schema.
