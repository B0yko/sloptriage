# kvconf 1.3.1 include traversal

kvconf 1.3.1 allows `@include ../../etc/passwd`. The check in `_resolve_include()` is missing.
