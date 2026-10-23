# RecursionError in interpolate()

`kvconf.loads()` never returns for `greeting = hello ${greeting}`; it raises RecursionError
from `_expand()` / `replace()` in interp.py.

```python
import kvconf

print(kvconf.loads("greeting = hello ${greeting}\n"))
```
