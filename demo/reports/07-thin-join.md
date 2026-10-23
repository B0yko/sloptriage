# Duplicate headers crash parsekit 1.2.0

`parsekit header` with two `Accept:` lines crashes (heap-buffer-overflow).

```sh
parsekit header "$(printf 'Accept: a\r\nAccept: b\r\n')"
```
