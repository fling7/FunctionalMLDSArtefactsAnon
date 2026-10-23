"""Optional immutable-model compilation for the unchanged independent ASP policy.

compile_model(instance, trace).evaluate(request, session) returns the same four
verdict fields as policy_adapter.evaluate. evaluate_many accepts (request, session)
pairs. The original adapter and admission.lp are never modified.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
import time

import clingo
import clingo.ast as ast

ROOT = Path(__file__).resolve().parent
EXPECTED_REFERENCE_HASHES = {
    'policy_adapter.py': 'cfa3af7ed9446eefb8b947b889f52d2841db73e3920a18133d37c57c7071dd12',
    'admission.lp': '149e76e157415465f925af7063c1796ce682f4228a5adff4347cb7ff08888fea',
}
_DYNAMIC_INPUTS = frozenset({
    ('bad_top', 1), ('field', 3), ('field_type', 3), ('candidate', 2),
    ('candidate_type', 2), ('ambiguity_member', 2),
    ('truthy_ambiguity_member', 1), ('digest', 2), ('digest_shape', 1),
    ('schema_pass', 1), ('schema_error', 1),
})


class UnsupportedPartition(RuntimeError):
    """The original source cannot be conservatively partitioned."""


def _reference_module():
    spec = importlib.util.spec_from_file_location('_independent_b_reference', ROOT / 'policy_adapter.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in EXPECTED_REFERENCE_HASHES}


def _signatures(node):
    """Walk every AST child, including negation and aggregate conditions."""
    result = set()
    def visit(item):
        if not isinstance(item, ast.AST):
            raise UnsupportedPartition('Non-AST item in the policy AST')
        if item.ast_type == ast.ASTType.SymbolicAtom:
            def predicate_symbol(symbol):
                if symbol.ast_type == ast.ASTType.Pool:
                    for alternative in symbol.arguments:
                        predicate_symbol(alternative)
                elif symbol.ast_type == ast.ASTType.Function and not symbol.external:
                    result.add((symbol.name, len(symbol.arguments)))
                else:
                    raise UnsupportedPartition('Unsupported nonordinary predicate atom')
            predicate_symbol(item.symbol)
        for key in item.child_keys:
            child = getattr(item, key)
            if isinstance(child, ast.AST):
                visit(child)
            elif child is not None:
                try:
                    children = iter(child)
                except TypeError as exc:
                    raise UnsupportedPartition('Unrecognized AST child shape') from exc
                for member in children:
                    visit(member)
    visit(node)
    return result


@dataclass(frozen=True)
class Partition:
    static_source: str
    request_source: str
    dynamic: frozenset
    boundary: frozenset
    static_rule_count: int
    request_rule_count: int


def _partition(source):
    nodes = []
    ast.parse_string(source, nodes.append)
    rules, shows = [], []
    for node in nodes:
        if node.ast_type == ast.ASTType.Comment:
            continue
        if node.ast_type == ast.ASTType.Program:
            if node.name != 'base' or node.parameters:
                raise UnsupportedPartition('Only an unparameterized base program is supported')
            continue
        if node.ast_type == ast.ASTType.ShowSignature:
            shows.append(str(node))
            continue
        if node.ast_type != ast.ASTType.Rule:
            raise UnsupportedPartition('Unsupported policy statement: ' + str(node.ast_type))
        head = node.head
        if (head.ast_type != ast.ASTType.Literal or head.sign != ast.Sign.NoSign
                or head.atom.ast_type != ast.ASTType.SymbolicAtom):
            raise UnsupportedPartition('Only ordinary positive single-predicate heads are supported')
        head_signatures = _signatures(head)
        if len(head_signatures) != 1:
            raise UnsupportedPartition('Rule does not have exactly one predicate signature')
        body_signatures = set()
        for body_item in node.body:
            body_signatures.update(_signatures(body_item))
        rules.append((node, next(iter(head_signatures)), body_signatures))

    # If any definition of a predicate depends on request data, EVERY definition
    # of that predicate is retained for each request. Sign and aggregate nesting
    # do not weaken a dependency.
    dynamic = set(_DYNAMIC_INPUTS)
    while True:
        additions = {head for _, head, body in rules if body & dynamic} - dynamic
        if not additions:
            break
        dynamic.update(additions)
    static_rules = [str(node) for node, head, _ in rules if head not in dynamic]
    request_rules = [str(node) for node, head, _ in rules if head in dynamic]
    boundary = set()
    for _, head, body in rules:
        if head not in dynamic and body & dynamic:
            raise UnsupportedPartition('A static rule still depends on dynamic predicates')
        if head in dynamic:
            boundary.update(body - dynamic)
    if len(static_rules) + len(request_rules) != len(rules):
        raise UnsupportedPartition('Incomplete rule partition')
    return Partition('\n'.join(static_rules), '\n'.join(request_rules + shows),
                     frozenset(dynamic), frozenset(boundary),
                     len(static_rules), len(request_rules))


def _unique_atoms(control):
    answers = []
    with control.solve(yield_=True) as handle:
        for model in handle:
            answers.append(tuple(model.symbols(atoms=True)))
    if len(answers) != 1:
        raise UnsupportedPartition('The immutable fragment does not have one stable model')
    return answers[0]


def _verdict(control):
    answers = []
    with control.solve(yield_=True) as handle:
        for model in handle:
            verdicts = [atom for atom in model.symbols(shown=True) if atom.name == 'verdict']
            if len(verdicts) != 1:
                raise RuntimeError('Admission policy must derive exactly one verdict')
            answers.append({key: term.string if term.type == clingo.SymbolType.String else None
                            for key, term in zip(('decision', 'reason', 'provider', 'action'),
                                                 verdicts[0].arguments)})
    if len(answers) != 1:
        raise RuntimeError('Admission policy must have exactly one stable model')
    return answers[0]


class CompiledAdmissionModel:
    """A private snapshot of one instance and trace, safe for repeated requests.

    This is partial grounding reuse: immutable native semantics are solved once
    in ASP. Each request is solved in a fresh clingo.Control using their boundary
    facts and the mechanically unchanged request-dependent rules. No live solver
    or request-dependent atom survives a call. Calls on one object are serialized
    so its cached JSON Schema validators are never used concurrently.
    """
    def __init__(self, instance, trace, *, allow_fallback=True):
        started = time.perf_counter()
        self._instance, self._trace = deepcopy(instance), deepcopy(trace)
        self._reference = _reference_module()
        self._lock = threading.RLock()
        self.mode = 'compiled'
        self.fallback_reason = None
        self.reference_hashes = source_hashes()
        self.statistics = {}
        try:
            if self.reference_hashes != EXPECTED_REFERENCE_HASHES:
                raise UnsupportedPartition('Original reference source differs from the audited byte hashes')
            self._compile()
        except UnsupportedPartition as exc:
            if not allow_fallback:
                raise
            self.mode = 'reference_fallback'
            self.fallback_reason = str(exc)
        self.compile_seconds = time.perf_counter() - started

    def _compile(self):
        reference = self._reference
        partition = _partition((ROOT / 'admission.lp').read_text(encoding='utf-8-sig'))
        static_facts, immutable_dynamic_facts = [], []
        # Use the unchanged adapter to parse model/trace facts once. Placeholder
        # request/session facts and their schema-validation results are discarded.
        # Their predicates are conservatively dynamic in the partition.
        for line in reference.load_facts(self._instance, self._trace, None, None).splitlines():
            symbol = clingo.parse_term(line[:-1])
            signature = (symbol.name, len(symbol.arguments))
            if signature in _DYNAMIC_INPUTS:
                if (symbol.name == 'bad_top'
                        and symbol.arguments[0].string not in ('request', 'session')):
                    immutable_dynamic_facts.append(line)
            else:
                static_facts.append(line)
        control = clingo.Control(['--warn=none', '--models=2'])
        control.add('base', [], partition.static_source + '\n' + '\n'.join(static_facts))
        control.ground([('base', [])])
        static_atoms = _unique_atoms(control)
        boundary_atoms = [atom for atom in static_atoms
                          if (atom.name, len(atom.arguments)) in partition.boundary]
        self._base_atoms = tuple(boundary_atoms) + tuple(
            clingo.parse_term(line[:-1]) for line in immutable_dynamic_facts)
        self._request_source = partition.request_source
        self._validators = []
        objects = self._instance.get('objects') if isinstance(self._instance, dict) else None
        for record in objects if isinstance(objects, list) else []:
            if (not isinstance(record, dict) or not isinstance(record.get('id'), str)
                    or not record['id'] or record.get('type') != 'SchemaReference'):
                continue
            try:
                schema = json.loads(record['text'])
                if isinstance(schema, dict) and '$schema' in schema:
                    cls = reference.jsonschema.validators.validator_for(schema, default=None)
                    if cls is None:
                        raise ValueError('Unsupported explicitly declared schema dialect')
                else:
                    cls = reference.jsonschema.Draft202012Validator
                cls.check_schema(schema)
                validator = cls(schema, registry=reference.Registry(retrieve=reference._deny_retrieval))
                self._validators.append((record['id'], validator))
            except self._schema_exceptions():
                pass
        self.statistics = {
            'static_rule_count': partition.static_rule_count,
            'request_rule_count': partition.request_rule_count,
            'static_input_fact_count': len(static_facts),
            'static_true_atom_count': len(static_atoms),
            'boundary_fact_count': len(boundary_atoms),
            'schema_validator_count': len(self._validators),
            'dynamic_predicates': [f'{n}/{a}' for n, a in sorted(partition.dynamic)],
            'boundary_predicates': [f'{n}/{a}' for n, a in sorted(partition.boundary)],
        }

    def _schema_exceptions(self):
        ref = self._reference
        return (KeyError, TypeError, ValueError, ref.jsonschema.exceptions.SchemaError,
                ref.jsonschema.exceptions.ValidationError,
                ref.jsonschema.exceptions._WrappedReferencingError, ref.NoSuchResource)

    def evaluate(self, request, session):
        with self._lock:
            if self.mode == 'reference_fallback':
                return self._reference.evaluate(self._instance, self._trace, request, session)
            dynamic_facts = [self._reference.load_facts({'objects': []},
                                                       {'runtime_actions': []}, request, session)]
            for identifier, validator in self._validators:
                try:
                    if validator.is_valid(request):
                        dynamic_facts.append(str(clingo.Function('schema_pass',
                                                   [clingo.String(identifier)])) + '.')
                except self._schema_exceptions():
                    # schema_error is not a body predicate in the audited source;
                    # absence of schema_pass has exactly the original effect.
                    pass
            control = clingo.Control(['--warn=none', '--models=2'])
            control.add('base', [], self._request_source + '\n' + '\n'.join(dynamic_facts))
            # Backend symbols become grounder domains, as ordinary ground facts
            # would. Reuse immutable clingo.Symbol objects instead of reparsing
            # thousands of static fact strings for every request.
            with control.backend() as backend:
                for symbol in self._base_atoms:
                    atom = backend.add_atom(symbol)
                    backend.add_rule([atom])
            control.ground([('base', [])])
            return _verdict(control)

    def evaluate_many(self, requests):
        """Return verdicts in input order for an iterable of (request, session)."""
        return [self.evaluate(request, session) for request, session in requests]


def compile_model(instance, trace, *, allow_fallback=True):
    return CompiledAdmissionModel(instance, trace, allow_fallback=allow_fallback)


def evaluate_many(instance, trace, requests, *, allow_fallback=True):
    """Convenience batch API; retain compile_model's result across batches."""
    return compile_model(instance, trace, allow_fallback=allow_fallback).evaluate_many(requests)
