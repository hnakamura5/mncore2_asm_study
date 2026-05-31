from __future__ import annotations

from asm_wrapper import DebugDataType, DebugLM0Ref, DebugScope, InstructionBuilder, LM0, PEID


def build() -> InstructionBuilder:
    builder = InstructionBuilder()
    builder.passa(precision="l", src_operand=PEID, dst_operands=[LM0.auto(0, vector=True)])
    builder.debug_get(
        target_memory=DebugLM0Ref(0, scope=DebugScope(group=0, l2b=0, l1b=0, mab=0, pe=0)),
        num_words=1,
        dtype=DebugDataType.DOUBLE,
    )
    return builder


if __name__ == "__main__":
    print(build().to_source())
