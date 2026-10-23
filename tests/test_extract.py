from __future__ import annotations

from sloptriage.extract import ExtractContext, extract

CTX = ExtractContext(
    project="curl",
    aliases=("libcurl",),
    languages=("c",),
    binaries=("curl",),
    repo_slug="curl/curl",
)


def kinds(text: str, ctx: ExtractContext = CTX) -> set[tuple[str, str, str]]:
    return {(c.kind, c.value, c.confidence) for c in extract(text, ctx).claims}


def test_backticked_call_is_high_and_bare_word_is_medium() -> None:
    got = kinds("The bug is in `Curl_parse_url()` and `parse` and `strcpy()`.")
    assert ("symbol", "Curl_parse_url", "high") in got
    assert ("symbol", "parse", "medium") not in got  # common word, never a claim
    assert not any(v == "strcpy" for _, v, _ in got)  # libc is not a claim about the project


def test_paths_lines_and_permalinks() -> None:
    text = "See lib/http.c:812:3 and line 40 of `lib/url.c`, https://github.com/curl/curl/blob/abc1234/lib/ws.c#L10-L20"
    claims = extract(text, CTX).claims
    lines = {(c.path, c.line, c.line_end) for c in claims if c.kind == "line"}
    assert ("lib/http.c", 812, None) in lines
    assert ("lib/url.c", 40, None) in lines
    assert ("lib/ws.c", 10, 20) in lines
    link = next(c for c in claims if c.kind == "path" and c.source == "permalink")
    assert (link.ref, link.repo) == ("abc1234", "curl/curl")


def test_asan_frames_and_error_type() -> None:
    text = """```
==1==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x602
READ of size 1 at 0x602 thread T0
    #0 0x55d in parse_header /src/curl/lib/http.c:214:9
    #1 0x55e in Curl_http_readwrite_headers /src/curl/lib/http.c:3400:5
    #2 0x7f1 in __libc_start_main (/lib/x86_64-linux-gnu/libc.so.6+0x2409b)
```"""
    claims = extract(text, CTX).claims
    frames = [c for c in claims if c.kind == "frame"]
    assert [(f.frame_index, f.function, f.line) for f in frames[:2]] == [
        (0, "parse_header", 214),
        (1, "Curl_http_readwrite_headers", 3400),
    ]
    assert frames[2].module is not None
    assert any(c.kind == "sanitizer_claim" and c.value == "heap-buffer-overflow" for c in claims)


def test_gdb_multiline_frames() -> None:
    text = "#0  0x0000555555582039 in curl_dbg_log (format=0x1,\n    x=2) at memdebug.c:383\n#1  0x00005 in foo_bar (a=1) at lib/x.c:12\n"
    frames = [c for c in extract(text, CTX).claims if c.kind == "frame"]
    assert [(f.function, f.path, f.line) for f in frames] == [
        ("curl_dbg_log", "memdebug.c", 383),
        ("foo_bar", "lib/x.c", 12),
    ]


def test_python_traceback() -> None:
    text = 'Traceback (most recent call last):\n  File "/app/kvconf/parser.py", line 12, in load\n    x()\n'
    frame = next(c for c in extract(text, CTX).claims if c.kind == "frame")
    assert (frame.path, frame.line, frame.function) == ("/app/kvconf/parser.py", 12, "load")


def test_quote_vs_poc_vs_fix() -> None:
    text = """The vulnerable code in `lib/http.c`:

```c
if(len > max)
  return CURLE_TOO_LARGE;
```

Steps to reproduce:

```c
#include <curl/curl.h>
int main(void) { return curl_easy_perform(NULL); }
```

Suggested fix:

```c
if(len >= max)
  return CURLE_TOO_LARGE;
```
"""
    claims = extract(text, CTX).claims
    quotes = [c for c in claims if c.kind == "quote"]
    pocs = [c for c in claims if c.kind == "poc"]
    assert len(quotes) == 1 and quotes[0].path == "lib/http.c" and quotes[0].confidence == "high"
    assert len(pocs) == 1 and pocs[0].poc_kind == "c"


def test_versions_near_project_name() -> None:
    got = kinds("Tested with curl 8.10.1 and libcurl/7.88.0 (OpenSSL/3.0.2), tag curl-8_4_0.")
    versions = {v for k, v, _ in got if k == "version"}
    assert {"8.10.1", "7.88.0", "8.4.0"} <= versions
    assert "3.0.2" not in versions


def test_cve_cwe_and_poc_defined_names() -> None:
    text = "CVE-2023-38545 and CWE-122.\n\nPoC:\n```c\nstatic int helper_fn(void) { return 1; }\nint main(void) { return helper_fn(); }\n```\nThe `helper_fn()` call crashes."
    ex = extract(text, CTX)
    assert {c.value for c in ex.claims if c.kind in ("cve", "cwe")} == {"CVE-2023-38545", "CWE-122"}
    assert "helper_fn" in ex.poc_names
    assert not any(c.kind == "symbol" and c.value == "helper_fn" for c in ex.claims)


def test_template_function_and_lines() -> None:
    text = "File: lib/vtls/wolfssl.c\n\nFunction: wssl_strerror (lines 1542-1556)\n\nLines 741, 773, and 804"
    claims = extract(text, CTX).claims
    assert any(
        c.kind == "frame" and c.function == "wssl_strerror" and c.line == 1542 for c in claims
    )
    assert {c.line for c in claims if c.kind == "line"} >= {741, 773, 804}


def test_spans_point_into_the_text() -> None:
    text = "Crash in `Curl_foo_bar()` at lib/x.c:9"
    for c in extract(text, CTX).claims:
        assert 0 <= c.start < c.end <= len(text)
