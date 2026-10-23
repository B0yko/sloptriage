"""Definitions with line spans, from tree-sitter grammars (one wheel per language)."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cache
from typing import Any

from tree_sitter import Language, Node, Parser

EXTENSIONS: dict[str, str] = {
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".c++": "cpp",
    ".hh": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".inl": "cpp",
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".go": "go",
    ".rs": "rust",
}

FUNCTION_KINDS = frozenset({"function", "method"})
MAX_PARSE_BYTES = 1_500_000


@dataclass(frozen=True)
class Definition:
    name: str
    kind: str
    start: int  # 1-based, inclusive
    end: int  # 1-based, inclusive
    qual: str = ""


def language_for(path: str) -> str | None:
    dot = path.rfind(".")
    if dot < 0 or "/" in path[dot:]:
        return None
    return EXTENSIONS.get(path[dot:].lower())


_GRAMMARS: dict[str, tuple[str, str]] = {
    "c": ("tree_sitter_c", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "python": ("tree_sitter_python", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
}


@cache
def _language(lang: str) -> Language:
    import importlib

    module_name, attr = _GRAMMARS[lang]
    module = importlib.import_module(module_name)
    return Language(getattr(module, attr)())


@cache
def parser_for(lang: str) -> Parser:
    return Parser(_language(lang))


def parse(lang: str, content: bytes) -> Node:
    return parser_for(lang).parse(content).root_node


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", "replace")


def _span(node: Node) -> tuple[int, int]:
    start, end = node.start_point[0] + 1, node.end_point[0] + 1
    if node.end_point[1] == 0 and end > start:
        end -= 1  # the node ends with a newline (preprocessor lines)
    return start, end


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


# -- C and C++ ----------------------------------------------------------------
_C_DECLARATOR_WRAPPERS = {
    "pointer_declarator",
    "parenthesized_declarator",
    "attributed_declarator",
    "reference_declarator",
    "array_declarator",
    "init_declarator",
}


def _c_declarator_name(node: Node | None) -> tuple[str, str, bool]:
    """Return (name, qualified name, is_function) for a C/C++ declarator."""
    is_function = False
    while node is not None:
        if node.type == "function_declarator":
            is_function = True
            node = node.child_by_field_name("declarator")
            continue
        if node.type in _C_DECLARATOR_WRAPPERS:
            inner = node.child_by_field_name("declarator")
            if inner is None:
                inner = next(
                    (
                        c
                        for c in node.named_children
                        if "declarator" in c.type or c.type.endswith("identifier")
                    ),
                    None,
                )
            node = inner
            continue
        if node.type in ("identifier", "field_identifier", "type_identifier"):
            name = _text(node)
            return name, name, is_function
        if node.type in ("qualified_identifier", "destructor_name", "operator_name"):
            full = _text(node)
            short = re.split(r"::", full)[-1].lstrip("~").strip()
            return short, full, is_function
        return "", "", is_function
    return "", "", is_function


def _c_defs(root: Node, cpp: bool) -> Iterator[Definition]:
    for node in _walk(root):
        t = node.type
        if t == "function_definition":
            name, qual, _ = _c_declarator_name(node.child_by_field_name("declarator"))
            if name:
                kind = "method" if "::" in qual else "function"
                s, e = _span(node)
                yield Definition(name, kind, s, e, qual)
        elif t in ("preproc_def", "preproc_function_def"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                s, e = _span(node)
                yield Definition(_text(name_node), "macro", s, e)
        elif t in ("struct_specifier", "union_specifier", "enum_specifier", "class_specifier"):
            name_node = node.child_by_field_name("name")
            if name_node is not None and node.child_by_field_name("body") is not None:
                s, e = _span(node)
                name = _text(name_node)
                yield Definition(name.split("::")[-1], "type", s, e, name)
        elif t == "type_definition":
            s, e = _span(node)
            for decl in node.children_by_field_name("declarator"):
                name, qual, _ = _c_declarator_name(decl)
                if name:
                    yield Definition(name, "type", s, e, qual)
        elif t == "enumerator":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                s, e = _span(node)
                yield Definition(_text(name_node), "constant", s, e)
        elif t in ("declaration", "field_declaration") and _is_top_level_or_class(node):
            s, e = _span(node)
            for decl in node.children_by_field_name("declarator"):
                name, qual, is_fn = _c_declarator_name(decl)
                if not name:
                    continue
                if is_fn:
                    yield Definition(name, "declaration", s, e, qual)
                elif node.type == "declaration":
                    yield Definition(name, "variable", s, e, qual)
        elif cpp and t == "namespace_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                s, e = _span(node)
                yield Definition(_text(name_node), "namespace", s, e)
        elif cpp and t == "alias_declaration":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                s, e = _span(node)
                yield Definition(_text(name_node), "type", s, e)


def _is_top_level_or_class(node: Node) -> bool:
    parent = node.parent
    while parent is not None and parent.type in (
        "linkage_specification",
        "declaration_list",
        "preproc_if",
        "preproc_ifdef",
        "preproc_else",
        "preproc_elif",
        "template_declaration",
        "namespace_definition",
        "field_declaration_list",
        "class_specifier",
        "struct_specifier",
    ):
        parent = parent.parent
    return parent is None or parent.type == "translation_unit"


# -- Python -------------------------------------------------------------------
def _py_defs(root: Node) -> Iterator[Definition]:
    def visit(node: Node, cls: str) -> Iterator[Definition]:
        for child in node.named_children:
            target = child
            if child.type == "decorated_definition":
                inner = child.child_by_field_name("definition")
                if inner is None:
                    continue
                target = inner
            if target.type in ("function_definition", "async_function_definition"):
                name = _text(target.child_by_field_name("name"))
                s, e = _span(child)
                yield Definition(
                    name, "method" if cls else "function", s, e, f"{cls}.{name}" if cls else name
                )
                body = target.child_by_field_name("body")
                if body is not None:
                    yield from visit(body, "")
            elif target.type == "class_definition":
                name = _text(target.child_by_field_name("name"))
                s, e = _span(child)
                yield Definition(name, "type", s, e, name)
                body = target.child_by_field_name("body")
                if body is not None:
                    yield from visit(body, name)
            elif child.type == "expression_statement" and node.type == "module":
                for assign in child.named_children:
                    if assign.type == "assignment":
                        left = assign.child_by_field_name("left")
                        if left is not None and left.type == "identifier":
                            s, e = _span(assign)
                            yield Definition(_text(left), "variable", s, e)
            elif child.type in (
                "if_statement",
                "try_statement",
                "block",
                "else_clause",
                "except_clause",
            ):
                yield from visit(child, cls)

    yield from visit(root, "")


# -- JavaScript and TypeScript ---------------------------------------------------
_JS_NAMED = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "type",
    "abstract_class_declaration": "type",
    "interface_declaration": "type",
    "type_alias_declaration": "type",
    "enum_declaration": "type",
    "method_definition": "method",
    "function_signature": "declaration",
}


def _js_defs(root: Node) -> Iterator[Definition]:
    for node in _walk(root):
        kind = _JS_NAMED.get(node.type)
        if kind:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                s, e = _span(node)
                yield Definition(_text(name_node), kind, s, e)
        elif node.type == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if name_node is None or name_node.type != "identifier":
                continue
            s, e = _span(node)
            if value is not None and value.type in (
                "arrow_function",
                "function_expression",
                "function",
            ):
                yield Definition(_text(name_node), "function", s, e)
            elif _js_top_level(node):
                yield Definition(_text(name_node), "variable", s, e)


def _js_top_level(node: Node) -> bool:
    parent = node.parent
    while parent is not None and parent.type in (
        "lexical_declaration",
        "variable_declaration",
        "export_statement",
    ):
        parent = parent.parent
    return parent is None or parent.type == "program"


# -- Go ---------------------------------------------------------------------
def _go_defs(root: Node) -> Iterator[Definition]:
    for node in _walk(root):
        t = node.type
        if t in ("function_declaration", "method_declaration"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                s, e = _span(node)
                yield Definition(
                    _text(name_node), "function" if t == "function_declaration" else "method", s, e
                )
        elif t in ("type_spec", "type_alias"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                s, e = _span(node)
                yield Definition(_text(name_node), "type", s, e)
        elif t in ("const_spec", "var_spec"):
            s, e = _span(node)
            for name_node in node.children_by_field_name("name"):
                yield Definition(
                    _text(name_node), "constant" if t == "const_spec" else "variable", s, e
                )


# -- Rust -------------------------------------------------------------------
_RUST_NAMED = {
    "function_item": "function",
    "function_signature_item": "declaration",
    "struct_item": "type",
    "enum_item": "type",
    "union_item": "type",
    "trait_item": "type",
    "type_item": "type",
    "const_item": "constant",
    "static_item": "variable",
    "mod_item": "namespace",
    "macro_definition": "macro",
}


def _rust_defs(root: Node) -> Iterator[Definition]:
    for node in _walk(root):
        kind = _RUST_NAMED.get(node.type)
        if not kind:
            continue
        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        s, e = _span(node)
        if kind == "function" and _inside(node, "impl_item"):
            kind = "method"
        yield Definition(_text(name_node), kind, s, e)


def _inside(node: Node, ancestor_type: str) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == ancestor_type:
            return True
        parent = parent.parent
    return False


_EXTRACTORS: dict[str, Callable[[Node], Iterator[Definition]]] = {
    "c": lambda root: _c_defs(root, cpp=False),
    "cpp": lambda root: _c_defs(root, cpp=True),
    "python": _py_defs,
    "javascript": _js_defs,
    "typescript": _js_defs,
    "tsx": _js_defs,
    "go": _go_defs,
    "rust": _rust_defs,
}

_COMMENT_TYPES = {"comment", "line_comment", "block_comment"}


def definitions(lang: str, content: bytes) -> list[Definition]:
    if len(content) > MAX_PARSE_BYTES:
        return []
    root = parse(lang, content)
    found = list(_EXTRACTORS[lang](root))
    if lang in ("c", "cpp"):
        from sloptriage.index import cfallback

        found = cfallback.merge(found, content)
    seen: set[tuple[str, str, int]] = set()
    out: list[Definition] = []
    for d in found:
        key = (d.name, d.kind, d.start)
        if d.name and key not in seen:
            seen.add(key)
            out.append(d)
    return out


def comment_or_blank_lines(lang: str | None, content: bytes) -> set[int]:
    """1-based numbers of lines that hold only whitespace or comments."""
    lines = content.split(b"\n")
    blank = {i + 1 for i, line in enumerate(lines) if not line.strip()}
    if lang is None or len(content) > MAX_PARSE_BYTES:
        return blank
    root = parse(lang, content)
    covered: dict[int, list[tuple[int, int]]] = {}
    for node in _walk(root):
        if node.type in _COMMENT_TYPES:
            (sr, sc), (er, ec) = node.start_point, node.end_point
            for row in range(sr, er + 1):
                start = sc if row == sr else 0
                end = ec if row == er else len(lines[row]) if row < len(lines) else 0
                covered.setdefault(row + 1, []).append((start, end))
    result = set(blank)
    for lineno, ranges in covered.items():
        raw = bytearray(lines[lineno - 1]) if lineno - 1 < len(lines) else bytearray()
        for start, end in ranges:
            raw[start:end] = b" " * (end - start)
        if not raw.strip():
            result.add(lineno)
    return result


_IDENT_RE = re.compile(rb"[A-Za-z_][A-Za-z0-9_]{1,80}")


def identifiers(content: bytes) -> set[str]:
    return {m.decode("ascii") for m in _IDENT_RE.findall(content)}


def has_errors(lang: str, content: bytes) -> bool:
    root: Any = parse(lang, content)
    return bool(root.has_error)
