# Crash with repeated header names

Running the header parser on a block where a field name repeats crashes with a
heap-buffer-overflow in `pk_header_join()` (`src/header.c`). Single headers are fine.

```sh
printf 'Host: example.com\r\nX-Trace: alpha\r\nX-Trace: beta\r\n\r\n' > dup.txt
parsekit header --file dup.txt
```
