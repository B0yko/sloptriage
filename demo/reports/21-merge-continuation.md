# Critical heap overflow in pk_header_merge_continuation()

parsekit 1.2.0 has a critical vulnerability in `pk_header_merge_continuation()` which calls
`pk_buf_grow_exact()` without checking the size returned by `pk_header_measure()`. An attacker
sending folded headers can overwrite the heap and achieve remote code execution.

The problem is in `src/header.c`. The fix is to validate the length before `pk_buf_grow_exact()`.
