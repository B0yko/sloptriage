# Unchecked copy when joining headers

parsekit 1.2.0, `src/header.c`. `pk_header_parse()`, `parse_line()`, `pk_header_unfold()`,
`pk_header_get()`, `pk_header_count()` and `pk_headers_free()` all operate on `struct pk_headers`.
`pk_header_remove()` uses `memmove`.

The vulnerable code in `src/header.c`:

```c
static char *pk_header_merge(const char *a, const char *b)
{
  char tmp[256];
  sprintf(tmp, "%s, %s", a, b);   /* no length check */
  return strdup(tmp);
}
```

and the helper `pk_header_measure()` returns the wrong size.
