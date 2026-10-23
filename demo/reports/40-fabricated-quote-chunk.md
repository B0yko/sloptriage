# Integer overflow in chunk size parsing

The code in `src/util.c`:

```c
size_t pk_decode_chunk_size(const char *p)
{
  size_t n = 0;
  while(isxdigit(*p))
    n = n * 16 + hexval(*p++);
  return n;  // integer overflow not checked
}
```
