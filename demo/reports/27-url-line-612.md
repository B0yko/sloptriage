# Out-of-bounds read in the URL parser

parsekit 1.2.0, `src/url.c:595` reads `host[len]` without checking `len`, and the same
pattern appears at line 636 of src/url.c.
