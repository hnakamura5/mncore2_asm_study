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
    PeVirtualFlatMemory,
    PeVirtualMemory,
    TReg,
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

        with self.assertRaisesRegex(
            RuntimeError,
            r"(?s)PE virtual allocation failed: root 1\[.*token=__pevr1_s600_a2_o0_wl_v0__.*Cycle log:.*imm 0 \$lr0; fvadd.*Root log:.*root 1:.*tokens=",
        ):
            builder.lines()

    def test_identical_virtual_operand_is_forwarded_before_allocation(self) -> None:
        builder = InstructionBuilder()
        forwarded = builder.new_memory_pe_virtual(600, 2)
        other = builder.new_memory_pe_virtual(600, 2)

        with builder.cycle():
            builder.passa(
                precision="l",
                src_operand=GRF0.auto(0),
                dst_operands=[forwarded],
            )

        with builder.cycle():
            builder.imm(payload=0, dst_operands=[GRF0.auto(2)])
            builder.fvadd(
                src_x_operand=forwarded,
                src_y_operand=other,
                dst_operands=[GRF0.auto(4)],
            )

        assignments = builder.resolve_pe_virtual_operands()

        self.assertIsInstance(assignments[forwarded], LM0)
        self.assertEqual(assignments[forwarded].render(), "$lm0")
        self.assertIsInstance(assignments[other], LM1)
        self.assertEqual(assignments[other].render(), "$ln0")
        self.assertEqual(
            builder.lines(),
            (
                "lpassa $lr0 $lm0",
                "imm 0 $lr2; fvadd $aluf $ln0 $lr4",
            ),
        )

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
                "imm 0 $lr0; lpassa $ln0 $lr0; lpassa $aluf $ls0; lpassa $aluf $nowrite",
            ),
        )

    def test_new_memory_pe_virtual_offset_resolves_to_same_kind(self) -> None:
        builder = InstructionBuilder()
        base = builder.new_memory_pe_virtual(16, 4)
        offset = base + 8

        with builder.cycle():
            builder.imm(payload=0, dst_operands=[GRF0.auto(0)])
            builder.passa(
                precision="l",
                src_operand=GRF1.auto(0),
                dst_operands=[base.as_vector()],
            )

        with builder.cycle():
            builder.passa(
                precision="l",
                src_operand=offset,
                dst_operands=[GRF0.auto(2)],
            )

        assignments = builder.resolve_pe_virtual_operands()

        self.assertEqual(base.root_id, offset.root_id)
        self.assertEqual(base.offset, 0)
        self.assertEqual(offset.offset, 8)
        self.assertIsInstance(assignments[base], LM1)
        self.assertEqual(assignments[base].render(), "$ln0")
        self.assertEqual(
            builder.lines(),
            (
                "imm 0 $lr0; lpassa $ls0 $ln0v",
                "lpassa $ln8 $lr2",
            ),
        )

    def test_new_memory_pe_virtual_offset_rejects_out_of_range_access(self) -> None:
        builder = InstructionBuilder()
        base = builder.new_memory_pe_virtual(8, 4)
        out_of_range = base + 8

        with builder.cycle():
            builder.passa(
                precision="l",
                src_operand=out_of_range,
                dst_operands=[GRF0.auto(0)],
            )

        with self.assertRaisesRegex(RuntimeError, "exceeds virtual size 8"):
            builder.lines()

    def test_pe_virtual_flat_requires_same_kind_assignment(self) -> None:
        builder = InstructionBuilder()
        flat_operands = [builder.new_memory_pe_virtual(600, 2) for _ in range(4)]
        flat_operand = builder.pe_virtual_flat(flat_operands)

        self.assertIsInstance(flat_operand, PeVirtualFlatMemory)

        with builder.cycle():
            builder.imm(payload=0, dst_operands=[GRF0.auto(0)])
            builder.passa(
                precision="l",
                src_operand=flat_operand,
                dst_operands=[GRF1.flat([0, 2, 4, 6])],
            )

        assignments = builder.resolve_pe_virtual_operands()
        for operand in flat_operands:
            self.assertIsInstance(assignments[operand], LM1)
            self.assertEqual(assignments[operand].render(), "$ln0")

        self.assertEqual(
            builder.lines(),
            ("imm 0 $lr0; lpassa $ln[0,0,0,0] $ls[0,2,4,6]",),
        )

    def test_pe_virtual_flat_fails_when_same_kind_constraint_conflicts(self) -> None:
        builder = InstructionBuilder()
        only_lm0 = builder.new_memory_pe_virtual(600, 2)
        only_lm1 = builder.new_memory_pe_virtual(600, 2)
        other_lm1_a = builder.new_memory_pe_virtual(600, 2)
        other_lm1_b = builder.new_memory_pe_virtual(600, 2)

        with builder.cycle():
            builder.passa(
                precision="l",
                src_operand=only_lm0,
                dst_operands=[GRF0.auto(0)],
            )
            builder.passa(
                precision="l",
                src_operand=LM1.auto(0, vector=True),
                dst_operands=[GRF0.auto(2)],
            )

        with builder.cycle():
            builder.imm(payload=0, dst_operands=[GRF0.auto(4)])
            builder.passa(
                precision="l",
                src_operand=only_lm1,
                dst_operands=[GRF0.auto(6)],
            )
            builder.passa(
                precision="l",
                src_operand=other_lm1_a,
                dst_operands=[GRF0.auto(8)],
            )
            builder.passa(
                precision="l",
                src_operand=other_lm1_b,
                dst_operands=[GRF0.auto(10)],
            )

        with builder.cycle():
            builder.passa(
                precision="l",
                src_operand=builder.pe_virtual_flat(
                    [only_lm0, only_lm1, other_lm1_a, other_lm1_b]
                ),
                dst_operands=[GRF1.flat([0, 2, 4, 6])],
            )

        with self.assertRaisesRegex(
            RuntimeError,
            "same-kind",
        ):
            builder.lines()

    def test_new_memory_pe_virtual_can_allocate_to_treg_when_eligible(self) -> None:
        builder = InstructionBuilder()
        treg_candidate = builder.new_memory_pe_virtual(2, 2)

        with builder.cycle():
            builder.imm(payload=0, dst_operands=[GRF0.auto(0)])
            builder.passa(
                precision="l",
                src_operand=LM1.auto(0),
                dst_operands=[GRF0.auto(2)],
            )
            builder.passa(
                precision="l",
                src_operand=GRF1.auto(0),
                dst_operands=[LM0.auto(0)],
            )
            builder.passa(
                precision="l",
                src_operand=LM1.auto(2),
                dst_operands=[Nowrite()],
            )
            builder.passa(
                precision="l",
                src_operand=GRF1.auto(2),
                dst_operands=[Nowrite()],
            )
            builder.passa(
                precision="l",
                src_operand=treg_candidate,
                dst_operands=[Nowrite()],
            )

        assignments = builder.resolve_pe_virtual_operands()

        self.assertIsInstance(assignments[treg_candidate], TReg)
        self.assertEqual(assignments[treg_candidate].render(), "$lt")
        self.assertEqual(
            builder.lines(),
            (
                "imm 0 $lr0; lpassa $ln0 $lr2; lpassa $ls0 $lm0; lpassa $ln2 $nowrite; lpassa $ls2 $nowrite; lpassa $lt $nowrite",
            ),
        )

    def test_new_memory_pe_virtual_reports_when_treg_is_ineligible(self) -> None:
        builder = InstructionBuilder()
        treg_ineligible = builder.new_memory_pe_virtual(2, 2).as_vector(True)

        with builder.cycle():
            builder.imm(payload=0, dst_operands=[GRF0.auto(0)])
            builder.passa(
                precision="l",
                src_operand=LM1.auto(0),
                dst_operands=[GRF0.auto(2)],
            )
            builder.passa(
                precision="l",
                src_operand=GRF1.auto(0),
                dst_operands=[LM0.auto(0)],
            )
            builder.passa(
                precision="l",
                src_operand=LM1.auto(2),
                dst_operands=[Nowrite()],
            )
            builder.passa(
                precision="l",
                src_operand=GRF1.auto(2),
                dst_operands=[Nowrite()],
            )
            builder.passa(
                precision="l",
                src_operand=treg_ineligible,
                dst_operands=[Nowrite()],
            )

        with self.assertRaisesRegex(
            RuntimeError,
            r"TReg cannot be used because TReg has no vector addressing form",
        ):
            builder.lines()


class AutoAlufForwardingTests(unittest.TestCase):
    def test_auto_aluf_replaces_matching_alu_source_in_next_cycle(self) -> None:
        builder = InstructionBuilder()

        with builder.cycle():
            builder.add(
                precision="i",
                src_x_operand=GRF0.auto(0),
                src_y_operand=GRF0.auto(2),
                dst_operands=[GRF0.auto(4)],
            )

        with builder.cycle():
            builder.passa(
                precision="i",
                src_operand=GRF0.auto(4),
                dst_operands=[GRF0.auto(6)],
            )

        self.assertEqual(
            builder.lines(),
            ("iadd $lr0 $lr2 $lr4", "ipassa $aluf $lr6"),
        )

    def test_auto_aluf_replaces_matching_non_alu_source_use(self) -> None:
        builder = InstructionBuilder()

        with builder.cycle():
            builder.add(
                precision="i",
                src_x_operand=GRF0.auto(0),
                src_y_operand=GRF0.auto(2),
                dst_operands=[GRF0.auto(4)],
            )

        with builder.cycle():
            builder.l1bmd(src_operand=GRF0.auto(4), dst_l1bm=L1BM(addr=0))

        self.assertEqual(
            builder.lines(),
            ("iadd $lr0 $lr2 $lr4", "l1bmd $aluf $lb0"),
        )

    def test_auto_aluf_is_disabled_by_noforward(self) -> None:
        builder = InstructionBuilder()

        with builder.cycle():
            builder.add(
                precision="i",
                src_x_operand=GRF0.auto(0),
                src_y_operand=GRF0.auto(2),
                dst_operands=[GRF0.auto(4)],
            )
            builder.noforward()

        with builder.cycle():
            builder.passa(
                precision="i",
                src_operand=GRF0.auto(4),
                dst_operands=[GRF0.auto(6)],
            )

        self.assertEqual(
            builder.lines(),
            ("iadd $lr0 $lr2 $lr4; noforward", "ipassa $lr4 $lr6"),
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
        operand = DRAM(addr=0, dar_addr=3, group=0) + 2

        self.assertEqual(operand.render(), "$di3@0")

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
        self.assertEqual(operand.flat_addrs, [])

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
