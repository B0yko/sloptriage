# XXE in parsekit

parsekit 1.2.0 is vulnerable to XML external entities: `xmlParseChunk()` is called with
`XML_PARSE_NOENT` in `parser.c`, and `xmlCtxtUseOptions()` does not disable entity loading.
See `include/libxml/parser.h` for the options.
