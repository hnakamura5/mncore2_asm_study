from __future__ import annotations

from asm_wrapper import DRAM, GRF0, L1BM, L2BM, InstructionBuilder


def build() -> InstructionBuilder:
    builder = InstructionBuilder()
    builder.imm(payload='ui"0x01234567"', dst_operands=[GRF0.auto(0)])
    builder.nop_repeat(repeat=2)
    builder.l1bmd(src_operand=GRF0.auto(0), dst_l1bm=L1BM(addr=0))
    builder.nop_repeat(repeat=3)
    builder.l2bmd(src_l1bm=L1BM(addr=0), dst_l2bm=L2BM(addr=0))
    builder.nop_repeat(repeat=3)
    builder.mvp(size=64, src_operand=L2BM(addr=0), dst_operand=DRAM(addr=0))
    builder.nop_repeat(repeat=12)
    builder.debug_get(target_memory="$d0n0", num_words=1, dtype="d")
    return builder


if __name__ == "__main__":
    print(build().to_source())
