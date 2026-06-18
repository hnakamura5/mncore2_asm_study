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


# 下位2bitをPE内で。subpeidで2bit、その後l1b方面で結合されるので、
# l1bidで3bit, l2b方面で結合されるので3bit 残りの5bitを2*mabid+1で確保か


def build() -> InstructionBuilder:
    ib = InstructionBuilder()

    peid_raw = ib.new_memory(GRF0, 2)
    l1bid = ib.new_memory(GRF0, 2)
    l2bid = ib.new_memory(GRF0, 2)
    l1bm_peid_raw = ib.new_memory(L1BM, 2)
    peid_1 = ib.new_memory(GRF0, 2)
    peid_1_2 = ib.new_memory(GRF0, 8)
    imm_1 = peid_1_2 + 1 * 2
    seq_in_pe = ib.new_memory(GRF0, 32)
    seq_in_pe_ll = seq_in_pe.as_width(WordWidth.DOUBLE_LONG)
    seq_in_pe_ll_2 = seq_in_pe_ll + 8 * 2
    mask_l1bid_lsb1 = ib.new_memory(MaskRegister, 1)
    imm_0 = seq_in_pe + 0 * 2
    imm_1 = seq_in_pe + 2 * 2
    imm_2 = seq_in_pe + 4 * 2
    imm_3 = seq_in_pe + 6 * 2
    imm_5 = seq_in_pe + 3 * 2
    imm_8 = seq_in_pe + 8 * 2
    imm_12 = seq_in_pe + 14 * 2
    imm_14 = seq_in_pe + 13 * 2

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
        ib.l1bmd(src_operand=ALUF, dst_l1bm=l1bm_peid_raw)

    with ib.cycle():
        ib.passa(precision="i", src_operand=L2BID, dst_operands=[l2bid])

    with ib.cycle():
        ib.inc(
            precision="i",
            src_operand=peid_raw.as_vector(),  # この後にl1bidもある
            dst_operands=[peid_1],
        )

    with ib.cycle():
        ib.inc(
            precision="l",
            src_operand=ALUF,
            dst_operands=[peid_1_2.as_vector()],
        )
        ib.l1bmp(src_l1bm=l1bm_peid_raw, dst_operands=[seq_in_pe_ll.as_vector()])
        # 結合したのを戻して、PEごとに0 ~ 8 の単語繰り返し長語が入る
        # 順番は 0, 4, 1, 5, 2, 6, 3, 7

    with ib.cycle():
        ib.and_(
            precision="i",
            src_x_operand=peid_1.as_vector(),
            src_y_operand=1,
            dst_operands=[mask_l1bid_lsb1],
        )
        ib.l1bmp(src_l1bm=l1bm_peid_raw + 8, dst_operands=[seq_in_pe_ll_2.as_vector()])
        # 結合したのを戻して、PEごとに0 ~ 8 の単語繰り返し長語が入る
        # 順番は 8, C, 9, D, A, E, B, F

    with ib.cycle():
        ib.lsl(
            precision="i",
            src_x_operand=LM0.flat([l1bid, l2bid, 8, 10]),
            src_y_operand=GRF1.flat(
                [
                    seq_in_pe_addr + 8 * 2,  # 8
                    seq_in_pe_addr + 3 * 2,  # 5
                    seq_in_pe_addr + 14 * 2,  # 12
                    seq_in_pe_addr + 13 * 2,  # 14
                ]
            ),  # 8, 5, 12, 14
            dst_operands=[l1bid_shift8],  # この後にl2bid_shift5もある。ここで二か所？
        )

    with ib.cycle():
        ib.add(
            precision="i",
            src_x_operand=l1bid_shift8,
            src_y_operand=l2bid_shift5,  # これがL1同士でかぶっているのでは？
            dst_operands=[pe_result_8s.as_vector()],
        )

    with ib.cycle():
        ib.add(
            precision="i",
            src_x_operand=l1bid_shift8,
            src_y_operand=l2bid_shift5,  # これがL1でかぶっている
            dst_operands=[pe_result_8s.as_vector()],
        )

    with ib.cycle():
        ib.add(
            precision="i",
            src_x_operand=pe_result_8s.as_vector(),
            src_y_operand=ALUF,
            dst_operands=[pe_result_8s.as_vector()],
        )

    with ib.cycle():
        ib.lsl(
            precision="i",
            src_x_operand=GRF1.flat(
                [
                    seq_in_pe + 0 * 2,  # 0
                    seq_in_pe + 2 * 2,  # 1
                    seq_in_pe + 4 * 2,  # 2
                    seq_in_pe + 6 * 2,  # 3
                ]
            ),
            src_y_operand=seq_in_pe + 12 * 2,  # 10
            dst_operands=[
                with_write_mask_pattern(pe_result_8s.as_vector(), mask_l1bid_lsb1)
            ],
        )

    for i in range(8):
        with ib.cycle():
            ib.add(
                precision="i",
                src_x_operand=pe_result_8s.as_vector(),
                src_y_operand=ALUF,
                dst_operands=[pe_result_8s.as_vector()],
            )
            ib.l1bmd(src_operand=pe_result_8s.as_vector(), dst_l1bm=l1bm_result)
            ib.l2bmr2(rrn_opcode="iiadd", src_l1bm=l1bm_result, dst_l2bm=l2bm_result)

    ib.nop()

    with ib.cycle():
        ib.mvd(
            precision="i",
            src_operand=pe_result_8s.as_vector(),
            dst_l2bm=l2bm_result,
        )

    with ib.cycle():
        ib.mvp(
            precision="i",
            src_l2bm=l2bm_result,
            dst_dram=DRAM.auto(0),
        )

    if True:
        ib.debug_get(target_memory=l2bm_result, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 512, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 1024, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 1536, num_words=64)

    return ib


if __name__ == "__main__":
    print(build().to_source())
