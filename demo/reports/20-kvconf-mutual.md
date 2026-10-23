# Crash: mutually recursive interpolation

kvconf 0.2.0, `src/kvconf/interp.py`, `_expand()` at line 24 and the nested `replace()` at
line 22: there is no cycle detection, so `[a] x = ${a.y}` / `y = ${a.x}` recurses until
Python gives up.

```python
import kvconf

TEXT = "[a]\nx = ${a.y}\ny = ${a.x}\n"
print(kvconf.loads(TEXT))
```
