"""直前 PE サイクルの ALU 出力を `$aluf` へ自動置換する。"""

from __future__ import annotations

from dataclasses import dataclass


_ALU_EXACT_SPECS = {
    "zero": (0, True),
    "imm": (1, True),
    "immu": (1, True),
    "msl": (1, True),
    "msr": (1, True),
}

_ALU_SUFFIX_SPECS = [
    ("ilrelud", 2),
    ("packbit", 2),
    ("lrelud", 2),
    ("lreluo", 2),
    ("relu0", 2),
    ("relu1", 2),
    ("relu2", 2),
    ("relu3", 2),
    ("passa", 1),
    ("rsqrt", 1),
    ("floor", 1),
    ("ftoi", 1),
    ("lnot", 1),
    ("relu", 2),
    ("bfe", 1),
    ("bfn", 1),
    ("max", 2),
    ("min", 2),
    ("and", 2),
    ("xor", 2),
    ("add", 2),
    ("sub", 2),
    ("lsl", 2),
    ("lsr", 2),
    ("bsl", 2),
    ("bsr", 2),
    ("inc", 1),
    ("dec", 1),
    ("not", 1),
    ("or", 2),
]

_MAU_VECTOR_EXACT_SPECS = {
    "dvadd": 2,
    "dvpassa": 1,
    "fvadd": 2,
    "fvpassa": 1,
    "hvadd": 2,
    "hvpassa": 1,
}

_MAU_VECTOR_SUFFIX_SPECS = [
    ("vfma", 3),
    ("vmul", 2),
]

_MAU_MATRIX_SUFFIX_SPECS = [
    ("mfma", 3),
    ("mmul", 2),
]

_MWRITE_OPCODES = {"dmwrite", "fmwrite", "gmwrite", "hmwrite"}
_PE_TO_L1BM_PREFIXES = ("l1bmm@", "l1bmr", "l1bmm4@", "l1bmr4")


@dataclass(frozen=True)
class _InstructionSpec:
    source_count: int
    alu: bool = False


def apply_auto_aluf_forwarding(lines: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    prev_alu_outputs: set[str] = set()
    rendered_lines: list[str] = []

    for line in lines:
        item_texts = [item.strip() for item in line.split(";")]
        parsed_items = [_parse_instruction_item(item_text) for item_text in item_texts]
        pe_cycle = any(parsed_item is not None for parsed_item in parsed_items)

        if not pe_cycle:
            rendered_lines.append(line)
            continue

        replaced_items = [
            _replace_item_sources(item_text, parsed_item, prev_alu_outputs)
            for item_text, parsed_item in zip(item_texts, parsed_items, strict=True)
        ]
        rendered_lines.append("; ".join(replaced_items))

        has_no_forward = any(
            parsed_item is not None and parsed_item.opcode in {"nop", "noforward"}
            for parsed_item in parsed_items
        )
        if has_no_forward:
            prev_alu_outputs = set()
            continue

        next_outputs: set[str] = set()
        for parsed_item in parsed_items:
            if parsed_item is None or not parsed_item.spec.alu:
                continue
            next_outputs.update(parsed_item.destination_tokens())
        prev_alu_outputs = next_outputs

    return tuple(rendered_lines)


@dataclass(frozen=True)
class _ParsedInstruction:
    opcode: str
    operands: list[str]
    spec: _InstructionSpec

    def destination_tokens(self) -> set[str]:
        destinations = self.operands[self.spec.source_count :]
        return {
            destination.split("/", 1)[0]
            for destination in destinations
            if destination != "$nowrite"
        }


def _replace_item_sources(
    item_text: str,
    parsed_item: _ParsedInstruction | None,
    prev_alu_outputs: set[str],
) -> str:
    if parsed_item is None or not prev_alu_outputs:
        return item_text

    operands = parsed_item.operands.copy()
    for index in range(parsed_item.spec.source_count):
        operands[index] = _replace_source_token(operands[index], prev_alu_outputs)
    if not operands:
        return parsed_item.opcode
    return f"{parsed_item.opcode} {' '.join(operands)}"


def _replace_source_token(token: str, prev_alu_outputs: set[str]) -> str:
    if token.startswith("-") and token[1:] in prev_alu_outputs:
        return "-$aluf"
    if token in prev_alu_outputs:
        return "$aluf"
    return token


def _parse_instruction_item(item_text: str) -> _ParsedInstruction | None:
    parts = item_text.split()
    if not parts:
        return None
    opcode = parts[0]
    operands = parts[1:]
    spec = _instruction_spec(opcode, operands)
    if spec is None:
        return None
    return _ParsedInstruction(opcode=opcode, operands=operands, spec=spec)


def _instruction_spec(opcode: str, operands: list[str]) -> _InstructionSpec | None:
    if opcode in {"nop", "noforward", "wait"}:
        return _InstructionSpec(source_count=0, alu=False)

    exact_alu = _ALU_EXACT_SPECS.get(opcode)
    if exact_alu is not None:
        source_count, alu = exact_alu
        return _InstructionSpec(source_count=source_count, alu=alu)

    for suffix, source_count in _ALU_SUFFIX_SPECS:
        if opcode.endswith(suffix):
            return _InstructionSpec(source_count=source_count, alu=True)

    exact_mau = _MAU_VECTOR_EXACT_SPECS.get(opcode)
    if exact_mau is not None:
        return _InstructionSpec(source_count=exact_mau, alu=False)

    for suffix, source_count in _MAU_VECTOR_SUFFIX_SPECS:
        if opcode.endswith(suffix):
            return _InstructionSpec(source_count=source_count, alu=False)

    for suffix, source_count in _MAU_MATRIX_SUFFIX_SPECS:
        if opcode.endswith(suffix):
            return _InstructionSpec(source_count=source_count + 1, alu=False)

    if opcode in _MWRITE_OPCODES:
        return _InstructionSpec(source_count=1, alu=False)

    if opcode in {"dmread", "fmread", "gmread", "hmread"}:
        return _InstructionSpec(source_count=1, alu=False)

    if opcode == "l1bmd":
        if len(operands) >= 2 and _is_l1bm_operand(operands[1]):
            return _InstructionSpec(source_count=1, alu=False)
        return _InstructionSpec(source_count=1, alu=False)

    if opcode.startswith(_PE_TO_L1BM_PREFIXES):
        return _InstructionSpec(source_count=1, alu=False)

    if opcode.startswith(
        (
            "l1bmp",
            "l1bmm",
            "l1bmm4",
            "l2bmb",
            "l2bmb2",
            "l2bmd",
            "l2bmr",
            "l2bmi",
            "l2bmdars",
        )
    ):
        return _InstructionSpec(source_count=1, alu=False)

    if opcode == "l2bmdarw":
        return _InstructionSpec(source_count=0, alu=False)

    return None


def _is_l1bm_operand(token: str) -> bool:
    return token.startswith("$lb") or token.startswith("$llb")
