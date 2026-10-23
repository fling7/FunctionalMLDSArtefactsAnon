% Independent admission policy. No routing decisions are supplied by Python.
% A stratified program: unique stable model; integer priorities choose a reason.

typed(I,T) :- obj(_,I,T).
agent(A) :- typed(A,"Agent").
wire_agent(A,W) :- agent(A), v(A,"sourceAgentId",W), vt(A,"sourceAgentId","string").
scene(T) :- typed(T,"Entity"), v(T,"kind","asset"), v(T,"entityRole","sceneObject").
group(G) :- typed(G,"Entity"), v(G,"kind","asset"), v(G,"entityRole","objectGroup").
zone(Z) :- typed(Z,"Entity"), v(Z,"kind","zone"), v(Z,"entityRole","semanticZone").
wire_target(T,W) :- scene(T), v(T,"sourceId",W), vt(T,"sourceId","string").

% Only unparseable structure and duplicate object IDs are publication failures.
publication_error :- bad_top(_).
publication_error :- bad_record(_).
publication_error :- obj(N,I,_), obj(M,I,_), N != M.

% Gate 1: compare the request with its session pin, never a current publication.
digest_matches :- digest("request",D), digest("session",D), digest_shape("request"), digest_shape("session").
failure(10,"E_STALE_DIGEST") :- not digest_matches.

% Non-deictic operation is outside this evaluator's admission scope.
selection_invalid :- field("request","interaction_mode","non_deictic").
selection_invalid :- not field_type("request","spatial_context","object").
selection_invalid :- not field("spatial","state","resolved").
selection_invalid :- field("spatial","ambiguous",true).
selection_invalid :- field("spatial","ambiguity",true).
selection_invalid :- truthy_ambiguity_member("ambiguous").
selection_invalid :- truthy_ambiguity_member("is_ambiguous").
identity_key("entity_id";"source_object_id";"source_id").
selection_invalid :- identity_key(K), field_type("spatial",K,T), T != "string".
selection_invalid :- field_type("spatial","candidate_entity_ids",T), T != "array".
selection_invalid :- candidate_type(_,T), T != "string".
selection_invalid :- field_type("spatial","candidate_entity_ids","array"), #count{N,T:candidate(N,T)} != 1.

% All supplied identities resolve uniquely, then must agree on the target.
identity_present(K) :- identity_key(K), field("spatial",K,_).
identity_resolution("entity_id",T) :- field("spatial","entity_id",T), scene(T).
identity_resolution(K,T) :- K="source_object_id", field("spatial",K,W), wire_target(T,W).
identity_resolution(K,T) :- K="source_id", field("spatial",K,W), wire_target(T,W).
identity_unknown :- not identity_present(_).
identity_unknown :- identity_present(K), #count{T:identity_resolution(K,T)} != 1.
identity_mismatch :- identity_resolution(K,T), identity_resolution(J,U), K != J, T != U.
selected_target(T) :- identity_resolution(_,T), not identity_unknown, not identity_mismatch.
selection_invalid :- selected_target(T), candidate(_,U), T != U.
failure(20,"E_SELECTION_STATE") :- selection_invalid.
failure(21,"E_UNKNOWN_ENTITY") :- identity_unknown.
failure(22,"E_ID_MISMATCH") :- identity_mismatch.

% Optional server tracking is an extra active-agent check before responsibility.
active_candidate(A) :- field("request","active_agent_id",W), wire_agent(A,W).
active(A) :- active_candidate(A), #count{B:active_candidate(B)} = 1.
failure(30,"E_ACTIVE_AGENT_UNKNOWN") :- #count{A:active_candidate(A)} != 1.
strict_matches :- field("request","active_agent_id",W), field("session","active_agent_id",W).
failure(31,"E_ACTIVE_AGENT_MISMATCH") :- field("session","active_agent_mode","server_strict"), not strict_matches.

% Responsibility levels are agent sets. Group projections do not add membership.
member_group(T,G) :- scene(T), group(G), r(T,"objectGroup",_,G).
member_zone(T,Z) :- wire_target(T,W), zone(Z), r(Z,"sourceObjectId",_,W).
owner_at(T,1,A) :- scene(T), agent(A), r(A,"groundedAsset",_,T).
owner_at(T,2,A) :- member_group(T,G), agent(A), r(A,"groundedObjectGroup",_,G).
owner_at(T,3,A) :- member_zone(T,Z), agent(A), r(A,"responsibleZone",_,Z).
occupied(T,L) :- owner_at(T,L,_).
more_specific(T,L) :- occupied(T,L), occupied(T,K), K < L.
deciding_level(T,L) :- occupied(T,L), not more_specific(T,L).
owner(T,A) :- deciding_level(T,L), owner_at(T,L,A).
provider(T,P) :- owner(T,P), #count{A:owner(T,A)} = 1.
failure(40,"E_UNOWNED") :- selected_target(T), #count{A:owner(T,A)} = 0.
failure(41,"E_AMBIGUOUS_OWNER") :- selected_target(T), #count{A:owner(T,A)} > 1.
reachable(A,P) :- agent(A), agent(P), A=P.
reachable(A,P) :- agent(A), agent(P), r(A,"handoffTarget",_,P).
failure(42,"E_NO_HANDOFF_PATH") :- selected_target(T), provider(T,P), active(A), not reachable(A,P).

% Explicit applicationActionKind controls classification; endpoint is fallback.
input_kind(A,K) :- typed(A,"RuntimeAction"), r(A,"inputSchema",_,I), schema_kind(I,K).
answer_action(A) :- input_kind(A,"chat").
answer_action(A) :- typed(A,"RuntimeAction"), not input_kind(A,_), r(A,"locator",_,L), typed(L,"RuntimeActionLocator"), v(L,"kind","endpoint"), v(L,"value","POST /chat").

% Independently traverse s -> u -> c -> b -> a using native records and links.
native_path(S,U,C,B,A,P,T) :-
    typed(S,"ScenarioStep"), r(S,"capabilityUse",_,U), typed(U,"CapabilityUse"),
    r(U,"provider",_,P), agent(P), r(U,"target",_,T), scene(T),
    r(U,"typeRef",_,C), typed(C,"Capability"),
    typed(B,"RuntimeBinding"), r(B,"capability",_,C),
    r(B,"runtimeAction",_,A), typed(A,"RuntimeAction"), answer_action(A).
chosen_path(S,U,C,B,A,P,T) :- selected_target(T), provider(T,P), native_path(S,U,C,B,A,P,T).
path_ambiguous :- #count{S,U,C,B,A,P,T:chosen_path(S,U,C,B,A,P,T)} > 1.
path_ambiguous :- chosen_path(_,U,_,_,_,_,_), #count{N,P:r(U,"provider",N,P)} > 1.
path_ambiguous :- chosen_path(_,U,_,_,_,_,_), #count{N,C:r(U,"typeRef",N,C)} > 1.
path_ambiguous :- chosen_path(_,_,_,B,_,_,_), #count{N,C:r(B,"capability",N,C)} > 1.
path_broken :- chosen_path(_,_,C,_,_,P,_), not r(P,"providedCapability",_,C).
path_broken :- chosen_path(_,_,_,_,_,P,_), not wire_agent(P,_).

% Match selected trace projection. Trace tuples never generate native paths.
trace_targets_differ(R,U) :- trace_row(R), typed(U,"CapabilityUse"), r(U,"target",_,T), not tr(R,_,T).
trace_targets_differ(R,U) :- trace_row(R), typed(U,"CapabilityUse"), tr(R,_,T), not r(U,"target",_,T).
projection(R,S,U,C,B,A,P,T) :- chosen_path(S,U,C,B,A,P,T),
    tv(R,"action_kind","chat"), tv(R,"scenario_step_id",S),
    tv(R,"capability_use_id",U), tv(R,"capability_id",C),
    tv(R,"provider_entity_id",P), tv(R,"runtime_binding_id",B),
    tv(R,"runtime_action_id",A), trace_targets_present(R), not trace_targets_differ(R,U).
path_ambiguous :- chosen_path(S,U,C,B,A,P,T), #count{R:projection(R,S,U,C,B,A,P,T)} > 1.
path_broken :- chosen_path(S,U,C,B,A,P,T), #count{R:projection(R,S,U,C,B,A,P,T)} = 0.
failure(50,"E_ACTION_AMBIGUOUS") :- path_ambiguous.
failure(51,"E_NO_DECLARED_ACTION") :- selected_target(T), provider(T,_), not chosen_path(_,_,_,_,_,_,T).
failure(51,"E_NO_DECLARED_ACTION") :- path_broken.

% Final schema gate. JSON Schema evaluation itself is a factual validator result.
valid_action_schema(A) :- typed(A,"RuntimeAction"),
    #count{N,I:r(A,"inputSchema",N,I)} = 1,
    r(A,"inputSchema",_,I), typed(I,"SchemaReference"), v(I,"uri","json"), schema_pass(I).
failure(60,"E_SCHEMA") :- chosen_path(_,_,_,_,A,_,_), not valid_action_schema(A).

% Global malformed input is the one precondition outside the ordered five gates.
failure(0,"E_PUBLICATION_INCONSISTENT") :- publication_error.
earlier(N) :- failure(N,_), failure(M,_), M < N.
first_failure(N,R) :- failure(N,R), not earlier(N).
verdict("REJECT",R,null,null) :- first_failure(_,R).
verdict("ANSWER_LOCAL",null,W,A) :- not failure(_,_), chosen_path(_,_,_,_,A,P,_), active(P), wire_agent(P,W).
verdict("ANSWER_AFTER_HANDOFF",null,W,A) :- not failure(_,_), chosen_path(_,_,_,_,A,P,_), active(X), X != P, reachable(X,P), wire_agent(P,W).
#show verdict/4.
