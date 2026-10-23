# Unsafe concatenation at src/header.c:144

parsekit 1.2.0. The code at `src/header.c:144` and `src/url.c:224` concatenates
attacker-controlled strings. Please fix urgently.
