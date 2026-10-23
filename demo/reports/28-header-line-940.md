# Header value copied without bounds check

In parsekit 1.2.0, line 893 of `src/header.c` copies the header value into a stack
buffer. Also see `src/util.c:237`.
