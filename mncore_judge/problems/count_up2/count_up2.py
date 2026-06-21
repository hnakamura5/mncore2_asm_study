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


# 下位2bitをPE内で。subpeidで2bit、その後l1b方面で結合されるので、
# l1bidで3bit, l2b方面で結合されるので3bit 残りの5bitを2*mabid+1で確保か

# 下位から順に
# 5bit 1~32 をL1B内のPEIDから確保、l1bmdで1~127まであつめてその32までを通過う
# 3bit 0~7 をL2BID として確保l2bmr2の16長語(=32単語)ストライドでのl2bマタギに対応
# 2bit 0~3を、L1BIDの上位2bitで確保。ここで、L2BにはL1BIDの偶数側からのみ転送することにする
# 残りの5bitはPEで作って順に送出。これはL1BIDの奇数側にのみ転送して、l2bmr2のiaddを使って足していくことにする。


def build() -> InstructionBuilder:
    ib = InstructionBuilder()

    # peid_raw = ib.new_memory(GRF0, 2)
    # l1bid = ib.new_memory(GRF0, 2)
    # l2bid = ib.new_memory(GRF0, 2)
    # l1bm_peid_raw = ib.new_memory(L1BM, 2)
    # l1bm_peid_raw_ll = l1bm_peid_raw.as_width(WordWidth.DOUBLE_LONG)
    # peid_0_1 = ib.new_memory(GRF0, 8)
    # l1bid_0_1 = peid_0_1 + 2
    # peid_1_2 = ib.new_memory(GRF0, 8)
    # imm_1 = peid_1_2 + 1 * 2
    # seq_in_pe = ib.new_memory(LM0, 32, align=8)  # PEごとに0~8の単語繰り返し長語が入る
    # seq_in_pe_ll = seq_in_pe.as_width(WordWidth.DOUBLE_LONG)
    # seq_in_pe_ll_2 = seq_in_pe_ll + 8 * 2
    # seq_in_pe_copy = ib.new_memory(
    #     GRF1, 32, align=8
    # )  # PEごとに0~8の単語繰り返し長語が入る
    # seq_in_pe_copy_ll = seq_in_pe_copy.as_width(WordWidth.DOUBLE_LONG)
    # seq_in_pe_copy_ll_2 = seq_in_pe_copy_ll + 8 * 2
    # mask_l1bid_lsb1 = ib.new_memory(MaskRegister, 1)
    # imm_0 = seq_in_pe + 0 * 2
    # # imm_1 = seq_in_pe + 2 * 2
    # imm_2 = seq_in_pe + 4 * 2
    # imm_3 = seq_in_pe + 6 * 2
    # imm_5 = seq_in_pe + 3 * 2
    # imm_8 = seq_in_pe + 8 * 2
    # imm_12 = seq_in_pe + 14 * 2
    # imm_14 = seq_in_pe + 13 * 2
    # l1bid_shift8 = ib.new_memory(GRF0, 2)
    # l2bid_shift5 = ib.new_memory(GRF0, 2)
    # pe_result_8s = ib.new_memory(GRF0, 8)
    # mask_l1bid_lsb1 = ib.new_memory(MaskRegister, 1)
    # l1bm_result = ib.new_memory(L1BM, 512)
    # l2bm_result = ib.new_memory(L2BM, 512)
    # pdm_result = ib.new_memory(PDM, 16384)
    # dram_result = ib.new_memory(DRAM, 32678)

    peid_raw = ib.new_memory_pe_virtual(2)
    l1bid = ib.new_memory_pe_virtual(8)
    l2bid = l1bid + 2
    l1bm_peid_raw = ib.new_memory(L1BM, 2)
    l1bm_peid_raw_ll = l1bm_peid_raw.as_width(WordWidth.DOUBLE_LONG)
    peid_0_1 = ib.new_memory_pe_virtual(8)
    l1bid_0_1 = peid_0_1 + 2
    peid_1_2 = ib.new_memory_pe_virtual(8)
    imm_1 = peid_1_2 + 1 * 2
    seq_in_pe = ib.new_memory_pe_virtual(
        32, align=8
    )  # PEごとに0~8の単語繰り返し長語が入る
    seq_in_pe_ll = seq_in_pe.as_width(WordWidth.DOUBLE_LONG)
    seq_in_pe_ll_2 = seq_in_pe_ll + 8 * 2
    seq_in_pe_copy = ib.new_memory(
        GRF1, 32, align=8
    )  # PEごとに0~8の単語繰り返し長語が入る
    seq_in_pe_copy_ll = seq_in_pe_copy.as_width(WordWidth.DOUBLE_LONG)
    seq_in_pe_copy_ll_2 = seq_in_pe_copy_ll + 8 * 2
    mask_l1bid_lsb1 = ib.new_memory(MaskRegister, 1)
    imm_0 = seq_in_pe + 0 * 2
    # imm_1 = seq_in_pe + 2 * 2
    imm_2 = seq_in_pe + 4 * 2
    imm_3 = seq_in_pe + 6 * 2
    imm_5 = seq_in_pe + 3 * 2
    imm_8 = seq_in_pe + 8 * 2
    imm_12 = seq_in_pe + 14 * 2
    imm_14 = seq_in_pe + 13 * 2
    l1bid_shift8 = ib.new_memory(GRF0, 2)
    l2bid_shift5 = ib.new_memory(GRF0, 2)
    pe_result_8s = ib.new_memory(GRF0, 8)
    mask_l1bid_lsb1 = ib.new_memory(MaskRegister, 1)
    l1bm_result = ib.new_memory(L1BM, 512)
    l2bm_result = ib.new_memory(L2BM, 512)
    pdm_result = ib.new_memory(PDM, 16384)
    dram_result = ib.new_memory(DRAM, 32678)

    # `$mabid`: 0 ~ 15
    # `$l2bid`: `group * 2 + l2b` 0 ~ 7
    # `$l1bid`: L1B 番号 各L2Bごとに 0 ~ 7
    # `$peid`: `mab * 4 + pe` 各L1Bごとに 0 ~ 63

    # packbit 左シフト1出来る。MSBが1のものがあれば、+1もできる。

    # ipassa $peid  $PEID
    # ipassa $l1bid $L1ID ; l1bmd $aluf
    # ipassa $l2bid $L22D
    # iinc [$PEID, $L1ID, 0, 0] -> [$PEID_1, L1ID_1, 1, 1] ;
    # linc $aluf $ID_1_2 ; l1bmp
    # iand $L1ID_1 1 $omr1 ; l1bmp  # L1IDのLSBが1なら1になるマスク ここの1はiincのついでに手に入れられ
    # ilsl [L1ID, L2ID, 1, 1] << [8, 5, 12, 14]
    # iadd (L1ID << 8) + (L2ID << 5)
    # iadd ((L1ID << 8) + (L2ID << 5)) + ID_1_2
    # add [0, 1, 2, 3] << 10 + ALUF -> PEID_Result
    # ilsl [0, 1, 2, 3] << 10 / omr1 -> PEID_Result # l1bmのLSB1の時に、PEID_Resultを上書き
    # l1bmd PEID_Result
    # iadd ; l1bmd ; l2bmr2 iadd
    # iadd ; l1bmd ; l2bmr2 iadd
    # iadd ; l1bmd ; l2bmr2 iadd
    # iadd ; l1bmd ; l2bmr2 iadd
    # iadd ; l1bmd ; l2bmr2 iadd
    # iadd ; l1bmd ; l2bmr2 iadd
    # iadd ; l1bmd ; l2bmr2 iadd
    # iadd ; l1bmd ; l2bmr2 iadd
    # nop
    # mvd
    # mvp

    with ib.cycle():
        ib.passa(precision="i", src_operand=PEID, dst_operands=[peid_raw])

    with ib.cycle():
        ib.passa(precision="i", src_operand=L1BID, dst_operands=[l1bid])
        ib.l1bmd(src_operand=peid_raw, dst_l1bm=l1bm_peid_raw)

    with ib.cycle():
        ib.passa(precision="i", src_operand=L2BID, dst_operands=[l2bid])

    with ib.cycle():
        ib.inc(
            precision="i",
            src_operand=peid_raw.as_vector(),  # この後にl1bidもある
            dst_operands=[peid_0_1],
        )
        # peid_0_1 に peid, peid + 1
        # l1bid_0_1 に l1bid, l1bid + 1 が入る

    with ib.cycle():
        ib.inc(
            precision="l",
            src_operand=peid_0_1,
            dst_operands=[peid_1_2.as_vector()],
        )  # peid_1_2 に peid, peid + 1, peid + 2, peid + 3 が入る
        ib.l1bmp(
            src_l1bm=l1bm_peid_raw_ll,
            dst_operands=[seq_in_pe_ll.as_vector(), seq_in_pe_copy_ll.as_vector()],
        )
        # 結合したのを戻して、PEごとに0 ~ 8 の単語繰り返し長語が入る
        # 順番は 0, 4, 1, 5, 2, 6, 3, 7

    with ib.cycle():
        ib.and_(
            precision="i",
            src_x_operand=l1bid_0_1,
            src_y_operand=imm_1,
            dst_operands=[mask_l1bid_lsb1],
        )  # l1bmdの下位1bitに対応するマスク
    with ib.cycle():
        ib.l1bmp(
            src_l1bm=l1bm_peid_raw_ll + 8, dst_operands=[seq_in_pe_ll_2.as_vector()]
        )
        # 結合したのを戻して、PEごとに0 ~ 8 の単語繰り返し長語が入る
        # 順番は 8, C, 9, D, A, E, B, F

    with ib.cycle():
        ib.lsl(
            precision="i",
            src_x_operand=l1bid.as_vector(),  # l1bid, l2bid, 1, 1
            src_y_operand=ib.pe_virtual_flat(
                [imm_8, imm_5, imm_12, imm_14]
            ),  # 8, 5, 12, 14
            dst_operands=[l1bid_shift8],  # この後にl2bid_shift5もある。ここで二か所？
        )

    with ib.cycle():
        ib.add(
            precision="i",
            src_x_operand=l1bid_shift8,
            src_y_operand=l2bid_shift5,
            dst_operands=[pe_result_8s.as_vector()],
        )
        # l1bid << 8 + l2bid << 5 の結果がpe_result_8sに入る

    with ib.cycle():
        ib.add(
            precision="i",
            src_x_operand=peid_0_1,
            src_y_operand=pe_result_8s.as_vector(),
            dst_operands=[pe_result_8s.as_vector()],
        )
        # peid_1 (1~127) + (l1bid << 8 + l2bid << 5) の結果がpe_result_8sに入る

    with ib.cycle():
        ib.lsl(
            precision="i",
            src_x_operand=ib.pe_virtual_flat([imm_0, imm_1, imm_2, imm_3]),
            src_y_operand=seq_in_pe + 12 * 2,  # 10
            dst_operands=[
                with_write_mask_register(pe_result_8s.as_vector(), mask_l1bid_lsb1)
            ],
        )  # l1bidの下位1bitが1のPEに対して、pe_result_8sに、上位5bit用の定数群で上書きする
        ib.l1bmd(src_operand=pe_result_8s, dst_l1bm=l1bm_result)

    for i in range(8):
        with ib.cycle():
            if i < 6:
                ib.add(
                    precision="i",
                    src_x_operand=pe_result_8s.as_vector(),
                    src_y_operand=ALUF,
                    dst_operands=[
                        with_write_mask_register(
                            pe_result_8s.as_vector(), mask_l1bid_lsb1
                        )
                    ],
                )
            if i < 7:
                ib.l1bmd(
                    src_operand=pe_result_8s.as_vector(),
                    dst_l1bm=l1bm_result + 64 * (i + 1),
                )
            ib.l2bmr2(
                rrn_opcode="iiadd",
                src_l1bm=l1bm_result + 64 * i,
                dst_l2bm=l2bm_result + 256 * i,
            )

    ib.nop()

    ib.mvd(size=2048, src_operand=l2bm_result, dst_operand=pdm_result)

    ib.mvp(
        size=16384,
        src_operand=l2bm_result,
        dst_operand=dram_result,
    )

    if True:
        ib.debug_get(target_memory=l2bm_result, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 512, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 1024, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 1536, num_words=64)

    return ib


if __name__ == "__main__":
    print(build().to_source())
