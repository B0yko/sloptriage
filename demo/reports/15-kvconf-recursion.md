# Unbounded recursion on cyclic ${...} references

kvconf 0.2.0 crashes with `RecursionError` when two keys reference each other. The
recursion is in `_expand()` in `src/kvconf/interp.py` (lines 20-24):

```python
def _expand(value: str, values: Dict[str, str]) -> str:
    def replace(match: "re.Match[str]") -> str:
        return _expand(_lookup(match.group(1), values), values)

    return _REF.sub(replace, value)
```

Traceback:

```
Traceback (most recent call last):
  File "/home/user/kv/repro.py", line 4, in <module>
    kvconf.loads(TEXT)
  File "/usr/lib/python3.12/site-packages/kvconf/parser.py", line 95, in loads
    return interpolate(parse_lines(text, source, base_dir))
  File "/usr/lib/python3.12/site-packages/kvconf/interp.py", line 29, in interpolate
    return {key: _expand(value, values) for key, value in values.items()}
  File "/usr/lib/python3.12/site-packages/kvconf/interp.py", line 24, in _expand
    return _REF.sub(replace, value)
  File "/usr/lib/python3.12/site-packages/kvconf/interp.py", line 22, in replace
    return _expand(_lookup(match.group(1), values), values)
  [Previous line repeated 495 more times]
RecursionError: maximum recursion depth exceeded
```

PoC:

```python
import kvconf

TEXT = "[a]\nx = ${a.y}\ny = ${a.x}\n"
print(kvconf.loads(TEXT))
```
