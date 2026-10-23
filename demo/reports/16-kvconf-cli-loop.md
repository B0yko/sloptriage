# kvconf CLI crashes on a self-referencing key

Version: kvconf 0.2.0

A configuration line that refers to itself, `name = ${name}`, makes `kvconf` die with
a RecursionError traceback instead of an error message. `load()` calls `loads()`
(src/kvconf/parser.py:95), which expands references in `_expand()` without a depth limit
(src/kvconf/interp.py:22).

```sh
printf 'name = ${name}\n' > loop.conf
kvconf loop.conf
```
