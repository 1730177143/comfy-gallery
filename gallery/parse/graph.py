"""Resolve values inside a ComfyUI API-format prompt graph.

The ``prompt`` chunk ComfyUI writes is the graph that actually executed, but it
stores connections rather than values: ``noise_seed`` may be ``["649", 0]``, a
link to a Seed node, and a width may come out of a math node. Following those
links is what turns a node dump into a readable recipe, and it is also why this
module exists separately from the extractors that use it.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

# Widget keys checked first when a link has to collapse to one scalar. Ordered so
# a Seed node reports its seed rather than whichever key happens to come first.
_SCALAR_PREFERENCE = (
    "value",
    "seed",
    "noise_seed",
    "int",
    "float",
    "number",
    "text",
    "string",
    "width",
    "height",
)

# Inputs walked when hunting for the text that feeds a conditioning chain.
_CONDITIONING_KEYS = (
    "conditioning",
    "positive",
    "negative",
    "conditioning_1",
    "conditioning_2",
    "conditioning_to",
    "conditioning_from",
    "cond",
    "positive_cond",
    "negative_cond",
    "guider",
)

_TEXT_KEYS = ("text", "text_a", "string", "value", "prompt", "wildcard_text")

_MAX_DEPTH = 32


def as_number(value: Any) -> float | int | None:
    """Coerce a scalar to a number, rejecting bools and non-numeric strings."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def as_text(value: Any, limit: int = 20000) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    return text[:limit]


class PromptGraph:
    """Read-only view over one API-format prompt."""

    def __init__(self, prompt: dict[str, Any]) -> None:
        self.nodes: dict[str, dict[str, Any]] = {
            str(key): value
            for key, value in (prompt or {}).items()
            if isinstance(value, dict)
        }

    # -- identity ---------------------------------------------------------

    @staticmethod
    def is_link(value: Any) -> bool:
        return (
            isinstance(value, (list, tuple))
            and len(value) == 2
            and isinstance(value[1], int)
            and isinstance(value[0], (str, int))
        )

    def node(self, node_id: str) -> dict[str, Any] | None:
        return self.nodes.get(str(node_id))

    def class_of(self, node_id: str) -> str:
        node = self.node(node_id)
        return str((node or {}).get("class_type") or "")

    def title_of(self, node_id: str) -> str:
        node = self.node(node_id) or {}
        meta = node.get("_meta")
        if isinstance(meta, dict):
            title = meta.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        return self.class_of(node_id)

    def inputs_of(self, node_id: str) -> dict[str, Any]:
        return (self.node(node_id) or {}).get("inputs") or {}

    def iter_nodes(self) -> Iterator[tuple[str, dict[str, Any]]]:
        def order(key: str) -> tuple[int, str]:
            return (int(key), "") if key.isdigit() else (1 << 30, key)

        for node_id in sorted(self.nodes, key=order):
            yield node_id, self.nodes[node_id]

    def find(self, *needles: str, exclude: Iterable[str] = ()) -> list[tuple[str, dict[str, Any]]]:
        """Nodes whose class name contains any needle and none of ``exclude``."""
        lowered = [needle.lower() for needle in needles]
        blocked = [item.lower() for item in exclude]
        hits: list[tuple[str, dict[str, Any]]] = []
        for node_id, node in self.iter_nodes():
            class_name = str(node.get("class_type") or "").lower()
            if any(block in class_name for block in blocked):
                continue
            if any(needle in class_name for needle in lowered):
                hits.append((node_id, node))
        return hits

    # -- value resolution -------------------------------------------------

    def resolve(self, value: Any, prefer: tuple[str, ...] = (), depth: int = 0,
                seen: set[str] | None = None) -> Any:
        """Collapse a link to the scalar value its source node actually used."""
        if depth > _MAX_DEPTH:
            return None
        if not self.is_link(value):
            return value
        node_id = str(value[0])
        seen = set() if seen is None else seen
        if node_id in seen:
            return None
        seen.add(node_id)
        inputs = self.inputs_of(node_id)
        for key in (*prefer, *_SCALAR_PREFERENCE):
            candidate = inputs.get(key)
            if candidate is not None and not self.is_link(candidate) and isinstance(
                candidate, (int, float, str, bool)
            ):
                return candidate
        for candidate in inputs.values():
            if not self.is_link(candidate) and isinstance(candidate, (int, float, str, bool)):
                return candidate
        for candidate in inputs.values():
            if self.is_link(candidate):
                got = self.resolve(candidate, prefer, depth + 1, seen)
                if got is not None:
                    return got
        return None

    def resolve_number(self, value: Any, prefer: tuple[str, ...] = ()) -> float | int | None:
        return as_number(self.resolve(value, prefer))

    def resolve_text(self, value: Any, depth: int = 0, seen: set[str] | None = None) -> str:
        if depth > _MAX_DEPTH:
            return ""
        if not self.is_link(value):
            return as_text(value)
        node_id = str(value[0])
        seen = set() if seen is None else seen
        if node_id in seen:
            return ""
        seen.add(node_id)
        inputs = self.inputs_of(node_id)
        for key in _TEXT_KEYS:
            if key not in inputs:
                continue
            candidate = inputs[key]
            if isinstance(candidate, str) and candidate.strip():
                return as_text(candidate)
            if self.is_link(candidate):
                nested = self.resolve_text(candidate, depth + 1, seen)
                if nested:
                    return nested
        for candidate in inputs.values():
            if self.is_link(candidate):
                nested = self.resolve_text(candidate, depth + 1, seen)
                if nested:
                    return nested
        return ""

    # -- conditioning -----------------------------------------------------

    def direct_text(self, node: dict[str, Any]) -> str:
        """The text a single node contributes, without following conditioning."""
        inputs = node.get("inputs") or {}
        class_name = str(node.get("class_type") or "").lower()
        keys = _TEXT_KEYS if "encode" in class_name else tuple(
            dict.fromkeys((*_TEXT_KEYS, "text"))
        )
        for key in keys:
            candidate = inputs.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return as_text(candidate)
            if self.is_link(candidate):
                nested = self.resolve_text(candidate)
                if nested:
                    return nested
        return ""

    def collect_texts(self, value: Any) -> list[str]:
        """Every prompt text reachable through a conditioning chain."""
        collected: list[str] = []
        self._walk_text(value, 0, set(), collected)
        unique: list[str] = []
        for text in collected:
            if text and text not in unique:
                unique.append(text)
        return unique

    def _walk_text(self, value: Any, depth: int, seen: set[str], out: list[str]) -> None:
        if depth > _MAX_DEPTH:
            return
        if not self.is_link(value):
            text = as_text(value)
            if text:
                out.append(text)
            return
        node_id = str(value[0])
        if node_id in seen:
            return
        seen.add(node_id)
        node = self.node(node_id)
        if node is None:
            return
        # ZeroOut replaces the conditioning with zeros, so whatever encoder sits
        # behind it did not contribute text to this branch.
        if "conditioningzeroout" in str(node.get("class_type") or "").lower():
            return
        direct = self.direct_text(node)
        if direct:
            out.append(direct)
            return
        inputs = node.get("inputs") or {}
        for key in _CONDITIONING_KEYS:
            if key in inputs:
                self._walk_text(inputs[key], depth + 1, seen, out)
        if out:
            return
        # Last resort: a wrapper this table does not know, so follow every link.
        for candidate in inputs.values():
            if self.is_link(candidate):
                self._walk_text(candidate, depth + 1, seen, out)
