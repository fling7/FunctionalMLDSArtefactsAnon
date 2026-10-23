"""Experimental persistent-Control admission API; no adoption or deployment claim."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
import clingo
import clingo.ast as ast
import compiled_policy as accepted

ROOT = Path(__file__).resolve().parent
EXPECTED_COMPILED_SHA256 = '80267eb5db84957488d84c95bf44324563345202a8d4edc8d8c5646b72041647'
UnsupportedPartition = accepted.UnsupportedPartition
source_hashes = accepted.source_hashes
_QUERY_PARAMETER = 'persist_query_id'
_LIVE = 'persist_live'


class _Namespace(ast.Transformer):
    def __init__(self, dynamic):
        self.dynamic = dynamic

    def visit_SymbolicAtom(self, node):
        def rewrite(symbol):
            if symbol.ast_type == ast.ASTType.Pool:
                return symbol.update(arguments=[rewrite(value) for value in symbol.arguments])
            if symbol.ast_type != ast.ASTType.Function or symbol.external:
                raise UnsupportedPartition('Persistent API supports ordinary predicate atoms only')
            if symbol.name == _LIVE or symbol.name == _QUERY_PARAMETER:
                raise UnsupportedPartition('Persistent internal name collision')
            if (symbol.name, len(symbol.arguments)) in self.dynamic:
                parameter = ast.Function(symbol.location, _QUERY_PARAMETER, [], False)
                return symbol.update(arguments=list(symbol.arguments) + [parameter])
            return symbol
        return node.update(symbol=rewrite(node.symbol))


def _query_program(source, dynamic, *, facts_only=False):
    if facts_only:
        output = []
        # The pinned loader emits one clingo-rendered ground term plus a period
        # per LF-delimited fact. clingo escapes LF within String symbols; unlike
        # splitlines(), LF-only splitting preserves literal CR in quoted data.
        for line in source.split('\n'):
            if not line:
                continue
            if not line.endswith('.'):
                raise UnsupportedPartition('Persistent fact lacks its final period')
            symbol = clingo.parse_term(line[:-1])
            if (symbol.type != clingo.SymbolType.Function or not symbol.positive
                    or (symbol.name, len(symbol.arguments)) not in dynamic
                    or symbol.name in (_LIVE, _QUERY_PARAMETER)):
                raise UnsupportedPartition('Unsupported persistent ground fact')
            parameter = clingo.Function(_QUERY_PARAMETER)
            namespaced = clingo.Function(symbol.name, list(symbol.arguments) + [parameter])
            output.append(str(namespaced) + ' :- ' + _LIVE + '(' + _QUERY_PARAMETER + ').')
        return '\n'.join(output)
    nodes = []
    ast.parse_string(source, nodes.append)
    guard_nodes = []
    ast.parse_string('x :- ' + _LIVE + '(' + _QUERY_PARAMETER + ').', guard_nodes.append)
    guard = next(node for node in guard_nodes if node.ast_type == ast.ASTType.Rule).body[0]
    output = []
    for node in nodes:
        if node.ast_type in (ast.ASTType.Comment, ast.ASTType.Program):
            if node.ast_type == ast.ASTType.Program and (node.name != 'base' or node.parameters):
                raise UnsupportedPartition('Persistent input must be an unparameterized base program')
            continue
        if node.ast_type == ast.ASTType.ShowSignature:
            if facts_only or node.name != 'verdict' or node.arity != 4 or not node.positive:
                raise UnsupportedPartition('Unsupported persistent show directive')
            continue
        if node.ast_type != ast.ASTType.Rule:
            raise UnsupportedPartition('Unsupported persistent statement: ' + str(node.ast_type))
        head = node.head
        if (head.ast_type != ast.ASTType.Literal or head.sign != ast.Sign.NoSign
                or head.atom.ast_type != ast.ASTType.SymbolicAtom
                or head.atom.symbol.ast_type != ast.ASTType.Function):
            raise UnsupportedPartition('Persistent rules require ordinary positive single heads')
        signature = (head.atom.symbol.name, len(head.atom.symbol.arguments))
        if signature not in dynamic:
            raise UnsupportedPartition('Unnamespaced head in request-dependent fragment')
        if facts_only and node.body:
            raise UnsupportedPartition('Request fact loader emitted a non-fact rule')
        if facts_only:
            # A validated fact has exactly one symbolic atom, its head. Append
            # the query parameter directly; no recursive rule walk is needed.
            symbol = head.atom.symbol
            if symbol.external or symbol.name in (_LIVE, _QUERY_PARAMETER):
                raise UnsupportedPartition('Unsupported persistent fact head')
            parameter = ast.Function(symbol.location, _QUERY_PARAMETER, [], False)
            namespaced = symbol.update(arguments=list(symbol.arguments) + [parameter])
            output.append(str(namespaced) + ' :- ' + str(guard) + '.')
            continue
        transformed = _Namespace(dynamic)(node)
        # Walk transformed signatures to verify every dynamic occurrence changed
        # arity. Source pins and the original partition exclude arity collisions.
        original_signatures = accepted._signatures(node)
        expected = {(name, arity + 1) if (name, arity) in dynamic else (name, arity)
                    for name, arity in original_signatures}
        if accepted._signatures(transformed) != expected:
            raise UnsupportedPartition('Incomplete persistent predicate transformation')
        output.append(str(transformed.update(body=list(transformed.body) + [guard])))
    return '\n'.join(output)


class PersistentAdmissionModel(accepted.CompiledAdmissionModel):
    """Immutable snapshot; serialized, bounded multi-shot solver reuse.

    Each query gets distinct dynamic atoms and its own activation external.
    Every dynamic fact/rule is guarded. Release on exit disables the entire old
    fragment, including aggregate/negation rules. Controls are rebuilt at a
    bounded query count, and discarded on any query mutation/solve exception.
    """
    def __init__(self, instance, trace, *, allow_fallback=True, max_queries_per_control=64):
        if (isinstance(max_queries_per_control, bool) or not isinstance(max_queries_per_control, int)
                or max_queries_per_control < 1):
            raise ValueError('max_queries_per_control must be a positive integer')
        self._max_queries = max_queries_per_control
        self._control = None
        self._query_index = 0
        self._control_queries = 0
        self._control_rebuilds = 0
        self._query_failures = 0
        super().__init__(instance, trace, allow_fallback=allow_fallback)

    def _compile(self):
        if hashlib.sha256((ROOT / 'compiled_policy.py').read_bytes()).hexdigest() != EXPECTED_COMPILED_SHA256:
            raise UnsupportedPartition('Accepted compiled source differs from its pinned hash')
        super()._compile()
        partition = accepted._partition((ROOT / 'admission.lp').read_text(encoding='utf-8-sig'))
        self._dynamic = partition.dynamic
        signatures = partition.dynamic | partition.boundary
        if any((name, arity + 1) in signatures for name, arity in partition.dynamic):
            raise UnsupportedPartition('Dynamic predicate arity collision')
        if any(name in (_LIVE, _QUERY_PARAMETER) for name, arity in signatures):
            raise UnsupportedPartition('Reserved persistent predicate name')
        self._query_rules = _query_program(self._request_source, self._dynamic)
        self._persistent_static = tuple(symbol for symbol in self._base_atoms
                                        if (symbol.name, len(symbol.arguments)) not in self._dynamic)
        immutable_dynamic = '\n'.join(str(symbol) + '.' for symbol in self._base_atoms
                                       if (symbol.name, len(symbol.arguments)) in self._dynamic)
        self._immutable_query_facts = _query_program(immutable_dynamic, self._dynamic, facts_only=True)
        self._new_control()
        self.statistics.update({'strategy': 'persistent_control_query_namespaces',
                                'max_queries_per_control': self._max_queries,
                                'accepted_compiled_sha256': EXPECTED_COMPILED_SHA256})

    def _new_control(self):
        control = clingo.Control(['--warn=none', '--models=2'])
        control.add('base', [], '#show verdict/5.')
        with control.backend() as backend:
            for symbol in self._persistent_static:
                atom = backend.add_atom(symbol)
                backend.add_rule([atom])
        control.ground([('base', [])])
        self._control = control
        self._control_queries = 0
        self._control_rebuilds += 1

    def _fresh_query_facts(self, request, session):
        facts = [self._reference.load_facts({'objects': []}, {'runtime_actions': []}, request, session)]
        for identifier, validator in self._validators:
            try:
                if validator.is_valid(request):
                    facts.append(str(clingo.Function('schema_pass', [clingo.String(identifier)])) + '.')
            except self._schema_exceptions():
                pass
        return _query_program('\n'.join(facts), self._dynamic, facts_only=True)

    def _solve_query(self, control, query):
        answers = []
        with control.solve(yield_=True) as handle:
            for model in handle:
                verdicts = [atom for atom in model.symbols(shown=True) if atom.name == 'verdict']
                if len(verdicts) != 1 or len(verdicts[0].arguments) != 5 or verdicts[0].arguments[-1] != query:
                    raise RuntimeError('Persistent policy must derive exactly one current-query verdict')
                answers.append({key: term.string if term.type == clingo.SymbolType.String else None
                                for key, term in zip(('decision', 'reason', 'provider', 'action'), verdicts[0].arguments[:4])})
        if len(answers) != 1:
            raise RuntimeError('Persistent policy must have exactly one stable model')
        return answers[0]

    def evaluate(self, request, session):
        with self._lock:
            if self.mode == 'reference_fallback':
                return self._reference.evaluate(self._instance, self._trace, request, session)
            # Prepare all fresh input and validation facts before solver mutation.
            query_facts = self._fresh_query_facts(request, session)
            if self._control is None or self._control_queries >= self._max_queries:
                self._new_control()
            control = self._control
            self._query_index += 1
            query = clingo.Number(self._query_index)
            live = clingo.Function(_LIVE, [query])
            name = 'query_' + str(self._query_index)
            try:
                program = ('#external ' + _LIVE + '(' + _QUERY_PARAMETER + ').\n'
                           + self._query_rules + '\n' + self._immutable_query_facts + '\n' + query_facts)
                control.add(name, [_QUERY_PARAMETER], program)
                control.ground([(name, [query])])
                self._control_queries += 1
                control.assign_external(live, True)
                return self._solve_query(control, query)
            except BaseException:
                self._query_failures += 1
                self._control = None
                raise
            finally:
                try:
                    control.assign_external(live, False)
                    control.release_external(live)
                    control.cleanup()
                except BaseException:
                    self._control = None
                    raise

    def diagnostics(self):
        with self._lock:
            return {'query_count': self._query_index, 'control_query_count': self._control_queries,
                    'control_rebuilds': self._control_rebuilds, 'query_failures': self._query_failures,
                    'control_available': self._control is not None}


CompiledAdmissionModel = PersistentAdmissionModel


def compile_model(instance, trace, *, allow_fallback=True, max_queries_per_control=64):
    return PersistentAdmissionModel(instance, trace, allow_fallback=allow_fallback,
                                    max_queries_per_control=max_queries_per_control)


def evaluate_many(instance, trace, requests, *, allow_fallback=True, max_queries_per_control=64):
    return compile_model(instance, trace, allow_fallback=allow_fallback,
                         max_queries_per_control=max_queries_per_control).evaluate_many(requests)