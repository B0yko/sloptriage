# Freed path pointer used in pk_url_normalize

In parsekit 1.2.0 the crash happens in function pk_url_normalize at src/url.c:241, after
`free(u->path)` on line 239 of src/url.c. `remove_dot_segments()` returns a new buffer and
the old one is released before `base` is checked.

```sh
parsekit normalize 'http://example.com/a/./b/../c'
```
