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


subpeid_0_1_2_3 = LM1.auto(0)
subpeid_0_1_2_3_temp = GRF1.auto(16)
l1bid = LM0.auto(4)
l2bid = LM0.auto(8)
mabid = LM0.auto(12)

l1bid_shift4 = GRF0.auto(16)
l2bid_shift7 = GRF0.auto(20)
mabid_shift10 = GRF0.auto(24)


mask_lower_32bit = MaskRegister(1)
seq_in_pe_addr = 0
seq_in_pe = GRF1.auto(seq_in_pe_addr, width=WordWidth.LONG)
seq_in_pe_ll = GRF1.auto(seq_in_pe_addr, width=WordWidth.DOUBLE_LONG, vector=True)
seq_in_pe_2 = GRF1.auto(16, width=WordWidth.LONG)
seq_in_pe_ll_2 = seq_in_pe_2.as_width(WordWidth.DOUBLE_LONG).as_vector()

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
l1bm_result_addr = 0
l1bm_result = L1BM(addr=l1bm_result_addr)
l1bm_raw_peid_addr = 128
l1bm_raw_peid = L1BM(addr=l1bm_raw_peid_addr)
l1bm_raw_peid_ll = L1BM(addr=l1bm_raw_peid_addr, width=WordWidth.DOUBLE_LONG)
l1bm_raw_peid_ll_2 = L1BM(addr=l1bm_raw_peid_addr + 8, width=WordWidth.DOUBLE_LONG)

l2bm_result = L2BM(addr=0)


# 下位2bitをPE内で。subpeidで2bit、その後l1b方面で結合されるので、
# l1bidで3bit, l2b方面で結合されるので3bit 残りの5bitを2*mabid+1で確保か


def build() -> InstructionBuilder:
    ib = InstructionBuilder()
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
        ib.l1bmp(src_l1bm=l1bm_peid_raw, dst_operands=[seq_in_pe_ll.as_vector()])

    with ib.cycle():
        ib.inc(
            precision="l",
            src_operand=ALUF,
            dst_operands=[peid_1_2],
        )
        ib.l1bmp(src_l1bm=l1bm_peid_raw + 8, dst_operands=[seq_in_pe_ll_2.as_vector()])

    if True:
        ib.debug_get(target_memory=l2bm_result, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 512, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 1024, num_words=64)
        ib.debug_get(target_memory=l2bm_result + 1536, num_words=64)

    return ib


if __name__ == "__main__":
    print(build().to_source())
