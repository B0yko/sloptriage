# pk_header_join() allocates no room for the terminating zero

parsekit 1.2.0. In lines 145-177 of src/header.c the joined value is built
in a buffer of exactly `total` bytes:

```c
  total += (n - 1) * 2;
  out = malloc(total);
  ...
  out[pos] = '\0';
```

The final store is one byte past the allocation when the header repeats.

Reproduce with:

```sh
parsekit header "$(printf 'Accept: a\r\nAccept: b\r\n')"
```
