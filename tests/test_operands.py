from __future__ import annotations

import unittest

from asm_wrapper import (
    DRAM,
    GRF0,
    InstructionBuilder,
    L1BM,
    L2BM,
    LM0,
    LM1,
    MaskRegister,
    Matrix,
    MatrixBank,
    negate_mau_input,
    with_write_mask_pattern,
    with_write_mask_register,
    WordWidth,
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


class OperandAddressArithmeticTests(unittest.TestCase):
    def test_direct_address_operand_addition_returns_same_type(self) -> None:
        operand = L1BM(addr=8) + 16

        self.assertIsInstance(operand, L1BM)
        self.assertEqual(operand.render(), "$lb24")

    def test_group_qualified_operand_addition_preserves_qualifiers(self) -> None:
        operand = L2BM(addr=32, group=1, l2b=0) + 64

        self.assertEqual(operand.render(), "$lc96@1.0")

    def test_suffix_based_operand_addition_offsets_only_addresses(self) -> None:
        operand = GRF0.auto(4, vector=True, adri=2) + 8

        self.assertEqual(operand.render(), "$lr12v2")

    def test_flat_operand_addition_offsets_each_cycle_address(self) -> None:
        operand = LM0.flat([0, 2, 4, 6]) + 8

        self.assertEqual(operand.render(), "$lm[8,10,12,14]")

    def test_dram_indirect_addition_offsets_dar_index(self) -> None:
        operand = DRAM(dar_addr=3, group=0) + 2

        self.assertEqual(operand.render(), "$di5@0")

    def test_matrix_addition_offsets_matrix_addr(self) -> None:
        operand = Matrix(MatrixBank.X, 2) + 4

        self.assertEqual(operand.render(), "$lx6")


class OperandWidthConversionTests(unittest.TestCase):
    def test_l1bm_as_width_returns_copied_operand(self) -> None:
        operand = L1BM(addr=8).as_width(WordWidth.DOUBLE_LONG)

        self.assertIsInstance(operand, L1BM)
        self.assertEqual(operand.render(), "$llb8")

    def test_suffix_based_operand_as_width_preserves_addressing_mode(self) -> None:
        operand = LM1.auto(16, vector=True, adri=3).as_width(WordWidth.DOUBLE_LONG)

        self.assertEqual(operand.render(), "$lln16v3")

    def test_grf_as_width_preserves_flat_addresses(self) -> None:
        operand = GRF0.flat([0, 2, 4, 6]).as_width(WordWidth.DOUBLE_LONG)

        self.assertEqual(operand.render(), "$lls[0,2,4,6]")

    def test_matrix_as_width_updates_matrix_prefix(self) -> None:
        operand = Matrix(MatrixBank.Y, 4).as_width(WordWidth.DOUBLE_LONG)

        self.assertEqual(operand.render(), "$lly4")


class OperandVectorConversionTests(unittest.TestCase):
    def test_as_vector_enables_vector_mode_on_scalar_operand(self) -> None:
        operand = GRF0.auto(12).as_vector(True)

        self.assertEqual(operand.render(), "$lr12v")

    def test_as_vector_disables_vector_mode_and_drops_adri(self) -> None:
        operand = LM1.auto(16, vector=True, adri=3).as_vector(False)

        self.assertEqual(operand.render(), "$ln16")

    def test_as_vector_preserves_other_suffix_parts(self) -> None:
        operand = LM0.auto(20, vector=True, madpe=2, cycle_mask="1000").as_vector(False)

        self.assertEqual(operand.render(), "$lm20j2/1000")


if __name__ == "__main__":
    unittest.main()
