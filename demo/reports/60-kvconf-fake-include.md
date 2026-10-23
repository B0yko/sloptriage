# Include path traversal in kvconf

kvconf 0.2.0 resolves `@include` paths with `_resolve_include()` and `_safe_join()` in
`src/kvconf/includes.py`, which do not block `..`.
