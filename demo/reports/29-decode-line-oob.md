# pk_percent_decode reads past the input

parsekit 1.1.0, `src/util.c:172`: the decoder reads two bytes after `%` without
checking the remaining length. Combined with `src/buf.c:172` this
corrupts the heap.
