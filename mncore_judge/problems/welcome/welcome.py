from __future__ import annotations

from asm_wrapper import InstructionBuilder, LM0, LM1

def build() -> InstructionBuilder:
    builder = InstructionBuilder()
    builder.inc(
        precision="i",
        src_operand=LM0.auto(0, vector=True),
        dst_operands=[LM1.auto(0, vector=True)],
    )
    builder.inc(
        precision="i",
        src_operand=LM0.auto(8, vector=True),
        dst_operands=[LM1.auto(8, vector=True)],
    )
    return builder


if __name__ == "__main__":
    print(build().to_source())
