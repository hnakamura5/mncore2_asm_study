from __future__ import annotations

import unittest

from asm_wrapper import (
    DRAM,
    GRF0,
    GRF1,
    InstructionBuilder,
    L1BM,
    L2BM,
    LM0,
    LM1,
    MaskRegister,
    Matrix,
    MatrixBank,
    Nowrite,
    PeVirtualMemory,
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


class BuilderMemoryAllocationTests(unittest.TestCase):
    def test_new_memory_allocates_auto_address_operands_with_alignment(self) -> None:
        builder = InstructionBuilder()

        first = builder.new_memory(LM0, 2, 2)
        second = builder.new_memory(LM0, 3, 8)

        self.assertIsInstance(first, LM0)
        self.assertEqual(first.render(), "$lm0")
        self.assertEqual(second.render(), "$lm8")

    def test_new_memory_tracks_each_memory_type_independently(self) -> None:
        builder = InstructionBuilder()

        l1bm_first = builder.new_memory(L1BM, 128, 128)
        lm0_first = builder.new_memory(LM0, 4, 4)
        l1bm_second = builder.new_memory(L1BM, 64, 128)

        self.assertEqual(l1bm_first.render(), "$lb0")
        self.assertEqual(lm0_first.render(), "$lm0")
        self.assertEqual(l1bm_second.render(), "$lb128")

    def test_new_memory_supports_direct_address_operands(self) -> None:
        builder = InstructionBuilder()

        first = builder.new_memory(DRAM, 64, 64)
        second = builder.new_memory(DRAM, 32, 64)

        self.assertIsInstance(first, DRAM)
        self.assertEqual(first.render(), "$d0")
        self.assertEqual(second.render(), "$d64")

    def test_typed_new_memory_wrappers_return_matching_operand_types(self) -> None:
        builder = InstructionBuilder()

        lm0 = builder.new_lm0(8, 8)
        l1bm = builder.new_l1bm(128, 128)
        grf1 = builder.new_grf1(4, 4)

        self.assertIsInstance(lm0, LM0)
        self.assertIsInstance(l1bm, L1BM)
        self.assertIsInstance(grf1, GRF1)
        self.assertEqual(lm0.render(), "$lm0")
        self.assertEqual(l1bm.render(), "$lb0")
        self.assertEqual(grf1.render(), "$ls0")

    def test_new_memory_pe_virtual_returns_virtual_operand(self) -> None:
        builder = InstructionBuilder()

        operand = builder.new_memory_pe_virtual(8, 4)

        self.assertIsInstance(operand, PeVirtualMemory)
        self.assertEqual(operand.render(), "__pevr0_s8_a4_o0_wl_v0__")

    def test_new_memory_pe_virtual_is_resolved_for_simple_cycle(self) -> None:
        builder = InstructionBuilder()
        src_x_operand = builder.new_memory_pe_virtual(600, 2).as_vector(True)
        src_y_operand = builder.new_memory_pe_virtual(600, 2).as_vector(True)

        with builder.cycle():
            builder.fvadd(
                src_x_operand=src_x_operand,
                src_y_operand=src_y_operand,
                dst_operands=[GRF0.auto(0, vector=True)],
            )

        self.assertEqual(builder.lines(), ("fvadd $lm0v $ln0v $lr0v",))

    def test_new_memory_pe_virtual_fails_when_constraints_cannot_be_satisfied(
        self,
    ) -> None:
        builder = InstructionBuilder()
        left = builder.new_memory_pe_virtual(600, 2)
        right = builder.new_memory_pe_virtual(600, 2)

        with builder.cycle():
            builder.imm(payload=0, dst_operands=[GRF0.auto(0)])
            builder.fvadd(
                src_x_operand=left,
                src_y_operand=right,
                dst_operands=[GRF0.auto(2)],
            )

        with self.assertRaisesRegex(RuntimeError, "PE virtual allocation failed"):
            builder.lines()

    def test_new_memory_pe_virtual_resolves_across_multiple_busy_cycles(self) -> None:
        builder = InstructionBuilder()
        lm1_forced = builder.new_memory_pe_virtual(600, 2)
        lm0_forced = builder.new_memory_pe_virtual(600, 2)
        grf0_forced = builder.new_memory_pe_virtual(400, 2)
        grf1_forced = builder.new_memory_pe_virtual(400, 2)

        with builder.cycle():
            builder.passa(
                precision="l",
                src_operand=lm1_forced,
                dst_operands=[grf0_forced],
            )
            builder.passa(
                precision="l",
                src_operand=lm0_forced,
                dst_operands=[grf1_forced],
            )

        with builder.cycle():
            builder.imm(payload=0, dst_operands=[GRF0.auto(0)])
            builder.passa(
                precision="l",
                src_operand=lm1_forced,
                dst_operands=[grf0_forced],
            )
            builder.passa(
                precision="l",
                src_operand=grf0_forced,
                dst_operands=[grf1_forced],
            )
            builder.passa(
                precision="l",
                src_operand=grf1_forced,
                dst_operands=[Nowrite()],
            )

        assignments = builder.resolve_pe_virtual_operands()

        self.assertIsInstance(assignments[lm1_forced], LM1)
        self.assertEqual(assignments[lm1_forced].render(), "$ln0")
        self.assertIsInstance(assignments[lm0_forced], LM0)
        self.assertEqual(assignments[lm0_forced].render(), "$lm0")
        self.assertIsInstance(assignments[grf0_forced], GRF0)
        self.assertEqual(assignments[grf0_forced].render(), "$lr0")
        self.assertIsInstance(assignments[grf1_forced], GRF1)
        self.assertEqual(assignments[grf1_forced].render(), "$ls0")

        self.assertEqual(
            builder.lines(),
            (
                "lpassa $ln0 $lr0; lpassa $lm0 $ls0",
                "imm 0 $lr0; lpassa $ln0 $lr0; lpassa $lr0 $ls0; lpassa $ls0 $nowrite",
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
        self.assertEqual(operand.addr, 8)
        self.assertEqual(operand.flat_addrs, [8, 10, 12, 14])

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
        operand = GRF1.flat([0, 2, 4, 6]).as_width(WordWidth.DOUBLE_LONG)

        self.assertEqual(operand.render(), "$lls[0,2,4,6]")

    def test_matrix_as_width_updates_matrix_prefix(self) -> None:
        operand = Matrix(MatrixBank.Y, 4).as_width(WordWidth.DOUBLE_LONG)

        self.assertEqual(operand.render(), "$lly4")


class OperandAddressMetadataTests(unittest.TestCase):
    def test_auto_mode_records_addr(self) -> None:
        operand = GRF0.auto(12, vector=True)

        self.assertEqual(operand.addr, 12)
        self.assertIsNone(operand.flat_addrs)

    def test_flat_mode_records_head_addr_and_flat_addrs(self) -> None:
        operand = LM1.flat([16, 18, 20, 22])

        self.assertEqual(operand.addr, 16)
        self.assertEqual(operand.flat_addrs, [16, 18, 20, 22])

    def test_t_indirect_flat_records_head_addr_and_flat_addrs(self) -> None:
        operand = LM0.t_indirect_flat([4, 8, 12, 16])

        self.assertEqual(operand.addr, 4)
        self.assertEqual(operand.flat_addrs, [4, 8, 12, 16])


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
