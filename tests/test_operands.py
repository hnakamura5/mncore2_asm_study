from __future__ import annotations

import unittest

from asm_wrapper import (
    GRF0,
    InstructionBuilder,
    L1BM,
    LM1,
    MaskRegister,
    negate_mau_input,
    with_write_mask_pattern,
    with_write_mask_register,
)


class MauOperandTests(unittest.TestCase):
    def test_negate_mau_input_renders_with_prefix_minus(self) -> None:
        operand = negate_mau_input(GRF0.auto(0))

        self.assertEqual(operand.render(), "-$lr0")

    def test_builder_accepts_negated_mau_input(self) -> None:
        builder = InstructionBuilder()
        builder.fvadd(
            src_x_operand=negate_mau_input(GRF0.auto(0)),
            src_y_operand=GRF0.auto(2),
            dst_operands=[GRF0.auto(4)],
        )

        self.assertEqual(builder.lines(), ("fvadd -$lr0 $lr2 $lr4",))


class WriteMaskOperandTests(unittest.TestCase):
    def test_fixed_write_mask_renders_on_destination_operand(self) -> None:
        operand = with_write_mask_pattern(LM1.auto(0, vector=True), "1000")

        self.assertEqual(operand.render(), "$ln0v/1000")

    def test_register_write_mask_supports_double_long_and_guard_suffix(self) -> None:
        operand = with_write_mask_register(
            MaskRegister(1), 3, double_long=True, guard_suffix="p"
        )

        self.assertEqual(operand.render(), "$omr1/$llimr3p")

    def test_builder_accepts_write_masked_destination_operand(self) -> None:
        builder = InstructionBuilder()
        builder.l1bmd(
            src_l1bm=L1BM(addr=0),
            dst_operands=[with_write_mask_register(GRF0.auto(4, vector=True), 1)],
        )

        self.assertEqual(builder.lines(), ("l1bmd $lb0 $lr4v/$imr1",))


class DebugOperandTests(unittest.TestCase):
    def test_debug_methods_accept_normal_operands_directly(self) -> None:
        builder = InstructionBuilder()
        builder.debug_get(target_memory=GRF0.auto(2), num_words=1, dtype="d")
        builder.debug_set(
            target_memory=L1BM(addr=8),
            num_words=2,
            payload="00000000000000010000000000000002",
        )

        self.assertEqual(
            builder.lines(),
            (
                "d getd $lr2 1  # debug: emulator-only memory dump",
                "d set $lb8 2 00000000000000010000000000000002  # debug: emulator-only memory write",
            ),
        )


if __name__ == "__main__":
    unittest.main()
