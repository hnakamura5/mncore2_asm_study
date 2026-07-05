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


# FizzBuzzまでを1単位として考えると問題は桁の変わる境界か?
# 例えば 1~15で71 bytes
# 16~90は同じ76 bytesだが、
# 91~105 は79 bytesになる
# 105~990 では84 bytes
# 991~1005 では 87 bytes
# 1006~6334 では 92 bytes
# これに改行がそれぞれ15個追加

# PEごとの問題として考えると、それぞれ2つ出せばよいことになる？
# 15個単位で考えると、2MABごと1つくらいがちょうどよい
# まあPEごと2個、あるいはL1Bごと120個とかが見通しが良さそう
# 1\n2\n: 4 bytes
# Fizz\n4\n: 7 bytes
# ただサイズがバラバラなのをどう処理するか

# 転送対象箇所の先頭インデクスをどう計算するか、上記の桁に応じて
# L1Bごと120個の場合
# 0: 510 bytes, sum: 510 bytes
# 1: 568 bytes, sum: 1078 bytes
# 2: 568 bytes, sum: 1646 bytes
# 3: 568 bytes, sum: 2214 bytes
# 4: 568 bytes, sum: 2782 bytes
# 5: 568 bytes, sum: 3350 bytes
# 6: 568 bytes, sum: 3918 bytes
# 7: 568 bytes, sum: 4486 bytes
# 8: 611 bytes, sum: 5097 bytes
# 9: 632 bytes, sum: 5729 bytes
# 10: 632 bytes, sum: 6361 bytes
# ... (全て632 bytes)
# 63: 632 bytes, sum: 39857 bytes

# all: 32767 bytes
# なるほどだから6334までなのか

# スタート地点 (単語)
# if (l1bid == 0): 512
# elif (l1bid < 9): 512 + 568 * l1bid
# elif (l1bid == 9): 5732
# elif (l1bid > 9): 5732 + 632 * (l1bid - 9)
# すべて16の倍数ではある

# PEごと 8byte 出すという発想で行くと?
# 何を出せばよいか半端な状態から特定する計算が必要と。

# 分布
# 8 byte内には最大で3つの数字の要素がある(1ケタ台)
#

# estは、次のような区分線形関数で作ることができます。
#     tidが584以上：
#     120/
#     79
#     ⁢𝑡⁢𝑖⁢𝑑 −113.4
#     （数を出力すると4桁なので、FizzBuzzの周期一周当たり79文字（
#     15
#     79
#     ）。1つのPEあたり8Byteつくるので8⁢𝑡⁢𝑖⁢𝑑
#     を掛ける）
#     tidが50以上：
#     120
#     71
#     ⁢𝑡⁢𝑖⁢𝑑 −13.4
#     （数を出力すると3桁なので、FizzBuzzの周期一周当たり71文字）
#     tidが4以上：
#     120
#     63
#     ⁢𝑡⁢𝑖⁢𝑑 −2.4
#     （数を出力すると2桁なので、FizzBuzzの周期一周当たり63文字）
#     tidが3以下：2.0⁢𝑡⁢𝑖⁢𝑑 +1.0
#     （4つのPEでしか使われないため、係数は適当でよい）


# 転送方法は常に問題
# L1Bまでは集めるだけでよい。しかしバイト数のズレをどう吸収するか
# L1B -> L2B でどう転送するかが問題
# L2B -> DRAM は単独個別転送8回使ってもよさそう


def build() -> InstructionBuilder:
    ib = InstructionBuilder()

    return ib


if __name__ == "__main__":
    print(build().to_source())
