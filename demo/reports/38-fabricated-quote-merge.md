# sprintf overflow when merging headers

The vulnerable code in `src/header.c`:

```c
static char *pk_header_merge(const char *a, const char *b)
{
  char tmp[256];
  sprintf(tmp, "%s, %s", a, b);   /* no length check */
  return strdup(tmp);
}
```

Two long header values overflow `tmp`.
