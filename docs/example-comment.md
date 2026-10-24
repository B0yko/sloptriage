# Example comment

This is the comment that the Action posted on a synthetic issue in this repository
([issue 1](https://github.com/B0yko/sloptriage/issues/1), opened to test the workflow and closed
afterwards), copied verbatim. The report cites functions and a file that do not exist and a line past the
end of a real file; the labels it applied were `triage:refs-failed` and `triage:needs-poc`.

---

<!-- sloptriage -->
### Reference check: 6 cited items could not be found in sloptriage at `v0.1.0`; 1 was found.

Checked against sloptriage at `v0.1.0` (`f0d7a8867146`), the version the report names.

| | Cited | Result | Evidence |
|---|---|---|---|
| ✗ | `check_everything()` | no definition was found in sloptriage at `v0.1.0` |  |
| ✗ | `src/sloptriage/refs_core.py` | no such file in sloptriage at `v0.1.0` |  |
| ✗ | `verify_all_claims()` at `src/sloptriage/refs.py:9999` | line 9999 is past the end of `src/sloptriage/refs.py` (929 lines) | [src/sloptriage/refs.py](https://github.com/b0yko/sloptriage/blob/f0d7a8867146ffee18cc57364f6fd64c112b6a68/src/sloptriage/refs.py) |
| ✗ | `src/sloptriage/refs.py:9999` | line 9999 is past the end of `src/sloptriage/refs.py` (929 lines) | [src/sloptriage/refs.py](https://github.com/b0yko/sloptriage/blob/f0d7a8867146ffee18cc57364f6fd64c112b6a68/src/sloptriage/refs.py) |
| ✗ | `verify_all_claims()` | no definition was found in sloptriage at `v0.1.0` |  |
| ✗ | stack frame 1: `check_everything()` at `src/sloptriage/refs_core.py:212` | no such file in sloptriage at `v0.1.0` |  |

<details><summary>Items that were found (1)</summary>

| | Cited | Result | Evidence |
|---|---|---|---|
| ✓ | `src/sloptriage/refs.py` | exists | [src/sloptriage/refs.py](https://github.com/b0yko/sloptriage/blob/f0d7a8867146ffee18cc57364f6fd64c112b6a68/src/sloptriage/refs.py) |

</details>

**What would help**

- A minimal reproducer: a command line, a small program or an input file.
- Check the names and line numbers marked ✗ or ⚠ against `v0.1.0`; where the Evidence column has a link, it points at that code.
- If a name or file marked ✗ belongs to your own test script, attach the script or paste its content.

<details><summary>Reproduction template</summary>

```text
Version: <the sloptriage version you tested (for example its --version output) or a commit>
Steps to reproduce:
1. ...
Expected and actual result:
Sanitizer output or stack trace (if any):
```

</details>

<sub>Automated reference check by [sloptriage](https://github.com/B0yko/sloptriage) 0.1.0. It compares the files, functions, lines and stack frames a report cites with the code; it does not judge whether the issue is real. If a result looks wrong, reply here: the check can miss code defined by macros or generated at build time. This comment is updated when the report is edited.</sub>
