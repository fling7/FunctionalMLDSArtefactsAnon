from pathlib import Path
p=Path('.')
s=(p/'persistent_policy.py').read_text()
s=s.replace("UnsupportedPartition = accepted.UnsupportedPartition", "UnsupportedPartition = accepted.UnsupportedPartition\nsource_hashes = accepted.source_hashes")
old="""        transformed = _Namespace(dynamic)(node)
        # Walk transformed signatures to verify every dynamic occurrence changed
"""
new="""        if facts_only:
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
"""
assert old in s
s=s.replace(old,new)
(p/'persistent_policy_v2.py').write_text(s,encoding='utf-8')
for stem in ('benchmark','safety'):
    s=(p/('persistent_'+stem+'.py')).read_text()
    s=s.replace('import persistent_policy as', 'import persistent_policy_v2 as')
    s=s.replace("'persistent_policy.py'", "'persistent_policy_v2.py'")
    s=s.replace("'persistent_"+stem+".py'", "'persistent_"+stem+"_v2.py'")
    s=s.replace('persistent-timing-', 'persistent-v2-timing-').replace("'persistent-safety.json'", "'persistent-v2-safety.json'")
    (p/('persistent_'+stem+'_v2.py')).write_text(s,encoding='utf-8')