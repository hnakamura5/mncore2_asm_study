from __future__ import annotations

from asm_wrapper import InstructionBuilder, PEID

# 1 から 32768 までの各整数の Int を順に Group 0 の DRAM の先頭から書き込んでください。
#
# たとえば $d0@0 には Long（Int 2 つぶん）として 1×232+2 が、 $d100@0 には 201×232+202 が書かれることになります。


def build() -> InstructionBuilder:
    builder = InstructionBuilder()
    # `$l2bid`: `group * 2 + l2b` 0 ~ 7
    # `$l1bid`: L1B 番号 各L2Bごとに 0 ~ 7
    # `$peid`: `mab * 4 + pe` 各L1Bごとに 0 ~ 63

    return builder


if __name__ == "__main__":
    print(build().to_source())
