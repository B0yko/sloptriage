"""Verdict JSON, the Markdown card, terminal text, the reporter checklist and labels.

Every renderer works from the verdict dictionary alone, so the Action's
``post`` job can render a card from a downloaded, schema-validated JSON file
without touching the report. Strings that come from the report are always
passed through :func:`code` before they reach Markdown.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from sloptriage import __version__
from sloptriage.config import Config
from sloptriage.extract import Claim
from sloptriage.paths import bundled
from sloptriage.verdict import CheckResult, needs

MARKER = "<!-- sloptriage -->"
MAX_COMMENT = 60_000
MAX_ROWS = 40
MAX_OUTPUT_LINES = 30
REPO_URL = "https://github.com/B0yko/sloptriage"

_BIDI = dict.fromkeys(map(ord, "‪‫‬‭‮⁦⁧⁨⁩‎‏؜"))
_SEVERITY_ORDER = {"hard": 0, "soft": 1, "ok": 2, "neutral": 3}


# -- escaping ----------------------------------------------------------------------
def clean(text: str, limit: int = 120) -> str:
    """Remove control and bidi characters, collapse whitespace, truncate."""
    text = text.translate(_BIDI)
    text = "".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def code(text: str, limit: int = 80) -> str:
    """A report-derived string as an inline code span: no HTML, links, images or mentions."""
    value = clean(text, limit).replace("`", "'").replace("|", "¦")
    if not value:
        return "` `"
    return f"`{value}`"


def neutralise_mentions(text: str) -> str:
    return re.sub(r"@(?=[A-Za-z0-9-])", "@​", text)


def fenced(text: str, max_lines: int = MAX_OUTPUT_LINES, width: int = 200) -> str:
    lines = [clean(ln, width) if ln.strip() else "" for ln in text.splitlines()]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines)"]
    body = "\n".join(lines)
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}text\n{body}\n{fence}"


def _project_link(verdict: dict[str, Any], url: str) -> bool:
    repo = (verdict.get("project") or {}).get("repository") or ""
    m = re.match(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", repo)
    if not m:
        return False
    prefix = f"https://github.com/{m.group(1)}/{m.group(2)}/blob/"
    return (
        url.startswith(prefix)
        and re.fullmatch(r"[\w./#:-]+", url[len("https://github.com/") :]) is not None
    )


# -- building the verdict ------------------------------------------------------------
def _claim_value(c: Claim) -> str:
    if c.kind in ("quote", "poc"):
        return c.poc_kind or c.lang or c.kind
    return str(c.value)


def build_verdict(
    result: CheckResult, cfg: Config, reproduction: dict[str, Any] | None = None
) -> dict[str, Any]:
    agg = result.aggregate
    res = result.resolution
    claims = []
    for o in sorted(agg.outcomes, key=lambda o: (_SEVERITY_ORDER[o.severity], o.claim.start)):
        c = o.claim
        if c.kind in ("cve", "cwe", "sanitizer_claim") and not o.findings:
            continue
        if c.kind == "version":
            continue
        claims.append(
            {
                "kind": c.kind,
                "confidence": c.confidence,
                "value": clean(_claim_value(c), 300),
                "source": c.source[:40],
                "path": clean(c.path, 300) if c.path else None,
                "line": c.line,
                "line_end": c.line_end,
                "function": clean(c.function, 200) if c.function else None,
                "frame_index": c.frame_index,
                "trace": c.trace,
                "lang": c.lang,
                "lines": len((c.text or "").splitlines()) if c.kind in ("quote", "poc") else None,
                "span": [c.start, c.end],
                "findings": [_finding_json(f) for f in o.findings[:8]],
            }
        )
        if len(claims) >= 400:
            break
    chain = [_finding_json(f) for f in result.findings if f.check == "frame_chain"][:100]
    need = needs(result)
    verdict: dict[str, Any] = {
        "schema": "sloptriage-verdict/1",
        "tool": {"name": "sloptriage", "version": __version__},
        "report": {
            "source": result.report.source,
            "id": clean(result.report.id, 300),
            "url": result.report.url,
            "created_at": result.report.created_at,
        },
        "project": {"name": cfg.project or "the project", "repository": result.repository},
        "resolution": {
            "ref": res.ref_label,
            "commit": res.commit,
            "assumed": res.assumed,
            "reason": res.reason,
            "versions": [
                {
                    "claimed": clean(v.claim.value, 80),
                    "status": v.status,
                    "ref": v.ref,
                    "nearest": v.nearest[:5],
                }
                for v in res.findings[:20]
            ],
        },
        "references": {
            "class": agg.cls,
            "hard": agg.hard,
            "soft": agg.soft,
            "verified": agg.verified,
            "checked": agg.checked,
            "verified_share": round(agg.share, 4) if agg.share is not None else None,
            "thresholds": vars(cfg.thresholds),
        },
        "claims": claims,
        "chain": chain,
        "reproduction": reproduction,
        "needs": need,
        "labels": [],
        "comment": False,
        "policy": {"mode": cfg.comment.mode, "managed_labels": sorted(set(cfg.labels.values()))},
        "timing": {
            "seconds": round(result.timings["total"], 3),
            "index_cached": result.index_cached,
        },
    }
    verdict["labels"] = labels_for(verdict, cfg)
    verdict["comment"] = should_comment(verdict, cfg)
    return verdict


def _finding_json(f: Any) -> dict[str, Any]:
    detail: dict[str, Any] = {}
    for key, value in list(f.detail.items())[:24]:
        if isinstance(value, str):
            detail[key] = clean(value, 300)
        elif isinstance(value, list):
            detail[key] = [clean(x, 300) if isinstance(x, str) else x for x in value[:12]]
        else:
            detail[key] = value
    return {
        "check": f.check,
        "status": f.status,
        "severity": f.severity,
        "detail": detail,
        "evidence": f.evidence[:4],
    }


def labels_for(verdict: dict[str, Any], cfg: Config) -> list[str]:
    names = cfg.labels
    out = [names[verdict["references"]["class"]]] if verdict["references"]["class"] in names else []
    for need in verdict.get("needs", []):
        out.append(names[need])
    return out


def should_comment(verdict: dict[str, Any], cfg: Config) -> bool:
    if cfg.comment.mode == "label":
        return False
    when = set(cfg.comment.when)
    if "always" in when:
        return True
    return verdict["references"]["class"] in when or bool(when & set(verdict.get("needs", [])))


def validate_verdict(verdict: Any) -> None:
    import jsonschema

    schema = json.loads(bundled("schemas", "verdict-v1.json").read_text(encoding="utf-8"))
    jsonschema.validate(verdict, schema)


# -- sentences -----------------------------------------------------------------------
def _ref(verdict: dict[str, Any]) -> str:
    return code(verdict["resolution"]["ref"], 60)


def describe(claim: dict[str, Any]) -> str:
    kind = claim["kind"]
    if kind == "path":
        return code(claim["path"] or claim["value"])
    if kind == "line":
        end = f"-{claim['line_end']}" if claim.get("line_end") else ""
        return code(f"{claim['path']}:{claim['line']}{end}")
    if kind == "symbol":
        return code(claim["value"] + ("()" if "call" in claim.get("source", "") else ""))
    if kind == "frame":
        idx = claim.get("frame_index")
        where = f"{claim['path']}:{claim['line']}" if claim.get("path") else ""
        head = f"frame #{idx} " if idx is not None and claim.get("trace") is not None else ""
        return (
            f"{head}{code((claim.get('function') or '?') + '()')} at {code(where)}"
            if where
            else f"{head}{code(claim.get('function') or '?')}"
        )
    if kind == "quote":
        where = f" from {code(claim['path'])}" if claim.get("path") else ""
        return f"quoted code ({claim.get('lines') or 0} lines){where}"
    if kind == "poc":
        return f"PoC ({clean(claim['value'], 20)})"
    return code(claim["value"])


def explain(finding: dict[str, Any], claim: dict[str, Any], verdict: dict[str, Any]) -> str:
    d = finding.get("detail", {})
    status: str = str(finding["status"])
    project = clean(verdict["project"]["name"], 60)
    ref = code(d.get("ref") or verdict["resolution"]["ref"], 60)
    check = finding["check"]
    if check == "path":
        return {
            "found": "exists",
            "found_moved": (
                f"not at {code(d.get('primary_ref') or verdict['resolution']['ref'], 60)}; exists at {ref}"
                if d.get("other_version")
                else f"no such path; {code(d.get('resolved', ''))} exists"
            ),
            "not_found": f"{code(d.get('path', claim['value']))} does not exist in {project} at {ref}",
            "outside_project": "outside the project tree",
            "other_repository": f"points to another repository ({code(d.get('repository', ''))})",
        }.get(status, status)
    if check == "symbol":
        return {
            "defined": f"defined in {code(d.get('path', ''))}",
            "referenced_only": f"used in {project}, not defined there",
            "defined_at_other_version": f"not defined at {code(d.get('primary_ref') or verdict['resolution']['ref'], 60)}; defined at {ref}",
            "external": "standard-library or third-party name",
            "defined_by_poc": "defined by the report's own PoC",
            "not_found": f"{code(d.get('symbol', claim['value']))} is not defined anywhere in {project} at {ref}",
        }.get(status, status)
    if check == "line":
        line, total, path = d.get("line"), d.get("lines"), code(d.get("path", ""))
        return {
            "in_range": f"line {line} of {path} ({total} lines)",
            "blank_or_comment": f"line {line} of {path} is blank or a comment",
            "out_of_range": f"line {line} is past the end of {path} ({total} lines)",
            "in_range_at_other_version": f"past the end at {ref} ({total} lines); in range at {code(d.get('other_ref', ''), 60)}",
        }.get(status, status)
    if check == "frame":
        fn = code((d.get("function") or claim.get("function") or "?") + "()")
        idx = claim.get("frame_index")
        head = (
            f"frame #{idx} names {fn}"
            if idx is not None and claim.get("trace") is not None
            else f"the report names {fn}"
        )
        if status == "consistent":
            return f"line {d.get('line')} is inside {fn}"
        if status == "outside_function":
            actual = d.get("actual")
            where = f"inside {code(actual + '()')}" if actual else "not inside it"
            return f"{head}, but line {d.get('line')} is {where}"
        if status == "function_not_in_file":
            others = d.get("defined_in") or []
            tail = f" (it is defined in {code(others[0])})" if others else ""
            return f"{fn} is not defined in {code(d.get('path', ''))}{tail}"
        if status == "consistent_at_other_version":
            return f"consistent at {code(d.get('other_ref', ''), 60)}, not at {ref}"
        if status == "outside_project":
            return "outside the project (runtime, system library or the reporter's own code)"
        return status
    if check == "quote":
        if status == "exact":
            return "found verbatim in the code"
        if status == "approximate":
            return f"found with small differences ({round(100 * float(d.get('similarity', 0)))}% of lines)"
        if status == "found_at_other_version":
            return f"not at {code(d.get('primary_ref') or verdict['resolution']['ref'], 60)}; found at {ref}"
        if status == "not_found":
            share = round(100 * float(d.get("best_similarity", 0)))
            return f"this code does not appear in {project} at {ref} (at most {share}% of its lines match)"
        return "too short to check"
    if check == "poc":
        return {
            "calls_project": f"uses {project} code",
            "no_project_reference": f"does not use any function or header of {project}",
            "not_checked": "not checked statically",
        }.get(status, status)
    return str(status)


def _mark(severity: str) -> str:
    return {"hard": "✗", "soft": "⚠", "ok": "✓", "neutral": "·"}[severity]


def _worst(claim: dict[str, Any]) -> dict[str, Any] | None:
    fs = claim.get("findings") or []
    if not fs:
        return None
    worst: dict[str, Any] = sorted(fs, key=lambda f: _SEVERITY_ORDER[f["severity"]])[0]
    return worst


def summary_line(verdict: dict[str, Any]) -> str:
    r = verdict["references"]
    project = clean(verdict["project"]["name"], 60)
    ref = _ref(verdict)
    cls = r["class"]
    if cls == "refs_failed":
        return (
            f"{r['hard']} of {r['checked']} cited items could not be found in {project} at {ref}."
        )
    if cls == "refs_mixed":
        return f"{r['verified']} of {r['checked']} cited items check out at {ref}; {r['checked'] - r['verified']} need a closer look."
    if cls == "refs_verified":
        return f"All {r['verified']} cited files, functions and lines exist in {project} at {ref}. This confirms the references, not the issue."
    if cls == "refs_thin":
        return f"The {r['verified']} cited item(s) check out at {ref}, but the report cites little that can be checked."
    return "The report cites no file, function, line or stack frame that can be checked."


def _resolution_sentence(verdict: dict[str, Any]) -> str:
    res = verdict["resolution"]
    commit = code(res["commit"][:12])
    project = clean(verdict["project"]["name"], 60)
    reason = {
        "claimed": "the version the report names",
        "explicit": "the ref given on the command line",
        "sha": "the commit the report names",
        "dev_version": "a development version: the default branch as of the report date",
        "no_version": "no version given: the default branch as of the report date",
        "version_not_found": "the named version does not exist: the default branch as of the report date",
        "latest": "the default branch",
    }[res["reason"]]
    text = f"Checked against {project} at {_ref(verdict)} ({commit}), {reason}."
    missing = [v for v in res.get("versions", []) if v["status"] == "not_found"]
    for v in missing[:2]:
        near = ", ".join(code(n, 40) for n in v.get("nearest", [])[:3])
        text += f" Version {code(v['claimed'], 40)} was never tagged" + (
            f" (nearest: {near})." if near else "."
        )
    return text


def _repro_lines(verdict: dict[str, Any]) -> list[str]:
    repro = verdict.get("reproduction")
    if not repro:
        return []
    v = repro["verdict"]
    text = {
        "reproduced": "the PoC crashes where the report says",
        "crashed_elsewhere": "the PoC crashes, but not in the way or place the report describes",
        "not_reproduced": "no crash in three clean runs",
        "poc_build_failed": "the PoC did not compile against the project",
        "poc_missing": "no PoC found in the report",
        "poc_unsupported": "the PoC needs something the sandbox does not provide",
        "build_failed": "the project did not build in the sandbox (an infrastructure problem, not the report's)",
        "timeout": "the PoC ran into the time limit",
        "flaky": "runs disagreed",
    }[v]
    lines = [f"**Reproduction:** {text}."]
    if repro.get("reason"):
        lines[0] = lines[0][:-1] + f": {clean(repro['reason'], 200)}."
    runs = repro.get("runs") or []
    if runs:
        top = next((r for r in runs if r.get("error_type")), None)
        if top:
            lines.append(
                f"Observed {code(top['error_type'], 60)} in {code((top.get('top_frame') or '?') + '()')}."
            )
    if repro.get("output_excerpt"):
        lines += [
            "",
            "<details><summary>Sanitizer output (first 30 lines)</summary>",
            "",
            fenced(repro["output_excerpt"]),
            "",
            "</details>",
        ]
    return lines


def _help_lines(verdict: dict[str, Any]) -> list[str]:
    project = clean(verdict["project"]["name"], 60)
    items = []
    if "needs_version" in verdict.get("needs", []):
        items.append(f"- The exact {project} version or commit you tested.")
    if "needs_poc" in verdict.get("needs", []):
        items.append("- A minimal reproducer: a command line, a small program or an input file.")
    if verdict["references"]["class"] in ("refs_failed", "refs_mixed"):
        items.append(
            f"- Check the names and line numbers marked ✗ against {_ref(verdict)}; the links point at that code."
        )
    if verdict["references"]["class"] == "refs_none":
        items.append("- The file, function and line where the problem happens.")
    if not items:
        return []
    template = (
        "Version: <output of the version command, or a commit>\n"
        "Steps to reproduce:\n  1. ...\n"
        "Expected and actual result:\n"
        "Sanitizer output or stack trace (if any):"
    )
    return [
        "**What would help**",
        "",
        *items,
        "",
        "<details><summary>Reproduction template</summary>",
        "",
        fenced(template),
        "",
        "</details>",
    ]


# -- formats ---------------------------------------------------------------------------
def render_markdown(verdict: dict[str, Any]) -> str:
    rows = []
    for claim in verdict["claims"]:
        worst = _worst(claim)
        if worst is None or worst["severity"] == "neutral":
            continue
        ev = ""
        links = [u for u in worst.get("evidence", []) if _project_link(verdict, u)]
        if links:
            label = clean(re.sub(r"^.*/blob/[0-9a-f]{40}/", "", links[0]), 60).replace("]", "")
            ev = f"[{label}]({links[0]})"
        elif worst.get("evidence"):
            ev = code(worst["evidence"][0], 70)
        rows.append(
            f"| {_mark(worst['severity'])} | {describe(claim)} | {explain(worst, claim, verdict)} | {ev} |"
        )
    chain_soft = [f for f in verdict.get("chain", []) if f["status"] == "call_not_seen"]
    parts = [
        MARKER,
        f"### sloptriage: {summary_line(verdict)}",
        "",
        _resolution_sentence(verdict),
        "",
    ]
    if rows:
        shown = rows[:MAX_ROWS]
        parts += ["| | Cited | Result | Evidence |", "|---|---|---|---|", *shown]
        if len(rows) > MAX_ROWS:
            parts.append(f"| | | and {len(rows) - MAX_ROWS} more | |")
        parts.append("")
    if chain_soft:
        names = ", ".join(
            f"{code(f['detail'].get('caller', '') + '()')} → {code(f['detail'].get('callee', '') + '()')}"
            for f in chain_soft[:5]
        )
        parts += [
            f"Call chain: the caller's code does not mention the callee for {names}. Inlining, macros and function pointers can explain this, so it is informational only.",
            "",
        ]
    repro_lines = _repro_lines(verdict)
    if repro_lines:
        parts += [*repro_lines, ""]
    help_lines = _help_lines(verdict)
    if help_lines:
        parts += [*help_lines, ""]
    parts.append(
        f"<sub>Checked by [sloptriage]({REPO_URL}) {__version__}. It compares the files, functions, lines and "
        "stack frames a report cites with the code; it does not judge whether the issue is real. "
        "This comment is updated when the report is edited.</sub>"
    )
    text = neutralise_mentions("\n".join(parts)) + "\n"
    if len(text) > MAX_COMMENT:
        text = text[: MAX_COMMENT - 200] + "\n\n(truncated)\n"
    return text


def render_text(verdict: dict[str, Any]) -> str:
    def plain(s: str) -> str:
        return re.sub(r"`([^`]*)`", r"\1", s).replace("**", "")

    lines = [plain(summary_line(verdict)), plain(_resolution_sentence(verdict)), ""]
    for claim in verdict["claims"]:
        worst = _worst(claim)
        if worst is None or worst["severity"] == "neutral":
            continue
        ev = worst["evidence"][0] if worst.get("evidence") else ""
        lines.append(
            f"  {_mark(worst['severity'])} {plain(describe(claim))}: {plain(explain(worst, claim, verdict))}"
        )
        if ev:
            lines.append(f"      {ev}")
    lines.append("")
    lines += [
        plain(x)
        for x in _repro_lines(verdict)
        if not x.startswith(("<details", "</details", "```"))
    ][:3]
    lines.append(
        f"class: {verdict['references']['class']}   labels: {', '.join(verdict['labels']) or '-'}"
    )
    return "\n".join(lines) + "\n"


def render_preflight(verdict: dict[str, Any]) -> str:
    """The reporter's view: a checklist of what to fix before sending."""

    def plain(s: str) -> str:
        return re.sub(r"`([^`]*)`", r"\1", s)

    out = ["Before you send this report:", ""]
    out.append(f"  {plain(_resolution_sentence(verdict))}")
    out.append("")
    fixes = []
    for claim in verdict["claims"]:
        worst = _worst(claim)
        if worst is None:
            continue
        if worst["severity"] in ("hard", "soft"):
            fixes.append(f"  [ ] {plain(describe(claim))}: {plain(explain(worst, claim, verdict))}")
    if fixes:
        out += ["Fix or double-check:", *fixes, ""]
    ok = sum(1 for c in verdict["claims"] if (_worst(c) or {}).get("severity") == "ok")
    out.append(f"  [x] {ok} cited item(s) match the code.")
    if "needs_version" in verdict["needs"]:
        out.append("  [ ] Say which version or commit you tested.")
    if "needs_poc" in verdict["needs"]:
        out.append("  [ ] Add a minimal reproducer (command, small program or input file).")
    if verdict["references"]["class"] == "refs_none":
        out.append("  [ ] Name the file, function and line where the problem happens.")
    out.append("")
    out.append(
        "This checks that your references match the code. It cannot tell whether the issue is real."
    )
    return "\n".join(out) + "\n"
