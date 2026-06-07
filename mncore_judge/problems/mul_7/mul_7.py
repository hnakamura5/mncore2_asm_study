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
)

# LM0上の ULong 配列 X の各要素 X[i] について、 Y[i]=X[i]×7 を計算し、LM1上に出力してください。
#
# なお、MN-Core 2 には整数乗算命令はありません。

# Inputs:
# X (0≤X[i]≤1000): ULong $lm[0:32], /((16_MAB:1, 4_PE:1, 16:1); B@[L1B,L2B])

# Outputs:
# Y: ULong $ln[0:32], /((16_MAB:1, 4_PE:1, 16:1))

# InputやOutputのレイアウトは以下のURLを参考にしてください。
# https://tech.preferred.jp/ja/blog/mn-core-tensor-layout/


const_reg = GRF1.auto(
    addr=64,
    vector=True,
)
fvfma_dest_reg = GRF0.auto(
    addr=72,
    vector=True,
)


def fvfma(ib: InstructionBuilder, index: int):
    ib.fvfma(
        src_x_operand=ALUF,
        src_y_operand=const_reg,
        src_z_operand=MAUF if index == 0 else fvfma_dest_reg,
        dst_operands=[
            WriteMaskedOperand.register(
                operand=LM1.auto(addr=8 * index, vector=True),
                register_addr=1,
            )
        ],
    )


def max_fvfma(ib: InstructionBuilder, index: int):
    with ib.cycle():
        ib.max(
            precision="s",
            src_x_operand=LM0.auto(
                addr=8 * (index + 1),
                vector=True,
            ),
            src_y_operand=const_reg,
            dst_operands=[
                MaskRegister(1),
            ],
        )
        fvfma(ib, index)


def build() -> InstructionBuilder:
    ib = InstructionBuilder()

    ib.imm(
        payload='i"0x40e00000"',
        dst_operands=[const_reg],
    )
    with ib.cycle():
        ib.max(
            precision="s",
            src_x_operand=LM0.auto(
                addr=0,
                vector=True,
            ),
            src_y_operand=ALUF,
            dst_operands=[
                MaskRegister(1),
            ],
        )
        ib.fvfma(
            src_x_operand=MauNegatedOperand(ALUF),
            src_y_operand=ALUF,
            src_z_operand=ALUF,
            dst_operands=[fvfma_dest_reg],
        )
    max_fvfma(ib, index=0)
    max_fvfma(ib, index=1)
    max_fvfma(ib, index=2)
    fvfma(ib, index=3)
    return ib


if __name__ == "__main__":
    print(build().to_source())
