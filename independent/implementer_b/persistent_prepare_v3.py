from pathlib import Path
p=Path('.')
s=(p/'persistent_policy_v2.py').read_text()
old='''def _query_program(source, dynamic, *, facts_only=False):
    nodes = []
'''
new='''def _query_program(source, dynamic, *, facts_only=False):
    if facts_only:
        output = []
        # The pinned loader emits one clingo-rendered ground term plus a period
        # per LF-delimited fact. clingo escapes LF within String symbols; unlike
        # splitlines(), LF-only splitting preserves literal CR in quoted data.
        for line in source.split('\\n'):
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
        return '\\n'.join(output)
    nodes = []
'''
assert old in s
s=s.replace(old,new)
(p/'persistent_policy_v3.py').write_text(s,encoding='utf-8')
for stem in ('benchmark','safety'):
    s=(p/('persistent_'+stem+'_v2.py')).read_text()
    s=s.replace('persistent_policy_v2','persistent_policy_v3').replace('persistent_'+stem+'_v2','persistent_'+stem+'_v3')
    s=s.replace('persistent-v2-', 'persistent-v3-')
    (p/('persistent_'+stem+'_v3.py')).write_text(s,encoding='utf-8')