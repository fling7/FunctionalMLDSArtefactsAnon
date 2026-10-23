publication_error(persist_query_id) :- bad_top(_,persist_query_id); persist_live(persist_query_id).
publication_error(persist_query_id) :- bad_record(_); persist_live(persist_query_id).
publication_error(persist_query_id) :- obj(N,I,_); obj(M,I,_); N != M; persist_live(persist_query_id).
digest_matches(persist_query_id) :- digest("request",D,persist_query_id); digest("session",D,persist_query_id); digest_shape("request",persist_query_id); digest_shape("session",persist_query_id); persist_live(persist_query_id).
failure(10,"E_STALE_DIGEST",persist_query_id) :- not digest_matches(persist_query_id); persist_live(persist_query_id).
selection_invalid(persist_query_id) :- field("request","interaction_mode","non_deictic",persist_query_id); persist_live(persist_query_id).
selection_invalid(persist_query_id) :- not field_type("request","spatial_context","object",persist_query_id); persist_live(persist_query_id).
selection_invalid(persist_query_id) :- not field("spatial","state","resolved",persist_query_id); persist_live(persist_query_id).
selection_invalid(persist_query_id) :- field("spatial","ambiguous",true,persist_query_id); persist_live(persist_query_id).
selection_invalid(persist_query_id) :- field("spatial","ambiguity",true,persist_query_id); persist_live(persist_query_id).
selection_invalid(persist_query_id) :- truthy_ambiguity_member("ambiguous",persist_query_id); persist_live(persist_query_id).
selection_invalid(persist_query_id) :- truthy_ambiguity_member("is_ambiguous",persist_query_id); persist_live(persist_query_id).
selection_invalid(persist_query_id) :- identity_key(K); field_type("spatial",K,T,persist_query_id); T != "string"; persist_live(persist_query_id).
selection_invalid(persist_query_id) :- field_type("spatial","candidate_entity_ids",T,persist_query_id); T != "array"; persist_live(persist_query_id).
selection_invalid(persist_query_id) :- candidate_type(_,T,persist_query_id); T != "string"; persist_live(persist_query_id).
selection_invalid(persist_query_id) :- field_type("spatial","candidate_entity_ids","array",persist_query_id); 1 != #count { N,T: candidate(N,T,persist_query_id) }; persist_live(persist_query_id).
identity_present(K,persist_query_id) :- identity_key(K); field("spatial",K,_,persist_query_id); persist_live(persist_query_id).
identity_resolution("entity_id",T,persist_query_id) :- field("spatial","entity_id",T,persist_query_id); scene(T); persist_live(persist_query_id).
identity_resolution(K,T,persist_query_id) :- K = "source_object_id"; field("spatial",K,W,persist_query_id); wire_target(T,W); persist_live(persist_query_id).
identity_resolution(K,T,persist_query_id) :- K = "source_id"; field("spatial",K,W,persist_query_id); wire_target(T,W); persist_live(persist_query_id).
identity_unknown(persist_query_id) :- not identity_present(_,persist_query_id); persist_live(persist_query_id).
identity_unknown(persist_query_id) :- identity_present(K,persist_query_id); 1 != #count { T: identity_resolution(K,T,persist_query_id) }; persist_live(persist_query_id).
identity_mismatch(persist_query_id) :- identity_resolution(K,T,persist_query_id); identity_resolution(J,U,persist_query_id); K != J; T != U; persist_live(persist_query_id).
selected_target(T,persist_query_id) :- identity_resolution(_,T,persist_query_id); not identity_unknown(persist_query_id); not identity_mismatch(persist_query_id); persist_live(persist_query_id).
selection_invalid(persist_query_id) :- selected_target(T,persist_query_id); candidate(_,U,persist_query_id); T != U; persist_live(persist_query_id).
failure(20,"E_SELECTION_STATE",persist_query_id) :- selection_invalid(persist_query_id); persist_live(persist_query_id).
failure(21,"E_UNKNOWN_ENTITY",persist_query_id) :- identity_unknown(persist_query_id); persist_live(persist_query_id).
failure(22,"E_ID_MISMATCH",persist_query_id) :- identity_mismatch(persist_query_id); persist_live(persist_query_id).
active_candidate(A,persist_query_id) :- field("request","active_agent_id",W,persist_query_id); wire_agent(A,W); persist_live(persist_query_id).
active(A,persist_query_id) :- active_candidate(A,persist_query_id); 1 = #count { B: active_candidate(B,persist_query_id) }; persist_live(persist_query_id).
failure(30,"E_ACTIVE_AGENT_UNKNOWN",persist_query_id) :- 1 != #count { A: active_candidate(A,persist_query_id) }; persist_live(persist_query_id).
strict_matches(persist_query_id) :- field("request","active_agent_id",W,persist_query_id); field("session","active_agent_id",W,persist_query_id); persist_live(persist_query_id).
failure(31,"E_ACTIVE_AGENT_MISMATCH",persist_query_id) :- field("session","active_agent_mode","server_strict",persist_query_id); not strict_matches(persist_query_id); persist_live(persist_query_id).
failure(40,"E_UNOWNED",persist_query_id) :- selected_target(T,persist_query_id); 0 = #count { A: owner(T,A) }; persist_live(persist_query_id).
failure(41,"E_AMBIGUOUS_OWNER",persist_query_id) :- selected_target(T,persist_query_id); 1 < #count { A: owner(T,A) }; persist_live(persist_query_id).
failure(42,"E_NO_HANDOFF_PATH",persist_query_id) :- selected_target(T,persist_query_id); provider(T,P); active(A,persist_query_id); not reachable(A,P); persist_live(persist_query_id).
chosen_path(S,U,C,B,A,P,T,persist_query_id) :- selected_target(T,persist_query_id); provider(T,P); native_path(S,U,C,B,A,P,T); persist_live(persist_query_id).
path_ambiguous(persist_query_id) :- 1 < #count { S,U,C,B,A,P,T: chosen_path(S,U,C,B,A,P,T,persist_query_id) }; persist_live(persist_query_id).
path_ambiguous(persist_query_id) :- chosen_path(_,U,_,_,_,_,_,persist_query_id); 1 < #count { N,P: r(U,"provider",N,P) }; persist_live(persist_query_id).
path_ambiguous(persist_query_id) :- chosen_path(_,U,_,_,_,_,_,persist_query_id); 1 < #count { N,C: r(U,"typeRef",N,C) }; persist_live(persist_query_id).
path_ambiguous(persist_query_id) :- chosen_path(_,_,_,B,_,_,_,persist_query_id); 1 < #count { N,C: r(B,"capability",N,C) }; persist_live(persist_query_id).
path_broken(persist_query_id) :- chosen_path(_,_,C,_,_,P,_,persist_query_id); not r(P,"providedCapability",_,C); persist_live(persist_query_id).
path_broken(persist_query_id) :- chosen_path(_,_,_,_,_,P,_,persist_query_id); not wire_agent(P,_); persist_live(persist_query_id).
projection(R,S,U,C,B,A,P,T,persist_query_id) :- chosen_path(S,U,C,B,A,P,T,persist_query_id); tv(R,"action_kind","chat"); tv(R,"scenario_step_id",S); tv(R,"capability_use_id",U); tv(R,"capability_id",C); tv(R,"provider_entity_id",P); tv(R,"runtime_binding_id",B); tv(R,"runtime_action_id",A); trace_targets_present(R); not trace_targets_differ(R,U); persist_live(persist_query_id).
path_ambiguous(persist_query_id) :- chosen_path(S,U,C,B,A,P,T,persist_query_id); 1 < #count { R: projection(R,S,U,C,B,A,P,T,persist_query_id) }; persist_live(persist_query_id).
path_broken(persist_query_id) :- chosen_path(S,U,C,B,A,P,T,persist_query_id); 0 = #count { R: projection(R,S,U,C,B,A,P,T,persist_query_id) }; persist_live(persist_query_id).
failure(50,"E_ACTION_AMBIGUOUS",persist_query_id) :- path_ambiguous(persist_query_id); persist_live(persist_query_id).
failure(51,"E_NO_DECLARED_ACTION",persist_query_id) :- selected_target(T,persist_query_id); provider(T,_); not chosen_path(_,_,_,_,_,_,T,persist_query_id); persist_live(persist_query_id).
failure(51,"E_NO_DECLARED_ACTION",persist_query_id) :- path_broken(persist_query_id); persist_live(persist_query_id).
valid_action_schema(A,persist_query_id) :- typed(A,"RuntimeAction"); 1 = #count { N,I: r(A,"inputSchema",N,I) }; r(A,"inputSchema",_,I); typed(I,"SchemaReference"); v(I,"uri","json"); schema_pass(I,persist_query_id); persist_live(persist_query_id).
failure(60,"E_SCHEMA",persist_query_id) :- chosen_path(_,_,_,_,A,_,_,persist_query_id); not valid_action_schema(A,persist_query_id); persist_live(persist_query_id).
failure(0,"E_PUBLICATION_INCONSISTENT",persist_query_id) :- publication_error(persist_query_id); persist_live(persist_query_id).
earlier(N,persist_query_id) :- failure(N,_,persist_query_id); failure(M,_,persist_query_id); M < N; persist_live(persist_query_id).
first_failure(N,R,persist_query_id) :- failure(N,R,persist_query_id); not earlier(N,persist_query_id); persist_live(persist_query_id).
verdict("REJECT",R,null,null,persist_query_id) :- first_failure(_,R,persist_query_id); persist_live(persist_query_id).
verdict("ANSWER_LOCAL",null,W,A,persist_query_id) :- not failure(_,_,persist_query_id); chosen_path(_,_,_,_,A,P,_,persist_query_id); active(P,persist_query_id); wire_agent(P,W); persist_live(persist_query_id).
verdict("ANSWER_AFTER_HANDOFF",null,W,A,persist_query_id) :- not failure(_,_,persist_query_id); chosen_path(_,_,_,_,A,P,_,persist_query_id); active(X,persist_query_id); X != P; reachable(X,P); wire_agent(P,W); persist_live(persist_query_id).