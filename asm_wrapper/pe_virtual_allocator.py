"""PE 仮想メモリを LM0/LM1/GRF0/GRF1 へ割り付ける解決器。"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable

from .operands import GRF0, GRF1, LM0, LM1, WordWidth
from .statements import CycleStatement, Statement


_PE_VIRTUAL_RE = re.compile(
    r"__pevr(?P<root_id>\d+)_s(?P<size>\d+)_a(?P<align>\d+)"
    r"_o(?P<offset>-?\d+)_w(?P<width>l|ll)_v(?P<vector>[01])__"
)
_PHYSICAL_PE_RE = re.compile(r"^\$(?P<width>ll|l)(?P<kind>[mnrs])(?P<body>.+)$")
_PHYSICAL_DIRECT_RE = re.compile(
    r"^\$(?P<width>ll|l)(?P<kind>[mnrs])(?P<addr>\d+)(?P<vector>v)?$"
)

_KIND_CAPACITY = {
    "lm0": 4096,
    "lm1": 4096,
    "grf0": 512,
    "grf1": 512,
}


class PeVirtualAllocationError(RuntimeError):
    """仮想 PE メモリ割り付けに失敗したときの例外。"""


@dataclass(frozen=True)
class VirtualUse:
    root_id: int
    size: int
    align: int
    offset: int
    width: WordWidth
    vector: bool
    token: str

    @property
    def signature(self) -> tuple[int, WordWidth, bool]:
        return (self.offset, self.width, self.vector)

    @property
    def access_span(self) -> int:
        return 2 if self.width == WordWidth.LONG else 4


@dataclass
class CycleInfo:
    index: int
    texts: list[str]
    virtual_uses: dict[int, list[VirtualUse]]
    concrete_by_kind: dict[str, set[str]]
    has_imm: bool

    @property
    def pressure(self) -> int:
        return len(self.virtual_uses) + len(self.concrete_by_kind) + int(self.has_imm)


@dataclass
class RootState:
    root_id: int
    size: int
    align: int
    uses: list[VirtualUse]
    cycles: list[int]
    candidates: set[str]
    fixed_bases: dict[str, int]
    reasons: list[str]
    max_cycle_pressure: int = 0
    interference: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class Assignment:
    kind: str
    base: int


def resolve_pe_virtual_assignments(
    statements: tuple[Statement, ...] | list[Statement],
) -> dict[int, Assignment]:
    cycles, all_uses = _collect_cycles_and_uses(statements)
    if not all_uses:
        return {}

    roots = _build_root_states(cycles, all_uses)
    return _assign_roots(roots)


def resolve_pe_virtual_statements(
    statements: tuple[Statement, ...] | list[Statement],
) -> tuple[str, ...]:
    cycles, all_uses = _collect_cycles_and_uses(statements)
    if not all_uses:
        return tuple(statement.render() for statement in statements)

    roots = _build_root_states(cycles, all_uses)
    assignments = _assign_roots(roots)
    replacements = {
        use.token: _render_physical_use(use, assignments[use.root_id])
        for use in all_uses
    }
    return tuple(_render_statement(statement, replacements) for statement in statements)


def _collect_cycles_and_uses(
    statements: Iterable[Statement],
) -> tuple[list[CycleInfo], list[VirtualUse]]:
    cycles: list[CycleInfo] = []
    all_uses: list[VirtualUse] = []

    for statement_index, statement in enumerate(statements):
        if isinstance(statement, CycleStatement):
            texts = [item.text for item in statement.items]
        else:
            text = getattr(statement, "text", None)
            if not isinstance(text, str):
                continue
            if not _PE_VIRTUAL_RE.search(text):
                continue
            texts = [text]

        virtual_uses: dict[int, list[VirtualUse]] = {}
        concrete_by_kind: dict[str, set[str]] = {}
        has_imm = False

        for text in texts:
            parts = text.split()
            if not parts:
                continue
            if parts[0].startswith("imm"):
                has_imm = True
            for token in parts[1:]:
                base_token = token.split("/", 1)[0]
                use = _parse_virtual_use(base_token)
                if use is not None:
                    virtual_uses.setdefault(use.root_id, []).append(use)
                    all_uses.append(use)
                    continue
                kind = _physical_kind_from_token(base_token)
                if kind is not None:
                    concrete_by_kind.setdefault(kind, set()).add(base_token)

        if virtual_uses:
            cycles.append(
                CycleInfo(
                    index=statement_index,
                    texts=texts,
                    virtual_uses=virtual_uses,
                    concrete_by_kind=concrete_by_kind,
                    has_imm=has_imm,
                )
            )

    return cycles, all_uses


def _build_root_states(
    cycles: list[CycleInfo], all_uses: list[VirtualUse]
) -> dict[int, RootState]:
    roots: dict[int, RootState] = {}
    for use in all_uses:
        root = roots.get(use.root_id)
        if root is None:
            root = RootState(
                root_id=use.root_id,
                size=use.size,
                align=use.align,
                uses=[],
                cycles=[],
                candidates={
                    kind
                    for kind, capacity in _KIND_CAPACITY.items()
                    if use.size <= capacity
                },
                fixed_bases={},
                reasons=[],
            )
            roots[use.root_id] = root
        elif root.size != use.size or root.align != use.align:
            raise PeVirtualAllocationError(
                f"PE virtual allocation failed: inconsistent virtual root metadata for root {use.root_id}"
            )
        root.uses.append(use)
        if use.offset < 0:
            root.reasons.append(
                f"root {use.root_id}: negative offset {use.offset} is not supported"
            )
        if use.offset + use.access_span > use.size:
            root.reasons.append(
                f"root {use.root_id}: access offset {use.offset} with width {use.width.value} exceeds virtual size {use.size}"
            )

    for cycle in cycles:
        cycle_root_ids = list(cycle.virtual_uses)
        for index, root_id in enumerate(cycle_root_ids):
            root = roots[root_id]
            root.cycles.append(cycle.index)
            root.max_cycle_pressure = max(root.max_cycle_pressure, cycle.pressure)
            signatures = {use.signature for use in cycle.virtual_uses[root_id]}
            if len(signatures) > 1:
                root.reasons.append(
                    f"cycle {cycle.index}: root {root_id} is used with multiple PE access shapes in the same cycle"
                )
                root.candidates.clear()
                continue
            if cycle.has_imm and "lm0" in root.candidates:
                root.candidates.remove("lm0")
                root.reasons.append(
                    f"cycle {cycle.index}: root {root_id} cannot use LM0 because it is issued with imm"
                )
            for other_root_id in cycle_root_ids[index + 1 :]:
                root.interference.add(other_root_id)
                roots[other_root_id].interference.add(root_id)

            for kind, concrete_tokens in cycle.concrete_by_kind.items():
                if kind not in root.candidates:
                    continue
                if len(concrete_tokens) != 1:
                    root.candidates.remove(kind)
                    root.reasons.append(
                        f"cycle {cycle.index}: root {root_id} cannot use {kind} because the cycle already uses multiple concrete {kind} operands"
                    )
                    continue
                signature = next(iter(signatures))
                concrete_token = next(iter(concrete_tokens))
                fixed_base = _match_fixed_base(kind, signature, concrete_token)
                if fixed_base is None:
                    root.candidates.remove(kind)
                    root.reasons.append(
                        f"cycle {cycle.index}: root {root_id} cannot use {kind} alongside concrete operand {concrete_token}"
                    )
                    continue
                existing_base = root.fixed_bases.get(kind)
                if existing_base is not None and existing_base != fixed_base:
                    root.candidates.remove(kind)
                    root.reasons.append(
                        f"root {root_id}: conflicting required {kind} base addresses {existing_base} and {fixed_base}"
                    )
                    continue
                root.fixed_bases[kind] = fixed_base

    for root in roots.values():
        root.candidates = {
            kind
            for kind in root.candidates
            if _base_fits_constraints(root, kind, root.fixed_bases.get(kind))
        }
        if not root.candidates:
            details = (
                "; ".join(root.reasons)
                if root.reasons
                else "no candidate physical kind fits"
            )
            raise PeVirtualAllocationError(
                f"PE virtual allocation failed: root {root.root_id} has no available physical PE memory kind ({details})"
            )

    return roots


def _assign_roots(roots: dict[int, RootState]) -> dict[int, Assignment]:
    ordered_roots = sorted(
        roots.values(),
        key=lambda root: (
            len(root.candidates),
            -root.max_cycle_pressure,
            -len(root.interference),
            -len(root.cycles),
            -root.size,
            root.root_id,
        ),
    )
    assignments: dict[int, Assignment] = {}

    for root in ordered_roots:
        assigned = _assign_single_root(root, roots, assignments)
        if assigned is None:
            candidate_text = ", ".join(sorted(root.candidates)) or "none"
            details = (
                "; ".join(root.reasons)
                if root.reasons
                else "no feasible address remained"
            )
            raise PeVirtualAllocationError(
                f"PE virtual allocation failed: root {root.root_id} could not be assigned. candidates={candidate_text}. {details}"
            )
        assignments[root.root_id] = assigned

    return assignments


def _assign_single_root(
    root: RootState,
    roots: dict[int, RootState],
    assignments: dict[int, Assignment],
) -> Assignment | None:
    for kind in sorted(root.candidates, key=lambda item: (_KIND_CAPACITY[item], item)):
        fixed_base = root.fixed_bases.get(kind)
        if fixed_base is not None:
            if _base_available(root, kind, fixed_base, roots, assignments):
                return Assignment(kind=kind, base=fixed_base)
            continue

        capacity = _KIND_CAPACITY[kind]
        base = 0
        while base + root.size <= capacity:
            if _base_available(root, kind, base, roots, assignments):
                return Assignment(kind=kind, base=base)
            base += root.align

    return None


def _base_available(
    root: RootState,
    kind: str,
    base: int,
    roots: dict[int, RootState],
    assignments: dict[int, Assignment],
) -> bool:
    if not _base_fits_constraints(root, kind, base):
        return False

    for other_root_id in root.interference:
        other_assignment = assignments.get(other_root_id)
        if other_assignment is None or other_assignment.kind != kind:
            continue
        return False
    return True


def _base_fits_constraints(root: RootState, kind: str, base: int | None) -> bool:
    if base is None:
        return True
    if base < 0:
        return False
    if base % root.align != 0:
        return False
    if base + root.size > _KIND_CAPACITY[kind]:
        return False
    for use in root.uses:
        if use.offset + use.access_span > root.size:
            return False
        if (base + use.offset) % use.access_span != 0:
            return False
    return True


def _match_fixed_base(
    kind: str,
    signature: tuple[int, WordWidth, bool],
    concrete_token: str,
) -> int | None:
    parsed = _parse_simple_physical_operand(concrete_token)
    if parsed is None:
        return None
    concrete_kind, concrete_addr, concrete_width, concrete_vector = parsed
    if concrete_kind != kind:
        return None
    offset, width, vector = signature
    if concrete_width != width or concrete_vector != vector:
        return None
    return concrete_addr - offset


def _parse_virtual_use(token: str) -> VirtualUse | None:
    match = _PE_VIRTUAL_RE.fullmatch(token)
    if match is None:
        return None
    width = WordWidth(match.group("width"))
    return VirtualUse(
        root_id=int(match.group("root_id")),
        size=int(match.group("size")),
        align=int(match.group("align")),
        offset=int(match.group("offset")),
        width=width,
        vector=match.group("vector") == "1",
        token=token,
    )


def _physical_kind_from_token(token: str) -> str | None:
    match = _PHYSICAL_PE_RE.fullmatch(token)
    if match is None:
        return None
    return {
        "m": "lm0",
        "n": "lm1",
        "r": "grf0",
        "s": "grf1",
    }.get(match.group("kind"))


def _parse_simple_physical_operand(
    token: str,
) -> tuple[str, int, WordWidth, bool] | None:
    match = _PHYSICAL_DIRECT_RE.fullmatch(token)
    if match is None:
        return None
    kind = {
        "m": "lm0",
        "n": "lm1",
        "r": "grf0",
        "s": "grf1",
    }[match.group("kind")]
    width = WordWidth(match.group("width"))
    return kind, int(match.group("addr")), width, match.group("vector") == "v"


def _render_physical_use(use: VirtualUse, assignment: Assignment) -> str:
    addr = assignment.base + use.offset
    if assignment.kind == "lm0":
        return LM0.auto(addr, width=use.width, vector=use.vector).render()
    if assignment.kind == "lm1":
        return LM1.auto(addr, width=use.width, vector=use.vector).render()
    if assignment.kind == "grf0":
        return GRF0.auto(addr, width=use.width, vector=use.vector).render()
    if assignment.kind == "grf1":
        return GRF1.auto(addr, width=use.width, vector=use.vector).render()
    raise AssertionError(f"Unknown PE physical kind: {assignment.kind}")


def _render_statement(statement: Statement, replacements: dict[str, str]) -> str:
    if isinstance(statement, CycleStatement):
        return "; ".join(
            _replace_tokens(item.text, replacements) for item in statement.items
        )

    text = getattr(statement, "text", None)
    if not isinstance(text, str):
        return statement.render()
    comment = getattr(statement, "comment", None)
    rendered_text = _replace_tokens(text, replacements)
    if not comment:
        return rendered_text
    return f"{rendered_text}  # {comment}"


def _replace_tokens(text: str, replacements: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(0)
        return replacements.get(token, token)

    return _PE_VIRTUAL_RE.sub(replace, text)
