from __future__ import annotations

from asm_wrapper import (
    InstructionBuilder,
    PEID,
    LM0,
    GRF0,
    GRF1,
    WordWidth,
    ALUF,
    MAUF,
    MaskRegister,
    Nowrite,
    MauNegatedOperand,
    LM1,
    WriteMaskedOperand,
    L1BM,
    DebugMaskRef,
)

# LM0上の Int 配列 X の各要素 X[i] について、絶対値 Y[i]=|X[i]| を計算し、LM1上に出力してください。

# 次の VSM は、C 言語でいう if (m[i] >= 0) n[i] = m[i]; を実現しています。
# imm i"0" $nowrite
# isub $lm0v $aluf $omr1
# ipassa $lm0v $ln0v/$imr1

sign_mask = MaskRegister(1)
zero_register = GRF0.auto(0)


def build() -> InstructionBuilder:
    ib = InstructionBuilder()

    with ib.cycle():
        ib.fvpassa(
            # Both OK. Exactly same address (including width) is required r/r, r/w access at the same cycle. w/w access is not allowed.
            src_x_operand=LM1.auto(0, vector=True, width=WordWidth.DOUBLE_LONG),
            # src_x_operand=LM1.auto(0, vector=True, width=WordWidth.DOUBLE_LONG),
            dst_operands=[sign_mask],
        )
        ib.sub(
            precision="i",
            src_x_operand=zero_register,
            src_y_operand=LM0.auto(0, vector=True, width=WordWidth.DOUBLE_LONG),
            dst_operands=[LM1.auto(0, vector=True, width=WordWidth.DOUBLE_LONG)],
            # NG: dst_operands=[LM1.auto(0, vector=True), LM1.auto(2, vector=True)],
        )
    ib.debug_get(
        target_memory=DebugMaskRef(addr=1),
        num_words=4,
    )

    return ib


if __name__ == "__main__":
    print(build().to_source())
