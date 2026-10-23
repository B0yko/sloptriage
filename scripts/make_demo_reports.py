"""Write the 60 synthetic demo reports and their labels.

Every line number, function span and quoted line in a valid report is read from
the demo sources at the stated version, so valid reports are correct by
construction. Low-quality reports are built to show one or more failure modes.

    uv run python scripts/make_demo_reports.py
"""

from __future__ import annotations

import base64
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from sloptriage.index.defs import definitions, language_for

ROOT = Path(__file__).resolve().parent.parent
PROJ = ROOT / "demo" / "projects"
OUT = ROOT / "demo" / "reports"
rng = random.Random(7)


def src(project: str, version: str, path: str) -> str:
    return (PROJ / project / f"v{version}" / path).read_text()


def line_of(project: str, version: str, path: str, needle: str, nth: int = 1) -> int:
    seen = 0
    for i, line in enumerate(src(project, version, path).splitlines(), 1):
        if needle in line:
            seen += 1
            if seen == nth:
                return i
    raise KeyError(f"{needle!r} not in {project} {version} {path}")


def span(project: str, version: str, path: str, func: str) -> tuple[int, int]:
    text = src(project, version, path).encode()
    lang = language_for(path)
    assert lang
    for d in definitions(lang, text):
        if d.name == func and d.kind in ("function", "method"):
            return d.start, d.end
    raise KeyError(func)


def nlines(project: str, version: str, path: str) -> int:
    return len(src(project, version, path).splitlines())


def lines(project: str, version: str, path: str, a: int, b: int) -> str:
    return "\n".join(src(project, version, path).splitlines()[a - 1 : b])


def addr() -> str:
    return "0x" + "".join(rng.choice("0123456789abcdef") for _ in range(12))


# -- facts about parsekit -----------------------------------------------------------
V = "1.2.0"
JOIN_S, JOIN_E = span("parsekit", V, "src/header.c", "pk_header_join")
JOIN_WRITE = line_of("parsekit", V, "src/header.c", "out[pos] = '\\0';")
JOIN_MALLOC = line_of("parsekit", V, "src/header.c", "out = malloc(total);")
JOIN_TOTAL = line_of("parsekit", V, "src/header.c", "total += (n - 1) * 2;")
CMD_HEADER_CALL = line_of("parsekit", V, "cli/parsekit.c", "value = pk_header_join(&hs, name);")
MAIN_HEADER_FILE = line_of("parsekit", V, "cli/parsekit.c", "rc = cmd_header(data, len);")
MAIN_HEADER_ARG = line_of(
    "parsekit", V, "cli/parsekit.c", "return cmd_header(argv[2], strlen(argv[2]));"
)
NORM_S, NORM_E = span("parsekit", V, "src/url.c", "pk_url_normalize")
NORM_READ = line_of("parsekit", V, "src/url.c", "if(base && base[1] == '\\0')")
NORM_FREE = line_of("parsekit", V, "src/url.c", "free(u->path);", 2)
NORM_STRRCHR = line_of("parsekit", V, "src/url.c", "base = strrchr(u->path, '/');")
URL_PATH_DUP = line_of("parsekit", V, "src/url.c", "u->path = pk_strndup(rest, i);")
STRNDUP_MALLOC = line_of("parsekit", V, "src/util.c", "char *out = malloc(n + 1);")
CMD_URL_NORM = line_of("parsekit", V, "cli/parsekit.c", "rc = pk_url_normalize(&u);")
MAIN_NORM = line_of("parsekit", V, "cli/parsekit.c", "return cmd_url(argv[2], 1);")
UNFOLD_S, UNFOLD_E = span("parsekit", V, "src/header.c", "pk_header_unfold")
PARSE_LINE_S, PARSE_LINE_E = span("parsekit", V, "src/header.c", "parse_line")
URL_PARSE_S, URL_PARSE_E = span("parsekit", V, "src/url.c", "pk_url_parse")
DECODE_S, DECODE_E = span("parsekit", V, "src/util.c", "pk_percent_decode")
HEADER_GET_S, HEADER_GET_E = span("parsekit", V, "src/header.c", "pk_header_get")
BUF_APPEND_S, BUF_APPEND_E = span("parsekit", V, "src/buf.c", "pk_buf_append")
BUF_RESERVE_S, BUF_RESERVE_E = span("parsekit", V, "src/buf.c", "buf_reserve")
HEXVAL_S, HEXVAL_E = span("parsekit", V, "src/util.c", "pk_hexval")
HEADER_LINES = nlines("parsekit", V, "src/header.c")
URL_LINES = nlines("parsekit", V, "src/url.c")
UTIL_LINES = nlines("parsekit", V, "src/util.c")
JOIN_V11_WRITE = line_of("parsekit", "1.1.0", "src/header.c", "out[pos] = '\\0';")
JOIN_V11_MALLOC = line_of("parsekit", "1.1.0", "src/header.c", "out = malloc(total);")
CMD_HEADER_CALL_V11 = line_of(
    "parsekit", "1.1.0", "cli/parsekit.c", "value = pk_header_join(&hs, name);"
)
MAIN_HEADER_FILE_V11 = line_of("parsekit", "1.1.0", "cli/parsekit.c", "rc = cmd_header(data, len);")
COMMENT_LINE = line_of("parsekit", V, "src/header.c", "/* combine all values of a repeated header")
BLANK_LINE_URL = NORM_S - 1  # the blank line before pk_url_normalize

# -- facts about kvconf ---------------------------------------------------------------
KV = "0.2.0"
EXPAND_S, EXPAND_E = span("kvconf", KV, "src/kvconf/interp.py", "_expand")
REPLACE_LINE = line_of(
    "kvconf", KV, "src/kvconf/interp.py", "return _expand(_lookup(match.group(1), values), values)"
)
SUB_LINE = line_of("kvconf", KV, "src/kvconf/interp.py", "return _REF.sub(replace, value)")
INTERP_LINE = line_of("kvconf", KV, "src/kvconf/interp.py", "return {key: _expand(value, values)")
LOOKUP_LINE = line_of("kvconf", KV, "src/kvconf/interp.py", 'if name.startswith("env:"):')
LOADS_LINE = line_of(
    "kvconf", KV, "src/kvconf/parser.py", "return interpolate(parse_lines(text, source, base_dir))"
)
LOAD_LINE = line_of(
    "kvconf",
    KV,
    "src/kvconf/parser.py",
    "return loads(handle.read(), path, os.path.dirname(os.path.abspath(path)))",
)
CLI_LOAD_LINE = line_of("kvconf", KV, "src/kvconf/cli.py", "values = load(args.path)")


# -- building blocks ------------------------------------------------------------------
def asan_overflow(
    prefix: str = "/src/parsekit", version: str = V, pid: int = 4121, cols: bool = True
) -> str:
    write = JOIN_WRITE if version == V else JOIN_V11_WRITE
    malloc = JOIN_MALLOC if version == V else JOIN_V11_MALLOC
    call = CMD_HEADER_CALL if version == V else CMD_HEADER_CALL_V11
    main_line = MAIN_HEADER_FILE if version == V else MAIN_HEADER_FILE_V11
    c = (lambda n: f":{n}") if cols else (lambda n: "")
    a = addr()
    return f"""=={pid}==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502000000{rng.randint(10, 99)} at pc {addr()} bp {addr()} sp {addr()}
WRITE of size 1 at 0x502000000{rng.randint(10, 99)} thread T0
    #0 {addr()} in pk_header_join {prefix}/src/header.c:{write}{c(12)}
    #1 {addr()} in cmd_header {prefix}/cli/parsekit.c:{call}{c(13)}
    #2 {addr()} in main {prefix}/cli/parsekit.c:{main_line}{c(10)}
    #3 {addr()} in __libc_start_call_main csu/../sysdeps/nptl/libc_start_call_main.h:58:16
    #4 {addr()} in __libc_start_main csu/../csu/libc-start.c:392:3
    #5 {a} in _start ({prefix}/build/parsekit+0x2c364)

0x502000000035 is located 0 bytes after 5-byte region [0x502000000030,0x502000000035)
allocated by thread T0 here:
    #0 {addr()} in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:145
    #1 {addr()} in pk_header_join {prefix}/src/header.c:{malloc}{c(9)}
    #2 {addr()} in cmd_header {prefix}/cli/parsekit.c:{call}{c(13)}

SUMMARY: AddressSanitizer: heap-buffer-overflow {prefix}/src/header.c:{write}{c(12)} in pk_header_join"""


def asan_uaf(prefix: str = "/home/dev/parsekit-1.2.0", pid: int = 977, short: bool = False) -> str:
    head = f"""=={pid}==ERROR: AddressSanitizer: heap-use-after-free on address 0x50300000{rng.randint(10, 99)}a at pc {addr()} bp {addr()} sp {addr()}
READ of size 1 at 0x50300000004a thread T0
    #0 {addr()} in pk_url_normalize {prefix}/src/url.c:{NORM_READ}:17
    #1 {addr()} in cmd_url {prefix}/cli/parsekit.c:{CMD_URL_NORM}:10
    #2 {addr()} in main {prefix}/cli/parsekit.c:{MAIN_NORM}:12"""
    if short:
        return (
            head
            + f"\n\nSUMMARY: AddressSanitizer: heap-use-after-free {prefix}/src/url.c:{NORM_READ}:17 in pk_url_normalize"
        )
    return (
        head
        + f"""
    #3 {addr()} in __libc_start_main csu/../csu/libc-start.c:392:3

0x50300000004a is located 10 bytes inside of 21-byte region [0x503000000040,0x503000000055)
freed by thread T0 here:
    #0 {addr()} in free ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:52
    #1 {addr()} in pk_url_normalize {prefix}/src/url.c:{NORM_FREE}:5
    #2 {addr()} in cmd_url {prefix}/cli/parsekit.c:{CMD_URL_NORM}:10

previously allocated by thread T0 here:
    #0 {addr()} in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:69
    #1 {addr()} in pk_strndup {prefix}/src/util.c:{STRNDUP_MALLOC}:15
    #2 {addr()} in pk_url_parse {prefix}/src/url.c:{URL_PATH_DUP}:13

SUMMARY: AddressSanitizer: heap-use-after-free {prefix}/src/url.c:{NORM_READ}:17 in pk_url_normalize"""
    )


def py_traceback(site: str = "/usr/lib/python3.12/site-packages") -> str:
    return f"""Traceback (most recent call last):
  File "/home/user/kv/repro.py", line 4, in <module>
    kvconf.loads(TEXT)
  File "{site}/kvconf/parser.py", line {LOADS_LINE}, in loads
    return interpolate(parse_lines(text, source, base_dir))
  File "{site}/kvconf/interp.py", line {INTERP_LINE}, in interpolate
    return {{key: _expand(value, values) for key, value in values.items()}}
  File "{site}/kvconf/interp.py", line {SUB_LINE}, in _expand
    return _REF.sub(replace, value)
  File "{site}/kvconf/interp.py", line {REPLACE_LINE}, in replace
    return _expand(_lookup(match.group(1), values), values)
  [Previous line repeated 495 more times]
RecursionError: maximum recursion depth exceeded"""


DUP_HEADERS = "Host: example.com\r\nX-Trace: alpha\r\nX-Trace: beta\r\n\r\n"
DUP_B64 = base64.b64encode(DUP_HEADERS.encode()).decode()
DOT_URL = "http://example.com/a/./b/../c"

POC_SH_OVERFLOW = """```sh
printf 'Host: example.com\\r\\nX-Trace: alpha\\r\\nX-Trace: beta\\r\\n\\r\\n' > dup.txt
parsekit header --file dup.txt
```"""
POC_SH_OVERFLOW_ARG = """```sh
parsekit header "$(printf 'Accept: a\\r\\nAccept: b\\r\\n')"
```"""
POC_INPUT_OVERFLOW = f"""Save this as `dup-headers.txt` and run `parsekit header --file dup-headers.txt`:

```base64
{DUP_B64}
```"""
POC_C_OVERFLOW = """```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <parsekit.h>

int main(void)
{
  const char *block = "Set-Cookie: a=1\\r\\nSet-Cookie: b=2\\r\\n\\r\\n";
  struct pk_headers hs;
  char *joined;

  if(pk_header_parse(block, strlen(block), &hs) != PK_OK)
    return 1;
  joined = pk_header_join(&hs, "Set-Cookie");
  printf("%s\\n", joined);
  free(joined);
  pk_headers_free(&hs);
  return 0;
}
```"""
POC_SH_UAF = f"""```sh
parsekit normalize '{DOT_URL}'
```"""
POC_C_UAF = """```c
#include <stdio.h>
#include <stdlib.h>
#include <parsekit.h>

int main(void)
{
  struct pk_url u;
  char *s;

  if(pk_url_parse("https://example.com/docs/./guide/../index.html", &u) != PK_OK)
    return 1;
  pk_url_normalize(&u);
  s = pk_url_to_string(&u);
  puts(s ? s : "(null)");
  free(s);
  pk_url_free(&u);
  return 0;
}
```"""
POC_PY = """```python
import kvconf

TEXT = "[a]\\nx = ${a.y}\\ny = ${a.x}\\n"
print(kvconf.loads(TEXT))
```"""
POC_SH_KV = """```sh
printf 'name = ${name}\\n' > loop.conf
kvconf loop.conf
```"""
POC_PY_SELF = """```python
import kvconf

print(kvconf.loads("greeting = hello ${greeting}\\n"))
```"""

POC_OWN_BUFFER = """```c
#include <stdio.h>
#include <string.h>
#include <parsekit.h>

int main(void)
{
  struct pk_url u;
  char host[8];

  if(pk_url_parse("http://very-long-hostname.example.com/", &u) != PK_OK)
    return 1;
  strcpy(host, u.host);
  printf("%s\\n", host);
  pk_url_free(&u);
  return 0;
}
```"""
POC_OWN_BUFFER_2 = """```c
#include <string.h>
#include <stdlib.h>
#include <parsekit.h>

int main(void)
{
  char *copy = malloc(4);
  const char *value = pk_strerror(PK_ERR_SYNTAX);
  memcpy(copy, value, strlen(value) + 1);
  free(copy);
  return 0;
}
```"""
POC_NO_LIB = """```c
#include <stdlib.h>
#include <string.h>

int main(void)
{
  char *header = malloc(16);
  strcpy(header, "X-Trace: alpha");
  free(header);
  free(header);
  return 0;
}
```"""
POC_NO_LIB_2 = """```c
#include <stdio.h>

int main(void)
{
  int values[4] = {1, 2, 3, 4};
  int i;
  for(i = 0; i <= 4; i++)
    printf("%d\\n", values[i]);
  return 0;
}
```"""
POC_NO_COMPILE = """```c
#include <parsekit.h>

int main(void)
{
  struct pk_headers hs;
  pk_headers_init(&hs);
  pk_header_set_raw(&hs, "X-Trace", 4096);
  return pk_header_merge_continuation(&hs, 0);
}
```"""
POC_NO_COMPILE_2 = """```c
#include <parsekit.h>

int main(void)
{
  pk_url_t *u = pk_url_new();
  pk_url_set_path(u, "/a/../../b");
  return pk_url_resolve_relative(u, NULL);
}
```"""
POC_SH_BENIGN = """```sh
parsekit url 'https://example.com/index.html?q=1'
```"""
POC_SH_BENIGN_2 = """```sh
parsekit header "$(printf 'Host: example.com\\r\\nAccept: */*\\r\\n')"
```"""


@dataclass
class R:
    slug: str
    label: str
    project: str
    version: str | None
    body: str
    modes: list[str] = field(default_factory=list)
    poc: str = "none"
    reproduces: bool = False
    bug: str | None = None
    notes: str = ""


REPORTS: list[R] = []


def add(*args: object, **kw: object) -> None:
    REPORTS.append(R(*args, **kw))  # type: ignore[arg-type]


QUOTE_JOIN = lines("parsekit", V, "src/header.c", JOIN_TOTAL, JOIN_MALLOC + 2)
QUOTE_JOIN_TAIL = lines("parsekit", V, "src/header.c", JOIN_WRITE - 2, JOIN_WRITE)
QUOTE_NORM = lines("parsekit", V, "src/url.c", NORM_STRRCHR - 4, NORM_READ + 1)
QUOTE_EXPAND = lines("kvconf", KV, "src/kvconf/interp.py", EXPAND_S, EXPAND_E)

# ----------------------------------------------------------------------------------
# 20 valid reports
# ----------------------------------------------------------------------------------
add(
    "header-join-overflow",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# Heap buffer overflow in pk_header_join() with repeated headers

## Summary

parsekit 1.2.0 writes one byte past the end of a heap buffer when a header block
contains the same header name twice. `pk_header_join()` in `src/header.c` sizes the
output as the sum of the values plus two bytes per separator, but forgets the
terminating NUL, which it writes at `src/header.c:{JOIN_WRITE}`.

The vulnerable code in `src/header.c`:

```c
{QUOTE_JOIN}
```

## Sanitizer output

```
{asan_overflow()}
```

## Steps to reproduce

{POC_INPUT_OVERFLOW}

## Impact

A one-byte heap overwrite reachable from any input that repeats a header name.
""",
    poc="input",
    reproduces=True,
    bug="heap-buffer-overflow",
    notes="detailed, base64 input PoC, quote and trace",
)

add(
    "join-overflow-cli",
    "valid",
    "parsekit",
    "1.1.0",
    f"""# parsekit header crashes on duplicate header names

Version: parsekit 1.1.0 (also reproduced on 1.2.0)

`parsekit header --file` aborts under AddressSanitizer as soon as one header name
appears twice. The overflow is in `pk_header_join()` (src/header.c:{JOIN_V11_WRITE}), called
from `cmd_header()`.

### Reproduce

{POC_SH_OVERFLOW}

### ASan

```
{asan_overflow(prefix="/build/parsekit-1.1.0", version="1.1.0", pid=31337)}
```
""",
    poc="sh",
    reproduces=True,
    bug="heap-buffer-overflow",
    notes="terse, shell PoC, version 1.1.0",
)

add(
    "join-overflow-api",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# Off-by-one heap write in pk_header_join

**Affected version:** parsekit 1.2.0
**Component:** `src/header.c`, function `pk_header_join()` (lines {JOIN_S}-{JOIN_E})

When more than one header matches, the function allocates `total` bytes at line
{JOIN_MALLOC} and later stores the terminating zero at `out[pos]`, line {JOIN_WRITE}, where
`pos == total`. A caller that only uses the public API hits it:

{POC_C_OVERFLOW}

Compile with `-fsanitize=address` against the installed library and run it; ASan
reports a 1-byte WRITE just after the allocated region in `pk_header_join`.
""",
    poc="c",
    reproduces=True,
    bug="heap-buffer-overflow",
    notes="C API PoC, function span and lines",
)

add(
    "dup-header-crash-noversion",
    "valid",
    "parsekit",
    None,
    f"""# Crash with repeated header names

Running the header parser on a block where a field name repeats crashes with a
heap-buffer-overflow in `pk_header_join()` (`src/header.c`). Single headers are fine.

{POC_SH_OVERFLOW}
""",
    poc="sh",
    reproduces=True,
    bug="heap-buffer-overflow",
    notes="no version, few references",
)

add(
    "join-missing-nul-quote",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# pk_header_join() allocates no room for the terminating zero

parsekit 1.2.0. In lines {JOIN_S}-{JOIN_E} of src/header.c the joined value is built
in a buffer of exactly `total` bytes:

```c
  total += (n - 1) * 2;
  out = malloc(total);
  ...
  out[pos] = '\\0';
```

The final store is one byte past the allocation when the header repeats.

Reproduce with:

{POC_SH_OVERFLOW_ARG}
""",
    poc="sh",
    reproduces=True,
    bug="heap-buffer-overflow",
    notes="abbreviated quote with ellipsis",
)

add(
    "set-cookie-join",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# Heap overflow when joining Set-Cookie headers

Tested on parsekit 1.2.0, built with `-fsanitize=address,undefined`.

Any application that calls `pk_header_join()` on a header that appears twice
(Set-Cookie is the usual case) corrupts the heap. Trace:

```
{asan_overflow(prefix="/work/parsekit", cols=False, pid=88)}
```

PoC:

{POC_C_OVERFLOW}
""",
    poc="c",
    reproduces=True,
    bug="heap-buffer-overflow",
    notes="trace without columns",
)

add(
    "thin-join",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# Duplicate headers crash parsekit 1.2.0

`parsekit header` with two `Accept:` lines crashes (heap-buffer-overflow).

{POC_SH_OVERFLOW_ARG}
""",
    poc="sh",
    reproduces=True,
    bug="heap-buffer-overflow",
    notes="thin: one reference",
)

add(
    "normalize-uaf",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# Use after free in pk_url_normalize() for paths with dot segments

## Summary

parsekit 1.2.0 reads freed memory in `pk_url_normalize()` when the URL path contains
`.` or `..` segments. The function keeps `base`, a pointer into `u->path`, frees
`u->path` at `src/url.c:{NORM_FREE}` and then dereferences `base` at line {NORM_READ}.

The code in `src/url.c`:

```c
{QUOTE_NORM}
```

## AddressSanitizer

```
{asan_uaf()}
```

## Reproduction

{POC_SH_UAF}
""",
    poc="sh",
    reproduces=True,
    bug="heap-use-after-free",
    notes="detailed UAF with free and alloc stacks",
)

add(
    "normalize-uaf-api",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# heap-use-after-free in URL normalisation

Version: parsekit 1.2.0

`pk_url_normalize()` (src/url.c, lines {NORM_S}-{NORM_E}) frees the old path and then
reads `base[1]`, where `base` came from `strrchr()` on the freed string. Reached through
the public API:

{POC_C_UAF}

ASan reports `heap-use-after-free` READ of size 1 in `pk_url_normalize` at src/url.c:{NORM_READ}.
""",
    poc="c",
    reproduces=True,
    bug="heap-use-after-free",
    notes="C API PoC, prose frame",
)

add(
    "normalize-uaf-terse",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# UAF: parsekit normalize with ../ in path

parsekit 1.2.0

```
{asan_uaf(short=True, pid=5150)}
```

{POC_SH_UAF}
""",
    poc="sh",
    reproduces=True,
    bug="heap-use-after-free",
    notes="terse, short trace",
)

add(
    "normalize-uaf-noversion",
    "valid",
    "parsekit",
    None,
    f"""# Normalising URLs with dot segments reads freed memory

The crash is in pk_url_normalize at src/url.c:{NORM_READ}: the pointer `base` is computed
from the old path, which is freed a few lines earlier at line {NORM_FREE}.

{POC_SH_UAF}
""",
    poc="sh",
    reproduces=True,
    bug="heap-use-after-free",
    notes="no version",
)

add(
    "normalize-uaf-docs-url",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# Use-after-free when normalising https://example.com/docs/./guide/../index.html

Affected: parsekit 1.2.0, `src/url.c`

Steps:

{POC_C_UAF}

Result (excerpt):

```
{asan_uaf(prefix="/src/parsekit", pid=2024)}
```
""",
    poc="c",
    reproduces=True,
    bug="heap-use-after-free",
    notes="C PoC with full trace",
)

add(
    "normalize-in-function-at",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# Freed path pointer used in pk_url_normalize

In parsekit 1.2.0 the crash happens in function pk_url_normalize at src/url.c:{NORM_READ}, after
`free(u->path)` on line {NORM_FREE} of src/url.c. `remove_dot_segments()` returns a new buffer and
the old one is released before `base` is checked.

{POC_SH_UAF}
""",
    poc="sh",
    reproduces=True,
    bug="heap-use-after-free",
    notes="'in function X at file:line' prose",
)

add(
    "thin-uaf",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# parsekit normalize crash

parsekit 1.2.0, `pk_url_normalize()`: heap-use-after-free with dot segments.

{POC_SH_UAF}
""",
    poc="sh",
    reproduces=True,
    bug="heap-use-after-free",
    notes="thin",
)

add(
    "kvconf-recursion",
    "valid",
    "kvconf",
    "0.2.0",
    f"""# Unbounded recursion on cyclic ${{...}} references

kvconf 0.2.0 crashes with `RecursionError` when two keys reference each other. The
recursion is in `_expand()` in `src/kvconf/interp.py` (lines {EXPAND_S}-{EXPAND_E}):

```python
{QUOTE_EXPAND}
```

Traceback:

```
{py_traceback()}
```

PoC:

{POC_PY}
""",
    poc="python",
    reproduces=True,
    bug="RecursionError",
    notes="python traceback and quote",
)

add(
    "kvconf-cli-loop",
    "valid",
    "kvconf",
    "0.2.0",
    f"""# kvconf CLI crashes on a self-referencing key

Version: kvconf 0.2.0

A configuration line that refers to itself, `name = ${{name}}`, makes `kvconf` die with
a RecursionError traceback instead of an error message. `load()` calls `loads()`
(src/kvconf/parser.py:{LOADS_LINE}), which expands references in `_expand()` without a depth limit
(src/kvconf/interp.py:{REPLACE_LINE}).

{POC_SH_KV}
""",
    poc="sh",
    reproduces=True,
    bug="RecursionError",
    notes="CLI shell PoC",
)

add(
    "kvconf-self-noversion",
    "valid",
    "kvconf",
    None,
    f"""# RecursionError in interpolate()

`kvconf.loads()` never returns for `greeting = hello ${{greeting}}`; it raises RecursionError
from `_expand()` / `replace()` in interp.py.

{POC_PY_SELF}
""",
    poc="python",
    reproduces=True,
    bug="RecursionError",
    notes="no version, python PoC",
)

add(
    "join-overflow-inline-header",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# One-byte heap overwrite via `parsekit header "<text>"`

parsekit 1.2.0. The inline form of the header command goes through `cmd_header()`
(cli/parsekit.c:{CMD_HEADER_CALL}) into `pk_header_join()`, which overflows when a header
repeats.

{POC_SH_OVERFLOW_ARG}

```
{asan_overflow(prefix="/opt/src/parsekit", pid=6060)}
```
""",
    poc="sh",
    reproduces=True,
    bug="heap-buffer-overflow",
    notes="inline header argument",
)

add(
    "normalize-uaf-lines",
    "valid",
    "parsekit",
    "1.2.0",
    f"""# pk_url_normalize: stale pointer after free

parsekit 1.2.0

File: src/url.c

Function: pk_url_normalize (lines {NORM_S}-{NORM_E})

Lines {NORM_STRRCHR}, {NORM_FREE} and {NORM_READ}: `base` is taken from the old path, the old path is
freed, then `base[1]` is read.

{POC_SH_UAF}
""",
    poc="sh",
    reproduces=True,
    bug="heap-use-after-free",
    notes="File/Function/Lines template",
)

add(
    "kvconf-mutual",
    "valid",
    "kvconf",
    "0.2.0",
    f"""# Crash: mutually recursive interpolation

kvconf 0.2.0, `src/kvconf/interp.py`, `_expand()` at line {SUB_LINE} and the nested `replace()` at
line {REPLACE_LINE}: there is no cycle detection, so `[a] x = ${{a.y}}` / `y = ${{a.x}}` recurses until
Python gives up.

{POC_PY}
""",
    poc="python",
    reproduces=True,
    bug="RecursionError",
    notes="lines only",
)

# ----------------------------------------------------------------------------------
# 40 low-quality reports
# ----------------------------------------------------------------------------------
FAKE_TRACE_1 = f"""==7781==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x60c000000140
WRITE of size 8 at 0x60c000000140 thread T0
    #0 {addr()} in pk_chunk_decode /src/parsekit/src/chunked.c:88:14
    #1 {addr()} in pk_http_read_body /src/parsekit/src/http_body.c:214:9
    #2 {addr()} in pk_session_feed /src/parsekit/src/session.c:57:5
    #3 {addr()} in main /src/parsekit/cli/parsekit.c:131:10

SUMMARY: AddressSanitizer: heap-buffer-overflow /src/parsekit/src/chunked.c:88:14 in pk_chunk_decode"""
FAKE_TRACE_2 = f"""==19==ERROR: AddressSanitizer: stack-buffer-overflow on address 0x7ffc1a2b
READ of size 4 at 0x7ffc1a2b thread T0
    #0 {addr()} in pk_url_resolve_relative /src/parsekit/src/url.c:402:11
    #1 {addr()} in pk_url_join_base /src/parsekit/src/url.c:451:8
    #2 {addr()} in cmd_url /src/parsekit/cli/parsekit.c:66:3

SUMMARY: AddressSanitizer: stack-buffer-overflow /src/parsekit/src/url.c:402:11"""
FAKE_TRACE_3 = f"""==500==ERROR: AddressSanitizer: heap-use-after-free on address 0x6020000000f0
    #0 {addr()} in pk_headers_compact /src/parsekit/src/header.c:301:7
    #1 {addr()} in pk_header_remove_all /src/parsekit/src/header.c:322:3
    #2 {addr()} in pk_cookie_jar_flush /src/parsekit/src/cookie.c:45:5"""
MISMATCH_TRACE_1 = f"""==4410==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502000000035
WRITE of size 1 at 0x502000000035 thread T0
    #0 {addr()} in pk_header_join /src/parsekit/src/header.c:{UNFOLD_S + 8}:12
    #1 {addr()} in parse_line /src/parsekit/src/header.c:{HEADER_GET_S + 2}:9
    #2 {addr()} in pk_header_parse /src/parsekit/src/header.c:{PARSE_LINE_S + 3}:10

SUMMARY: AddressSanitizer: heap-buffer-overflow /src/parsekit/src/header.c:{UNFOLD_S + 8}"""
MISMATCH_TRACE_2 = f"""==61==ERROR: AddressSanitizer: heap-use-after-free on address 0x503000000044
READ of size 1 at 0x503000000044 thread T0
    #0 {addr()} in pk_url_normalize /src/parsekit/src/url.c:{URL_PARSE_S + 10}:7
    #1 {addr()} in pk_percent_decode /src/parsekit/src/util.c:{HEXVAL_S + 2}:3
    #2 {addr()} in cmd_url /src/parsekit/cli/parsekit.c:{CMD_URL_NORM}:10"""
MISMATCH_TRACE_3 = f"""    #0 {addr()} in pk_buf_append /src/parsekit/src/buf.c:{BUF_RESERVE_S + 4}:5
    #1 {addr()} in pk_header_unfold /src/parsekit/src/header.c:{JOIN_S + 5}:9
    #2 {addr()} in parse_line /src/parsekit/src/header.c:{PARSE_LINE_S + 20}:12"""
FAKE_QUOTE_1 = """static char *pk_header_merge(const char *a, const char *b)
{
  char tmp[256];
  sprintf(tmp, "%s, %s", a, b);   /* no length check */
  return strdup(tmp);
}"""
FAKE_QUOTE_2 = """  if(u->port_str) {
    char portbuf[6];
    strcpy(portbuf, u->port_str);
    u->port = atoi(portbuf);
  }"""
FAKE_QUOTE_3 = """size_t pk_decode_chunk_size(const char *p)
{
  size_t n = 0;
  while(isxdigit(*p))
    n = n * 16 + hexval(*p++);
  return n;  // integer overflow not checked
}"""

add(
    "merge-continuation",
    "invalid",
    "parsekit",
    "1.2.0",
    """# Critical heap overflow in pk_header_merge_continuation()

parsekit 1.2.0 has a critical vulnerability in `pk_header_merge_continuation()` which calls
`pk_buf_grow_exact()` without checking the size returned by `pk_header_measure()`. An attacker
sending folded headers can overwrite the heap and achieve remote code execution.

The problem is in `src/header.c`. The fix is to validate the length before `pk_buf_grow_exact()`.
""",
    modes=["nonexistent_function"],
    notes="three invented functions",
)

add(
    "resolve-relative",
    "invalid",
    "parsekit",
    "1.2.0",
    """# Path traversal in pk_url_resolve_relative

`pk_url_resolve_relative()` and `pk_url_join_base()` in src/url.c do not reject `../` segments,
allowing access to arbitrary files when parsekit is used in a web server.

Severity: high (CVSS 8.1)
""",
    modes=["nonexistent_function"],
    notes="two invented functions",
)

add(
    "buf-grow-exact",
    "invalid",
    "parsekit",
    None,
    """# Integer overflow in buffer growth

The function `pk_buf_grow_exact()` multiplies the capacity by 2 without an overflow check, and
`pk_buf_shrink_to_fit()` then frees the old pointer twice. This leads to memory corruption.
""",
    modes=["nonexistent_function"],
    notes="no version, invented functions",
)

add(
    "http-parser-file",
    "invalid",
    "parsekit",
    "1.2.0",
    """# Request smuggling in src/http_parser.c

parsekit's `src/http_parser.c` accepts both Content-Length and Transfer-Encoding, see
`src/http_parser.c:212`. The chunk parser in `src/chunked.c` also trusts the size line.
""",
    modes=["nonexistent_file", "line_out_of_range"],
    notes="files that never existed",
)

add(
    "cookie-file",
    "invalid",
    "parsekit",
    "1.2.0",
    """# Cookie parsing overflow

The cookie jar code in `lib/parsekit/cookie.c` and `src/cookie_jar.c` copies cookie names into
a fixed buffer. This affects every application that uses parsekit for HTTP.
""",
    modes=["nonexistent_file"],
    notes="nonexistent files",
)

add(
    "session-file",
    "invalid",
    "parsekit",
    None,
    """# Memory leak in src/session.c

`src/session.c` leaks the session object when `src/transport/tls.c` fails to connect. Over time
this causes denial of service.
""",
    modes=["nonexistent_file"],
    notes="nonexistent files, no version",
)

add(
    "url-line-612",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Out-of-bounds read in the URL parser

parsekit 1.2.0, `src/url.c:{URL_LINES + 300}` reads `host[len]` without checking `len`, and the same
pattern appears at line {URL_LINES + 341} of src/url.c.
""",
    modes=["line_out_of_range"],
    notes="lines past end of src/url.c",
)

add(
    "header-line-940",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Header value copied without bounds check

In parsekit 1.2.0, line {HEADER_LINES + 700} of `src/header.c` copies the header value into a stack
buffer. Also see `src/util.c:{UTIL_LINES + 120}`.
""",
    modes=["line_out_of_range"],
    notes="lines past end",
)

add(
    "decode-line-oob",
    "invalid",
    "parsekit",
    "1.1.0",
    f"""# pk_percent_decode reads past the input

parsekit 1.1.0, `src/util.c:{UTIL_LINES + 55}`: the decoder reads two bytes after `%` without
checking the remaining length. Combined with `src/buf.c:{nlines("parsekit", "1.1.0", "src/buf.c") + 90}` this
corrupts the heap.
""",
    modes=["line_out_of_range"],
    notes="lines past end at 1.1.0",
)

add(
    "comment-line",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Unsafe concatenation at src/header.c:{COMMENT_LINE}

parsekit 1.2.0. The code at `src/header.c:{COMMENT_LINE}` and `src/url.c:{BLANK_LINE_URL}` concatenates
attacker-controlled strings. Please fix urgently.
""",
    modes=["line_blank_or_comment"],
    notes="cites a comment line and a blank line",
)

add(
    "blank-line-only",
    "invalid",
    "parsekit",
    None,
    f"""# Possible overflow near src/url.c:{BLANK_LINE_URL}

I believe there might be an overflow at `src/url.c:{BLANK_LINE_URL}`. I did not test it.
""",
    modes=["line_blank_or_comment", "no_poc"],
    notes="blank line only",
)

add(
    "frame-mismatch-join",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Heap overflow in header joining (ASan confirmed)

parsekit 1.2.0. AddressSanitizer output:

```
{MISMATCH_TRACE_1}
```

The overflow happens because `pk_header_join()` trusts `value_len`.
""",
    modes=["frame_mismatch"],
    poc="none",
    notes="real names, lines inside other functions",
)

add(
    "frame-mismatch-normalize",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# UAF in pk_url_normalize via pk_percent_decode

```
{MISMATCH_TRACE_2}
```

`pk_percent_decode()` frees the path and `pk_url_normalize()` uses it afterwards.
""",
    modes=["frame_mismatch"],
    notes="frames point into other functions; call chain impossible",
)

add(
    "frame-mismatch-unfold",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Crash in pk_header_unfold

Backtrace from my fuzzer (parsekit 1.2.0):

```
{MISMATCH_TRACE_3}
```
""",
    modes=["frame_mismatch"],
    notes="frame lines inside other functions",
)

add(
    "fabricated-trace-chunked",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Heap-buffer-overflow in chunked body decoding

parsekit 1.2.0 crashes when decoding a chunked body:

```
{FAKE_TRACE_1}
```

{POC_SH_BENIGN}
""",
    modes=["fabricated_trace", "nonexistent_file", "nonexistent_function"],
    poc="sh",
    notes="invented trace; PoC uses a normal URL",
)

add(
    "fabricated-trace-resolve",
    "invalid",
    "parsekit",
    None,
    f"""# Stack overflow when resolving relative URLs

```
{FAKE_TRACE_2}
```
""",
    modes=["fabricated_trace", "nonexistent_function"],
    notes="invented functions in a real file",
)

add(
    "fabricated-trace-cookie",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# UAF when flushing cookies

ASan:

```
{FAKE_TRACE_3}
```

This is a critical issue for all users of parsekit.
""",
    modes=["fabricated_trace", "nonexistent_file", "nonexistent_function"],
    notes="invented trace",
)

add(
    "fabricated-quote-merge",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# sprintf overflow when merging headers

The vulnerable code in `src/header.c`:

```c
{FAKE_QUOTE_1}
```

Two long header values overflow `tmp`.
""",
    modes=["fabricated_quote", "nonexistent_function"],
    notes="quote never in the project",
)

add(
    "fabricated-quote-port",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Stack overflow in port parsing

parsekit 1.2.0 copies the port string into a 6-byte stack buffer. From `src/url.c`:

```c
{FAKE_QUOTE_2}
```
""",
    modes=["fabricated_quote"],
    notes="quote never in the project",
)

add(
    "fabricated-quote-chunk",
    "invalid",
    "parsekit",
    None,
    f"""# Integer overflow in chunk size parsing

The code in `src/util.c`:

```c
{FAKE_QUOTE_3}
```
""",
    modes=["fabricated_quote", "nonexistent_function"],
    notes="invented helper quoted from a real file",
)

add(
    "own-buffer-host",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Buffer overflow in pk_url_parse with long host names

`pk_url_parse()` in src/url.c (lines {URL_PARSE_S}-{URL_PARSE_E}) returns host names of any length,
which overflows the caller's buffer. PoC:

{POC_OWN_BUFFER}

AddressSanitizer reports a stack-buffer-overflow.
""",
    modes=["poc_own_buffer"],
    poc="c",
    notes="PoC overflows its own 8-byte buffer",
)

add(
    "own-buffer-strerror",
    "invalid",
    "parsekit",
    "1.2.0",
    """# Heap overflow involving pk_strerror

`pk_strerror()` returns strings longer than expected. Reproducer:

"""
    + POC_OWN_BUFFER_2
    + "\n",
    modes=["poc_own_buffer"],
    poc="c",
    notes="PoC copies into its own 4-byte allocation",
)

add(
    "no-lib-double-free",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Double free in header handling

parsekit 1.2.0 frees header values twice in `pk_headers_free()` (src/header.c). Proof:

{POC_NO_LIB}
""",
    modes=["poc_no_library_call"],
    poc="c",
    notes="PoC never calls the library",
)

add(
    "no-lib-array",
    "invalid",
    "parsekit",
    None,
    f"""# Out-of-bounds read in header indexing

{POC_NO_LIB_2}

This shows the same off-by-one that `pk_header_get()` has.
""",
    modes=["poc_no_library_call"],
    poc="c",
    notes="PoC never calls the library",
)

add(
    "no-compile-set-raw",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Heap overflow through pk_header_set_raw

Calling `pk_header_set_raw()` with a large length corrupts memory:

{POC_NO_COMPILE}
""",
    modes=["poc_does_not_compile", "nonexistent_function"],
    poc="c",
    notes="calls functions that do not exist",
)

add(
    "no-compile-url-new",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Traversal in pk_url_set_path

{POC_NO_COMPILE_2}

`pk_url_set_path()` accepts `..` segments that escape the root.
""",
    modes=["poc_does_not_compile", "nonexistent_function"],
    poc="c",
    notes="API that never existed",
)

add(
    "version-130",
    "invalid",
    "parsekit",
    "1.3.0",
    """# Regression in parsekit 1.3.0

After upgrading to parsekit 1.3.0, `pk_header_parse()` accepts header names with spaces, which
enables header injection. `pk_header_validate_name()` was removed in this release.
""",
    modes=["version_never_released", "nonexistent_function"],
    notes="version never released",
)

add(
    "version-200",
    "invalid",
    "parsekit",
    "2.0.0",
    f"""# parsekit 2.0.0 URL parser crash

parsekit 2.0.0 crashes on IPv6 hosts in `parse_authority()` (src/url.c). Steps:

{POC_SH_BENIGN}
""",
    modes=["version_never_released"],
    poc="sh",
    notes="version never released, benign PoC",
)

add(
    "version-131",
    "invalid",
    "kvconf",
    "1.3.1",
    """# kvconf 1.3.1 include traversal

kvconf 1.3.1 allows `@include ../../etc/passwd`. The check in `_resolve_include()` is missing.
""",
    modes=["version_never_released", "nonexistent_function"],
    notes="kvconf version never released",
)

add(
    "other-library-xml",
    "invalid",
    "parsekit",
    "1.2.0",
    """# XXE in parsekit

parsekit 1.2.0 is vulnerable to XML external entities: `xmlParseChunk()` is called with
`XML_PARSE_NOENT` in `parser.c`, and `xmlCtxtUseOptions()` does not disable entity loading.
See `include/libxml/parser.h` for the options.
""",
    modes=["other_library"],
    notes="describes libxml2, not parsekit",
)

add(
    "other-library-curl",
    "invalid",
    "parsekit",
    "1.2.0",
    """# URL API overflow (Curl_parse_url)

In `lib/urlapi.c`, `Curl_parse_url()` copies the scheme into a fixed buffer, and `curl_url_set()`
passes the user string straight through. `lib/url.c:1840` shows the same pattern.
""",
    modes=["other_library", "nonexistent_file", "nonexistent_function"],
    notes="describes a different library",
)

add(
    "padded-merge",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Heap overflow in header folding (pk_header_unfold -> pk_header_merge_continuation)

## Details

parsekit 1.2.0 parses headers in `pk_header_parse()` (src/header.c:{PARSE_LINE_E + 5}), which calls
`parse_line()` (src/header.c:{PARSE_LINE_S}) and `pk_header_unfold()` (src/header.c:{UNFOLD_S}). Values are
appended with `pk_buf_append()` in src/buf.c and duplicated with `pk_strndup()` in src/util.c.
`pk_header_get()` and `pk_header_count()` then read them back.

The overflow is in `pk_header_merge_continuation()`, which calls `pk_buf_grow_exact()` with a length
computed by `pk_header_measure()`.
""",
    modes=["padded", "nonexistent_function"],
    notes="three invented functions among many real references",
)

add(
    "padded-trace",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Use after free in URL handling

Relevant functions: `pk_url_parse()` in src/url.c, `pk_url_normalize()` (src/url.c:{NORM_S}),
`pk_url_to_string()`, `pk_url_free()`, `pk_strndup()` (src/util.c), `pk_buf_append()` (src/buf.c),
`pk_buf_detach()` and `default_port()`.

```
{FAKE_TRACE_2}
```
""",
    modes=["padded", "fabricated_trace", "nonexistent_function"],
    notes="invented frames among real references",
)

add(
    "padded-quote",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Unchecked copy when joining headers

parsekit 1.2.0, `src/header.c`. `pk_header_parse()`, `parse_line()`, `pk_header_unfold()`,
`pk_header_get()`, `pk_header_count()` and `pk_headers_free()` all operate on `struct pk_headers`.
`pk_header_remove()` uses `memmove`.

The vulnerable code in `src/header.c`:

```c
{FAKE_QUOTE_1}
```

and the helper `pk_header_measure()` returns the wrong size.
""",
    modes=["padded", "fabricated_quote", "nonexistent_function"],
    notes="invented quote and function among real references",
)

add(
    "padded-files",
    "invalid",
    "parsekit",
    None,
    """# Memory corruption across the parser

Files involved: `src/url.c`, `src/header.c`, `src/buf.c`, `src/util.c`, `src/query.c`,
`cli/parsekit.c`, `include/parsekit.h`, and the new `src/http_parser.c` and `src/chunked.c`.
Functions: `pk_url_parse()`, `pk_query_parse()`, `pk_header_parse()`, `pk_chunk_decode()` and
`pk_http_read_body()`.
""",
    modes=["padded", "nonexistent_file", "nonexistent_function"],
    notes="two invented files and functions among real ones",
)

add(
    "vague-1",
    "invalid",
    "parsekit",
    None,
    """# Security vulnerability in parsekit

I found a serious memory safety issue in parsekit's parsing code that can lead to remote code
execution. The library does not properly validate input lengths. Please assign a CVE and a bounty.
""",
    modes=["no_references"],
    notes="nothing checkable",
)

add(
    "vague-2",
    "invalid",
    "kvconf",
    None,
    """# Insecure configuration parsing

kvconf might be vulnerable to injection attacks because configuration values are not sanitised.
An attacker could potentially exploit this.
""",
    modes=["no_references"],
    notes="nothing checkable",
)

add(
    "stale-concat",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Overflow in pk_header_concat()

parsekit 1.2.0: `pk_header_concat()` in `src/strutil.c` sizes the buffer incorrectly, and
`pk_header_set_raw()` makes it reachable from user input.

{POC_SH_BENIGN_2}
""",
    modes=["stale_reference", "nonexistent_function"],
    poc="sh",
    notes="names from 1.0.0 plus an invented function; benign PoC",
)

add(
    "benign-poc-normal-url",
    "invalid",
    "parsekit",
    "1.2.0",
    f"""# Crash in pk_url_parse

parsekit 1.2.0 crashes in `pk_url_parse()` (src/url.c:{URL_PARSE_S + 5}) on ordinary URLs:

{POC_SH_BENIGN}
""",
    modes=["poc_does_not_reproduce"],
    poc="sh",
    notes="real reference, PoC with a normal URL",
)

add(
    "kvconf-fake-include",
    "invalid",
    "kvconf",
    "0.2.0",
    """# Include path traversal in kvconf

kvconf 0.2.0 resolves `@include` paths with `_resolve_include()` and `_safe_join()` in
`src/kvconf/includes.py`, which do not block `..`.
""",
    modes=["nonexistent_function", "nonexistent_file"],
    notes="invented module and helpers",
)

assert sum(r.label == "valid" for r in REPORTS) == 20, sum(r.label == "valid" for r in REPORTS)
assert sum(r.label == "invalid" for r in REPORTS) == 40, sum(r.label == "invalid" for r in REPORTS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.md"):
        old.unlink()
    labels = []
    for i, r in enumerate(REPORTS, 1):
        name = f"{i:02d}-{r.slug}.md"
        (OUT / name).write_text(r.body.rstrip() + "\n", encoding="utf-8")
        labels.append(
            {
                "file": name,
                "label": r.label,
                "project": r.project,
                "claimed_version": r.version,
                "bug": r.bug,
                "failure_modes": r.modes,
                "poc": r.poc,
                "poc_reproduces": r.reproduces,
                "notes": r.notes,
            }
        )
    doc = {"schema": "sloptriage-demo-labels/1", "reports": labels}
    (OUT / "labels.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(labels)} reports to {OUT}")


if __name__ == "__main__":
    main()
