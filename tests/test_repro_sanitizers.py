from __future__ import annotations

import pytest

from sloptriage.repro.sanitizers import (
    Crash,
    error_types_match,
    parse_output,
    repo_path,
    signal_name,
    top_project_frame,
)

ASAN_OVERFLOW = """\
make: nothing to do
====================
==31337==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x502000000035 at pc 0x5581f3a2 bp 0x7ffc1 sp 0x7ffc0
WRITE of size 1 at 0x502000000035 thread T0
    #0 0x5581f3a2 in pk_header_join /build/src/src/header.c:175:12
    #1 0x5581f3b9 in cmd_header /build/src/cli/parsekit.c:109:13
    #2 0x5581f3c0 in main /build/src/cli/parsekit.c:168:10
    #3 0x7f0a1c2b in __libc_start_call_main ../sysdeps/nptl/libc_start_call_main.h:58:16
    #4 0x5581f2e0 in _start (/opt/project/bin/parsekit+0x2c364)

0x502000000035 is located 0 bytes after 5-byte region [0x502000000030,0x502000000035)
allocated by thread T0 here:
    #0 0x7f0a1d00 in malloc ../../../../src/libsanitizer/asan/asan_malloc_linux.cpp:69
    #1 0x5581f39a in pk_header_join /build/src/src/header.c:161:9

SUMMARY: AddressSanitizer: heap-buffer-overflow /build/src/src/header.c:175:12 in pk_header_join
==31337==ABORTING
"""

ASAN_MEMCPY = """\
==7==ERROR: AddressSanitizer: stack-buffer-overflow on address 0x7ffd0 at pc 0x7f1 bp 0x7ffd1 sp 0x7ffd2
WRITE of size 40 at 0x7ffd0 thread T0
    #0 0x7f1 in __interceptor_memcpy /usr/src/gcc/libsanitizer/sanitizer_common/sanitizer_common_interceptors.inc:827
    #1 0x401 in pk_buf_append /build/src/src/buf.c:44:5
    #2 0x402 in main /work/poc/poc.c:9:3
"""

ASAN_SEGV = """\
==1==ERROR: AddressSanitizer: SEGV on unknown address 0x000000000008 (pc 0x55 bp 0x7ff sp 0x7fe T0)
==1==The signal is caused by a READ memory access.
==1==Hint: address points to the zero page.
    #0 0x55 in pk_url_free /build/src/src/url.c:300:9
    #1 0x56 in main /work/poc/poc.c:12:3
"""

ASAN_DOUBLE_FREE = """\
==1==ERROR: AddressSanitizer: attempting double-free on 0x602000000010 in thread T0:
    #0 0x1 in free (/usr/lib/libasan.so.8+0x1)
    #1 0x2 in main /work/poc/poc.c:7:3
"""

UBSAN = """\
/build/src/src/url.c:210:17: runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'
"""

UBSAN_STACK = """\
/build/src/src/url.c:210:17: runtime error: signed integer overflow: 2147483647 + 1 cannot be represented in type 'int'
    #0 0x55 in pk_url_parse /build/src/src/url.c:210:17
    #1 0x56 in main /work/poc/poc.c:5:3
"""

TSAN = """\
==================
WARNING: ThreadSanitizer: data race (pid=12)
  Write of size 4 at 0x7b04 by thread T2:
    #0 worker /build/src/src/pool.c:41:12 (prog+0x1a2b)
    #1 __tsan_thread_start_func <null> (prog+0x4)

  Previous read of size 4 at 0x7b04 by main thread:
    #0 main /work/poc/poc.c:20:5 (prog+0x1c3d)
"""

PY_TRACEBACK = """\
Traceback (most recent call last):
  File "/work/poc/poc.py", line 4, in <module>
    kvconf.loads(TEXT)
  File "/usr/local/lib/python3.12/site-packages/kvconf/parser.py", line 95, in loads
    return interpolate(parse_lines(text, source, base_dir))
  File "/usr/local/lib/python3.12/site-packages/kvconf/interp.py", line 29, in interpolate
    return {key: _expand(value, values) for key, value in values.items()}
  File "/usr/local/lib/python3.12/site-packages/kvconf/interp.py", line 24, in _expand
    return _REF.sub(replace, value)
  [Previous line repeated 495 more times]
RecursionError: maximum recursion depth exceeded
"""

FILES = {
    "src/header.c",
    "cli/parsekit.c",
    "src/buf.c",
    "src/url.c",
    "src/kvconf/interp.py",
    "src/kvconf/parser.py",
}


def test_asan_overflow_keeps_the_first_stack_only() -> None:
    crash = parse_output(ASAN_OVERFLOW)
    assert isinstance(crash, Crash)
    assert crash.tool == "AddressSanitizer"
    assert crash.error_type == "heap-buffer-overflow"
    assert [f.function for f in crash.frames] == [
        "pk_header_join",
        "cmd_header",
        "main",
        "__libc_start_call_main",
        "_start",
    ]
    top = crash.frames[0]
    assert (top.index, top.path, top.line) == (0, "/build/src/src/header.c", 175)


def test_asan_error_type_for_other_headlines() -> None:
    segv = parse_output(ASAN_SEGV)
    assert segv is not None and segv.error_type == "SEGV"
    double = parse_output(ASAN_DOUBLE_FREE)
    assert double is not None and double.error_type == "double-free"
    assert double.frames[0].function == "free"


def test_ubsan_with_and_without_a_stack() -> None:
    bare = parse_output(UBSAN)
    assert bare is not None
    assert bare.tool == "UndefinedBehaviorSanitizer"
    assert bare.error_type == "signed-integer-overflow"
    assert (bare.frames[0].path, bare.frames[0].line, bare.frames[0].function) == (
        "/build/src/src/url.c",
        210,
        None,
    )
    stacked = parse_output(UBSAN_STACK)
    assert stacked is not None
    assert [f.function for f in stacked.frames] == ["pk_url_parse", "main"]


UBSAN_OBJECT_SIZE = """\
/build/src/src/header.c:175:12: runtime error: store to address 0x502000000054 with insufficient space for an object of type 'char'
0x502000000054: note: pointer points here
  61 2c 20 62 00 00 00 00  00 00 00 00 00 00 00 00
              ^
    #0 0xb7c650251cd8 in pk_header_join /build/src/src/header.c:175
    #1 0xb7c65024bf58 in cmd_header /build/src/cli/parsekit.c:109
    #3 0xff63caf12258  (/lib/aarch64-linux-gnu/libc.so.6+0x22258) (BuildId: 5f3926d9963ff284b8173bf3601bbb00c3abad16)
"""


def test_ubsan_object_size_report_is_an_out_of_bounds_access() -> None:
    crash = parse_output(UBSAN_OBJECT_SIZE)
    assert crash is not None
    assert crash.error_type == "out-of-bounds"
    assert crash.frames[0].function == "pk_header_join" and crash.frames[0].line == 175


@pytest.mark.parametrize(
    ("message", "error_type"),
    [
        (
            "signed integer overflow: 1 + 2 cannot be represented in type 'int'",
            "signed-integer-overflow",
        ),
        ("index 7 out of bounds for type 'int [5]'", "out-of-bounds"),
        ("member access within null pointer of type 'struct pk_url'", "null-dereference"),
        (
            "load of misaligned address 0x1 for type 'int', which requires 4 byte alignment",
            "misaligned-access",
        ),
        ("load of value 7, which is not a valid value for type 'bool'", "invalid-value"),
        ("division by zero", "division-by-zero"),
        ("shift exponent 70 is too large for 32-bit type 'int'", "shift-out-of-bounds"),
    ],
)
def test_ubsan_messages_are_reduced_to_a_stable_error_type(message: str, error_type: str) -> None:
    crash = parse_output(f"/build/src/src/url.c:9:3: runtime error: {message}\n")
    assert crash is not None and crash.error_type == error_type


def test_tsan_data_race_uses_the_first_stack() -> None:
    crash = parse_output(TSAN)
    assert crash is not None
    assert crash.tool == "ThreadSanitizer"
    assert crash.error_type == "data-race"
    assert crash.frames[0].function == "worker"
    assert crash.frames[0].path == "/build/src/src/pool.c"
    assert crash.frames[0].line == 41


def test_python_traceback_puts_the_innermost_frame_first() -> None:
    crash = parse_output(PY_TRACEBACK)
    assert crash is not None
    assert crash.tool == "python"
    assert crash.error_type == "RecursionError"
    assert [f.function for f in crash.frames[:2]] == ["_expand", "interpolate"]
    assert crash.frames[0].path == "/usr/local/lib/python3.12/site-packages/kvconf/interp.py"
    assert crash.frames[0].line == 24
    assert crash.frames[-1].function == "<module>"


def test_output_without_a_report_is_not_a_crash() -> None:
    assert parse_output("hello\nscheme: http\n") is None
    assert parse_output("") is None
    assert parse_output("AddressSanitizer is a fast memory error detector") is None


def test_signal_names() -> None:
    assert signal_name(139) == "SIGSEGV"
    assert signal_name(134) == "SIGABRT"
    assert signal_name(136) == "SIGFPE"
    assert signal_name(137) == "SIGKILL"
    assert signal_name(0) is None
    assert signal_name(1) is None
    assert signal_name(None) is None


def test_error_types_match_exact_and_related_names() -> None:
    assert error_types_match("heap-buffer-overflow", "heap-buffer-overflow")
    assert error_types_match("heap-buffer-overflow", "buffer-overflow")
    assert error_types_match("stack-buffer-overflow", "out-of-bounds")
    assert error_types_match("SEGV", "null-dereference")
    assert error_types_match("signed-integer-overflow", "integer-overflow")
    assert error_types_match("RecursionError", "RecursionError")
    assert not error_types_match("heap-use-after-free", "heap-buffer-overflow")
    assert not error_types_match("double-free", "heap-use-after-free")
    assert not error_types_match("data-race", "heap-buffer-overflow")


def test_repo_path_maps_build_paths_and_installed_python_paths() -> None:
    assert repo_path("/build/src/src/header.c", FILES) == "src/header.c"
    assert repo_path("/build/src/cli/parsekit.c", FILES) == "cli/parsekit.c"
    assert (
        repo_path("/usr/local/lib/python3.12/site-packages/kvconf/interp.py", FILES)
        == "src/kvconf/interp.py"
    )


def test_repo_path_rejects_system_and_poc_paths() -> None:
    assert repo_path("/work/poc/poc.c", FILES) is None
    assert repo_path("/usr/include/x86_64-linux-gnu/bits/string_fortified.h", FILES) is None
    assert repo_path("../sysdeps/nptl/libc_start_call_main.h", FILES) is None
    assert repo_path("/build/src/src/missing.c", FILES) is None
    assert repo_path(None, FILES) is None


def test_top_project_frame_skips_runtime_and_poc_frames() -> None:
    crash = parse_output(ASAN_MEMCPY)
    assert crash is not None
    top = top_project_frame(crash, FILES)
    assert top is not None
    frame, path = top
    assert (frame.function, path, frame.line) == ("pk_buf_append", "src/buf.c", 44)


def test_top_project_frame_is_none_when_only_the_poc_is_involved() -> None:
    crash = parse_output(ASAN_DOUBLE_FREE)
    assert crash is not None
    assert top_project_frame(crash, FILES) is None


def test_hostile_lines_do_not_make_the_parser_slow() -> None:
    import time

    started = time.monotonic()
    for text in (
        "==1==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x1\n    #0 0x1 in f "
        + " " * 200_000
        + "!\n",
        'Traceback (most recent call last):\n  File "x.py", line 1, in f'
        + " " * 200_000
        + "x\nValueError: y\n",
        "#" + " " * 300_000 + "\n" * 3 + "x:" * 100_000,
    ):
        parse_output(text)
    assert time.monotonic() - started < 2.0
