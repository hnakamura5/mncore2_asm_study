from __future__ import annotations

from asm_wrapper import (
    LM0,
    LM1,
    InstructionBuilder,
    PEID,
    L1BID,
    L2BID,
    L1BM,
    L2BM,
    DRAM,
    ALUF,
    GRF0,
    GRF1,
    with_write_mask_pattern,
)

# 1 から 32768 までの各整数の Int を順に Group 0 の DRAM の先頭から書き込んでください。
#
# たとえば $d0@0 には Long（Int 2 つぶん）として 1×2^32+2 が、 $d100@0 には 201×2^32+202 が書かれることになります。


# 32768 = 2^15
# 6bitはPEIDの範囲、3bitはL1BIDの範囲、3bitはL2BIDの範囲で12bit
# 残りの3bitもL1BIDで割り当てるとよいか？
# 1からスタートなのがいやらしいところ。最後の2^15はmsbで確保

# peidをipassaで書き込むと、当然単語として2回書き込まれる。これに、1と2を加算すればよいのでは？
# これで7bitを確保できる？
# これをやるなら、他の全てのものも同じように足す必要がある。
# そんで、縮約も iadd でやればよいか？あるじゃん。
# 即値0x0000000100000002 が用意できなくない？ 1を出してマスク付き+1するのはできるけども？
# 即値0x0000000000000001 ならできるけども？じゃあこっちでやって、最後に集めるときに1足すか。


peid = LM0.auto(0)
l1bid = LM1.auto(0)
l2bid = LM1.auto(2)
imm_0_1 = GRF0.auto(2)
shifter_6 = GRF0.auto(0)
peid_shifted_6 = GRF1.auto(0)
zero = GRF1.auto(2)


def build() -> InstructionBuilder:
    ib = InstructionBuilder()
    # `$l2bid`: `group * 2 + l2b` 0 ~ 7
    # `$l1bid`: L1B 番号 各L2Bごとに 0 ~ 7
    # `$peid`: `mab * 4 + pe` 各L1Bごとに 0 ~ 63

    # packbit 左シフト1出来る。MSBが1のものがあれば、+1もできる。

    with ib.cycle():
        ib.packbit(
            precision="i",
            src_x_operand=PEID,
            src_y_operand=zero,
            dst_operands=[peid],
        )  # PEIDの二倍を書き込む。単語としては2回書き込まれる。これでPEIDの値を0, 0, 2, 2, 4, 4, ... 126 とする
    with ib.cycle():
        ib.inc(
            precision="i",
            src_operand=ALUF,
            dst_operands=[
                with_write_mask_pattern(peid, mask_pattern="0011", guard_suffix="p")
            ],
        )  # PEIDの偶数番目に1を加算する。これでPEIDが0, 1, 2, 3, 4, 5, ... 127 とする

    with ib.cycle():
        ib.imm(payload='l"0x"', dst_operands=[peid])  # PEIDの初期値を1にする
    with ib.cycle():
        ib.passa(precision="i", src_operand=PEID, dst_operands=[peid])
    with ib.cycle():
        ib.imm(payload='i"6"', dst_operands=[shifter_6])  # シフト量 6 をロード
        ib.l1bmd(src_operand=ALUF, dst_l1bm=L1BM(addr=0))  # PEID 0~63 をL1BMに展開
    with ib.cycle():
        ib.lsl(
            precision="i",
            src_x_operand=L1BID,
            src_y_operand=shifter_6,
            dst_operands=[peid_shifted_6],
        )  # L1BIDを6ビット左シフト

    return ib


if __name__ == "__main__":
    print(build().to_source())
