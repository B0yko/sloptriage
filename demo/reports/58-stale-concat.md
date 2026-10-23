# Overflow in pk_header_concat()

parsekit 1.2.0: `pk_header_concat()` in `src/strutil.c` sizes the buffer incorrectly, and
`pk_header_set_raw()` makes it reachable from user input.

```sh
parsekit header "$(printf 'Host: example.com\r\nAccept: */*\r\n')"
```
