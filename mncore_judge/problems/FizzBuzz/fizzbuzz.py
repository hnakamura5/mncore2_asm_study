from __future__ import annotations

from asm_wrapper import (
    Nowrite,
    LM0,
    LM1,
    InstructionBuilder,
    PEID,
    L1BID,
    L2BID,
    MSB1,
    SUBPEID,
    MABID,
    L1BM,
    L2BM,
    DRAM,
    PDM,
    ALUF,
    GRF0,
    GRF1,
    with_write_mask_register,
    with_write_mask_pattern,
    DebugGRF0Ref,
    WordWidth,
    MaskRegister,
    MauNegatedOperand,
)

# 1 から 6334 までの各整数について

#     15 の倍数なら FizzBuzz
#     5 の倍数でなく 3 の倍数なら Fizz
#     3 の倍数でなく 5 の倍数なら Buzz
#     それ以外ならそのままの数字

# とし、さらにそれらを \n 区切りで連結した文字列を、Group=0 の DRAM の先頭から書き込んでください。

# 最後に \n を付加する必要はなく、ヌル終端の必要もありません。

# 例えば、仮に 1 から 3 までであれば、文字列は 1\n2\nFizz なので、 0x310A320A46697A7A の 8 バイトを書き込めばよいことになります。


# 1 = 0x31
# 2 = 0x32
# ...
# Fizz = 0x46697A7A
# Buzz = 0x42757A7A
# \n = 0x0A


def build() -> InstructionBuilder:
    ib = InstructionBuilder()

    return ib


if __name__ == "__main__":
    print(build().to_source())
