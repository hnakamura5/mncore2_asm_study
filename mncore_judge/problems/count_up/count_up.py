from __future__ import annotations

from asm_wrapper import (
    LM0,
    LM1,
    InstructionBuilder,
    PEID,
    L1BID,
    L2BID,
    MSB1,
    L1BM,
    L2BM,
    DRAM,
    ALUF,
    GRF0,
    GRF1,
    with_write_mask_pattern,
    DebugGRF0Ref,
    WordWidth,
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
seq_in_pe = LM1.auto(0, width=WordWidth.LONG)
seq_in_pe_ll = LM1.auto(0, width=WordWidth.DOUBLE_LONG, vector=True)
l1bid = LM0.auto(2)
l2bid = LM0.auto(4)
imm_0_1 = GRF0.auto(2)
zero = GRF1.auto(2)

l1bm_peid = L1BM(
    addr=0,
)
l1bm_peid_ll = L1BM(addr=0, width=WordWidth.DOUBLE_LONG)


def build() -> InstructionBuilder:
    ib = InstructionBuilder()
    # `$l2bid`: `group * 2 + l2b` 0 ~ 7
    # `$l1bid`: L1B 番号 各L2Bごとに 0 ~ 7
    # `$peid`: `mab * 4 + pe` 各L1Bごとに 0 ~ 63

    # packbit 左シフト1出来る。MSBが1のものがあれば、+1もできる。

    with ib.cycle():
        ib.dec(
            unsigned=True, precision="l", src_operand=MSB1, dst_operands=[imm_0_1]
        )  # imm_0_1 に 0x0000000000000001 をセット
        # 0x01111111 11111111 を作る。単語のMSBが0と1であることに留意

    if False:
        ib.debug_get(
            target_memory=DebugGRF0Ref(2), num_words=2
        )  # デバッグ用。0x01111111 11111111 が入っていることを確認するための命令

    with ib.cycle():
        ib.packbit(
            precision="i",
            src_x_operand=PEID,
            src_y_operand=ALUF,
            dst_operands=[peid],
        )  # PEID << 2 + 0 と PEID << 2 + 1 を作る。0と1は ALUFの単語MSBから来る。
    # これをL1BMに集めると、0, 1, 2, 3, ..., 127 ができる。

    if False:
        ib.debug_get(
            target_memory=peid, num_words=1
        )  # デバッグ用。0, 1, 2, 3, ..., 127 のどれかが入っていることを確認する

    with ib.cycle():
        ib.l1bmd(src_operand=ALUF, dst_l1bm=l1bm_peid)  # PEID 0~63 をL1BMに結合

    if False:
        ib.debug_get(target_memory=l1bm_peid, num_words=64)

    ib.nop_repeat(repeat=2)  # TODO: とりあえず待ち

    with ib.cycle():
        ib.l1bmp(src_l1bm=l1bm_peid_ll, dst_operands=[seq_in_pe_ll])
        # 結合したのを戻して、PEごとに0 ~ 15 が入る
        # 順番は 0, 1, 8, 9, 2, 3, 10, 11, 4, 5, 12, 13, 6, 7, 14, 15

    if False:
        ib.debug_get(target_memory=seq_in_pe, num_words=8)

    return ib


if __name__ == "__main__":
    print(build().to_source())
