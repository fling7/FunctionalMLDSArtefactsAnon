"""Bounded clingo multi-shot feasibility probe, independent of admission decisions."""
import hashlib
import json
from pathlib import Path
import clingo
import clingo.ast as ast

ROOT = Path(__file__).resolve().parent
SOURCE = '''item("a"). item("b").
seen(X) :- inp(X), item(X).
missing :- not seen(_).
count(N) :- N = #count { X : seen(X) }.
out("missing",N) :- missing, count(N).
out("present",N) :- not missing, count(N).
#show out/2.
'''
DYNAMIC = {('inp', 1), ('seen', 1), ('missing', 0), ('count', 1), ('out', 2)}


class Namespace(ast.Transformer):
    def visit_SymbolicAtom(self, node):
        symbol = node.symbol
        if symbol.ast_type != ast.ASTType.Function:
            raise ValueError('ordinary atom expected')
        if (symbol.name, len(symbol.arguments)) in DYNAMIC:
            query = ast.Function(symbol.location, 'qid', [], False)
            return node.update(symbol=symbol.update(arguments=list(symbol.arguments) + [query]))
        return node


def transform(source):
    nodes = []
    ast.parse_string(source, nodes.append)
    rules = []
    guard_nodes = []
    ast.parse_string('x :- live(qid).', guard_nodes.append)
    guard = next(node for node in guard_nodes if node.ast_type == ast.ASTType.Rule).body[0]
    for node in nodes:
        if node.ast_type != ast.ASTType.Rule:
            continue
        head = node.head.atom.symbol
        if (head.name, len(head.arguments)) in DYNAMIC:
            transformed = Namespace()(node)
            rules.append(str(transformed.update(body=list(transformed.body) + [guard])))
    return '\n'.join(rules)


def outputs(control):
    found = []
    with control.solve(yield_=True) as handle:
        for model in handle:
            found.append(sorted(str(symbol) for symbol in model.symbols(shown=True)))
    assert len(found) == 1
    return found[0]


def main():
    control = clingo.Control(['--warn=none', '--models=2'])
    control.add('base', [], 'item("a"). item("b"). #show out/3.')
    control.ground([('base', [])])
    rules = transform(SOURCE)
    requests = [[], ['a'], ['a', 'b'], ['unknown'], [], ['b'], ['a'], []] * 3
    rows = []
    for index, values in enumerate(requests, 1):
        query = clingo.Number(index)
        live = clingo.Function('live', [query])
        facts = '\n'.join(str(clingo.Function('inp', [clingo.String(value)])) + '.' for value in values)
        name = 'request_' + str(index)
        control.add(name, ['qid'], '#external live(qid).\n' + rules + '\n' + transform(facts))
        control.ground([(name, [query])])
        try:
            control.assign_external(live, True)
            actual = outputs(control)
            fresh = clingo.Control(['--warn=none', '--models=2'])
            fresh.add('base', [], SOURCE + '\n' + facts)
            fresh.ground([('base', [])])
            expected = outputs(fresh)
            projected = []
            for value in actual:
                symbol = clingo.parse_term(value)
                assert symbol.arguments[-1] == query
                projected.append(str(clingo.Function(symbol.name, list(symbol.arguments[:-1]))))
            assert sorted(projected) == expected
            rows.append({'query': index, 'values': values, 'actual': actual, 'expected': expected, 'equal': True})
        finally:
            control.assign_external(live, False)
            control.release_external(live)
        assert outputs(control) == []
        control.cleanup()
    output = {'status': 'passed', 'query_count': len(rows), 'rows': rows, 'transformed_rules': rules,
              'clingo_version': clingo.__version__, 'source_sha256': hashlib.sha256((ROOT / 'persistent_feasibility.py').read_bytes()).hexdigest(),
              'scope': 'Toy ASP feasibility only, not admission equivalence or WP8 evidence'}
    (ROOT / 'persistent-feasibility.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'passed', 'query_count': len(rows), 'clingo_version': clingo.__version__}), flush=True)


if __name__ == '__main__':
    main()