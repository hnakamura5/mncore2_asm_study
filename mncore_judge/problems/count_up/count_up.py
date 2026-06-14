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
    MaskRegister,
    MauNegatedOperand,
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


peid_0_1 = LM0.auto(0)  # 単語ペア (PEID << 2 + 0, PEID << 2 + 1) を入れる
l1bid_addr = 2
l1bid = LM0.auto(l1bid_addr)
l2bid_addr = 4
l2bid = LM0.auto(l2bid_addr)
l1bid_shift7 = GRF0.auto(16)
l2bid_shift10_addr = 12
l2bid_shift10 = LM0.auto(l2bid_shift10_addr)
extra_2bit_addr = 14
extra_2bit = LM0.auto(extra_2bit_addr)

mask_lower_32bit = MaskRegister(1)
seq_in_pe_addr = 0
seq_in_pe = LM1.auto(seq_in_pe_addr, width=WordWidth.LONG)
seq_in_pe_ll = LM1.auto(seq_in_pe_addr, width=WordWidth.DOUBLE_LONG, vector=True)
seq_in_pe_ll_2 = LM1.auto(seq_in_pe_addr + 16, width=WordWidth.DOUBLE_LONG, vector=True)
zero = GRF0.auto(0)
imm_0_1 = GRF0.auto(2)
imm_7 = GRF0.auto(4)
imm_10 = GRF0.auto(6)
imm_13_addr = 8
imm_13 = GRF0.auto(8)

peid_raw = GRF1.auto(0)
peid_for_imm = GRF1.auto(2)  # 32bitで同じ数字が二回繰り返されている列

pe_result_8s_addr = GRF1.auto(4)  # PEごとの結論を入れる
# 単語ペア(1, 2) に、l1bid << 7 と l2bid << 10 を足したものをベースとして
# これに [0, 0x200, 0x400, 0x600] を足した8単語が入る

l1bm_peid = L1BM(
    addr=0,
)
l1bm_peid_ll = L1BM(addr=0, width=WordWidth.DOUBLE_LONG)
l1bm_l1bid = L1BM(addr=128)
l1bm_l2bid = L1BM(addr=256)
l1bm_extra_2bit_addr = 384
l1bm_extra_2bit = L1BM(addr=l1bm_extra_2bit_addr)
l1bm_result_addr = 768
l1bm_result = L1BM(addr=l1bm_result_addr)
l1bm_raw_peid_addr = 1024
l1bm_raw_peid = L1BM(addr=l1bm_raw_peid_addr)
l1bm_raw_peid_ll = L1BM(addr=l1bm_raw_peid_addr, width=WordWidth.DOUBLE_LONG)
l1bm_raw_peid_ll_2 = L1BM(addr=l1bm_raw_peid_addr + 8, width=WordWidth.DOUBLE_LONG)

l2bm_result = L2BM(addr=0)


def build() -> InstructionBuilder:
    ib = InstructionBuilder()
    # `$l2bid`: `group * 2 + l2b` 0 ~ 7
    # `$l1bid`: L1B 番号 各L2Bごとに 0 ~ 7
    # `$peid`: `mab * 4 + pe` 各L1Bごとに 0 ~ 63

    # packbit 左シフト1出来る。MSBが1のものがあれば、+1もできる。

    with ib.cycle():
        ib.passa(precision="i", src_operand=PEID, dst_operands=[peid_raw])

    with ib.cycle():
        ib.l1bmd(src_operand=ALUF, dst_l1bm=l1bm_raw_peid)  # PEID 0~63 をL1BMに結合
        ib.dec(
            unsigned=True, precision="l", src_operand=MSB1, dst_operands=[imm_0_1]
        )  # imm_0_1 に 0x0000000000000001 をセット
        # 0x01111111 11111111 を作る。単語のMSBが0と1であることに留意

    if False:
        ib.debug_get(
            target_memory=DebugGRF0Ref(2), num_words=2
        )  # デバッグ用。0x01111111 11111111 が入っていることを確認するための命令

    with ib.cycle():
        ib.fvpassa(
            src_x_operand=MauNegatedOperand(ALUF),
            dst_operands=[mask_lower_32bit],
        )  # 下位32bitが1になるマスク
        ib.packbit(
            precision="i",
            src_x_operand=PEID,
            src_y_operand=ALUF,
            dst_operands=[peid_0_1],
        )  # PEID << 2 + 0 と PEID << 2 + 1 を作る。0と1は ALUFの単語MSBから来る。
    # これをL1BMに集めると、0, 1, 2, 3, ..., 127 ができる。7bit 確保

    if False:
        ib.debug_get(target_memory=mask_lower_32bit, num_words=1)
        # 下位32bitが1になるマスク。3 = 0b0011 ということ。(サイクル方向は？)

    if False:
        ib.debug_get(
            target_memory=peid_0_1, num_words=1
        )  # デバッグ用。0, 1, 2, 3, ..., 127 のどれかが入っていることを確認する

    with ib.cycle():
        ib.l1bmd(src_operand=ALUF, dst_l1bm=l1bm_peid)  # PEID 0~63 をL1BMに結合

    if False:
        ib.debug_get(target_memory=l1bm_peid, num_words=64)

    # with ib.cycle():
    #     # ib.passa(precision="i", src_operand=L1BID, dst_operands=[l1bid])
    #     ib.imm(payload='i"7"', dst_operands=[imm_7])

    # with ib.cycle():
    #     # ib.passa(precision="i", src_operand=L2BID, dst_operands=[l2bid])
    #     ib.imm(payload='i"10"', dst_operands=[imm_10])

    ib.nop_repeat(repeat=2)  # TODO: とりあえず待ち
    # 前のl1bmd から2サイクル必要

    with ib.cycle():
        ib.imm(payload='i"13"', dst_operands=[imm_13])
        ib.l1bmp(src_l1bm=l1bm_raw_peid_ll, dst_operands=[seq_in_pe_ll])
        # 結合したのを戻して、PEごとに0 ~ 8 の単語繰り返し長語が入る
        # 順番は 0, 4, 1, 5, 2, 6, 3, 7

    with ib.cycle():
        ib.l1bmp(src_l1bm=l1bm_raw_peid_ll_2, dst_operands=[seq_in_pe_ll_2])
        # 結合したのを戻して、PEごとに0 ~ 8 の単語繰り返し長語が入る
        # 順番は 8, C, 9, D, A, E, B, F

    if False:
        ib.debug_get(target_memory=seq_in_pe, num_words=16)

    ib.nop_repeat(repeat=2)  # TODO: とりあえず待ち
    imm_7 = LM1.auto(seq_in_pe_addr + 7 * 2, width=WordWidth.LONG)
    with ib.cycle():
        ib.lsl(
            precision="i",
            src_x_operand=L1BID,
            src_y_operand=imm_7,
            dst_operands=[l1bid_shift7],
        )

    if False:
        ib.debug_get(target_memory=l1bid_shift7, num_words=1)
        # 0 とか0x80とかが出る

    imm_10 = LM1.auto(seq_in_pe_addr + 12 * 2, width=WordWidth.LONG)
    with ib.cycle():
        ib.lsl(
            precision="i",
            src_x_operand=L1BID,
            src_y_operand=imm_10,
            dst_operands=[l2bid_shift10],
        )
        ib.l1bmd(src_operand=ALUF, dst_l1bm=l1bm_l1bid)  # l1bid << 7 をL1BMに結合
        # 3bit確保

    if False:
        ib.debug_get(target_memory=l2bid_shift10, num_words=1)
        # 0 とか0x400とかが出る

    if False:
        ib.debug_get(target_memory=l1bm_l1bid, num_words=8)

    with ib.cycle():
        ib.l1bmd(src_operand=ALUF, dst_l1bm=l1bm_l2bid)  # l2bid << 10 をL1BMに結合
        # 3bit確保

    if False:
        ib.debug_get(target_memory=l1bm_l2bid, num_words=8)

    # 残り2bitと+1をどう確保するか？今回は普通に考えると13bit分もの数が必要
    # 1, 1 << 13 + 1, 2 << 13 + 1, 3 << 13 + 1
    # この4つをそれぞれのPEで(単語繰り返しの長語)定数として用意して、
    # 順に上で集計していく形になるか
    imm_0_addr = seq_in_pe_addr + 0 * 2
    imm_1_addr = seq_in_pe_addr + 2 * 2
    imm_2_addr = seq_in_pe_addr + 4 * 2
    imm_3_addr = seq_in_pe_addr + 6 * 2
    with ib.cycle():
        ib.lsl(
            precision="i",
            src_x_operand=LM1.flat([imm_0_addr, imm_1_addr, imm_2_addr, imm_3_addr]),
            src_y_operand=GRF0.flat([imm_13_addr] * 4),
            dst_operands=[extra_2bit],
        )

    with ib.cycle():
        ib.inc(
            precision="i",
            src_operand=ALUF,
            dst_operands=[LM0.auto(extra_2bit_addr, vector=True)],
        )
        # 1, 1 << 13 + 1, 2 << 13 + 1, 3 << 13 + 1 を得る。つまり残りの2bit分と+1

    if False:
        ib.debug_get(target_memory=extra_2bit, num_words=4)
        # 1, 0x2001, 0x4001, 0x6001 が出る

    with ib.cycle():
        ib.l1bmd(src_operand=ALUF, dst_l1bm=l1bm_extra_2bit)  # extra_2bit をL1BMに結合

    if False:
        ib.debug_get(target_memory=l1bm_extra_2bit, num_words=2)
        ib.debug_get(target_memory=l1bm_extra_2bit + 64, num_words=2)
        ib.debug_get(target_memory=l1bm_extra_2bit + 128, num_words=2)
        ib.debug_get(target_memory=l1bm_extra_2bit + 192, num_words=2)
        # 1, 0x2001, 0x4001, 0x6001 が出る

    with ib.cycle():
        ib.nop()

    with ib.cycle():
        ib.add(
            precision="i",
            src_x_operand=peid_0_1,
            src_y_operand=l1bid_shift7,
            dst_operands=[pe_result_8s_addr.as_vector()],
        )

    if False:
        ib.debug_get(target_memory=pe_result_8s_addr, num_words=4)

    with ib.cycle():
        ib.add(
            precision="i",
            src_x_operand=ALUF,
            src_y_operand=l2bid_shift10,
            dst_operands=[pe_result_8s_addr.as_vector()],
        )

    with ib.cycle():
        ib.add(
            precision="i",
            src_x_operand=ALUF,
            src_y_operand=extra_2bit.as_vector(),
            dst_operands=[pe_result_8s_addr.as_vector()],
        )

    with ib.cycle():
        ib.nop()

    if False:
        ib.debug_get(target_memory=pe_result_8s_addr, num_words=4)

    with ib.cycle():
        ib.l1bmd(src_operand=pe_result_8s_addr, dst_l1bm=l1bm_result)

    with ib.cycle():
        ib.l1bmd(src_operand=pe_result_8s_addr + 2, dst_l1bm=l1bm_result + 64)

    with ib.cycle():
        ib.l1bmd(src_operand=pe_result_8s_addr + 4, dst_l1bm=l1bm_result + 128)

    with ib.cycle():
        ib.l1bmd(src_operand=pe_result_8s_addr + 6, dst_l1bm=l1bm_result + 192)

    if False:
        ib.debug_get(target_memory=l1bm_result, num_words=64)
        ib.debug_get(target_memory=l1bm_result + 64, num_words=64)
        ib.debug_get(target_memory=l1bm_result + 128, num_words=64)
        ib.debug_get(target_memory=l1bm_result + 192, num_words=64)

    # 転送幅の問題で16単語ごとになる
    # for i in range(4):
    #     with ib.cycle():
    #         ib.l2bmd(src_l1bm=l1bm_result + i * 32, dst_l2bm=l2bm_result + i * 256)

    #     with ib.cycle():
    #         ib.l2bmd(
    #             src_l1bm=l1bm_result + (i + 1) * 32,
    #             dst_l2bm=l2bm_result + (i + 1) * 256,
    #         )

    # if True:
    #     ib.debug_get(target_memory=l2bm_result, num_words=64)
    #     ib.debug_get(target_memory=l2bm_result + 256, num_words=64)
    #     ib.debug_get(target_memory=l2bm_result + 512, num_words=64)
    #     ib.debug_get(target_memory=l2bm_result + 768, num_words=64)

    # L1BMごとにサイクルごと32単語固めて転送する。だから各L1BMでの区切りを32単語ごとにする必要がある。
    # 127まで一気に作っているのが売りなのだが？
    # これなら16単語単位にして、4bitで切って隙間にl1bm押し込んでも良いかもしれない。
    for i in range(4):
        with ib.cycle():
            ib.l2bmr2(
                rrn_opcode="fmin",  # 整数の大小比較であることが保証されている
                src_l1bm=l1bm_result + i * 64,
                dst_l2bm=l2bm_result + i * 512,
            )
        with ib.cycle():
            ib.l2bmr2(
                rrn_opcode="fmax",
                src_l1bm=l1bm_result + i * 64,
                dst_l2bm=l2bm_result + (i + 1) * 512,
            )

    if True:
        ib.debug_get(target_memory=l2bm_result, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 512, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 1024, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 1536, num_words=64)

    return ib


if __name__ == "__main__":
    print(build().to_source())
