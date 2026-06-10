from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "bin" / "python"
MAIN = ROOT / "main.py"
ASSEMBLER = ROOT / "mncore_judge" / "judge-py" / "mncore2_emuenv" / "assemble3"
EMULATOR = ROOT / "mncore_judge" / "judge-py" / "mncore2_emuenv" / "gpfn3_package_main"
SAMPLE = ROOT / "examples" / "peid_lm0_sample.py"
TESTCASE = ROOT / "examples" / "peid_lm0_testcase.vsm"
MV_SAMPLE = ROOT / "examples" / "mv_to_dram_sample.py"
MV_SAMPLE_VSM = ROOT / "examples" / "mv_to_dram_sample.vsm"
EXPECTED_DIR = ROOT / "tests" / "expected"


def ensure_toolchain_executable() -> None:
    for binary in (ASSEMBLER, EMULATOR):
        mode = binary.stat().st_mode
        binary.chmod(mode | stat.S_IXUSR)


class RunnerCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_toolchain_executable()

    def run_cli(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(PYTHON), str(MAIN), *(str(arg) for arg in args)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            env=os.environ.copy(),
        )

    def read_expected(self, name: str) -> str:
        text = (EXPECTED_DIR / name).read_text(encoding="utf-8")
        if not text.endswith("\n"):
            text += "\n"
        return text

    def test_instruction_builder_example_runs(self) -> None:
        result = self.run_cli(SAMPLE)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout, self.read_expected("peid_lm0_sample.dump.txt"))

    def test_instruction_builder_example_passes_judge_mode(self) -> None:
        result = self.run_cli(SAMPLE, "--testcase", TESTCASE)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout, self.read_expected("peid_lm0_sample.judge.txt"))

    def test_mv_instruction_builder_example_runs(self) -> None:
        result = self.run_cli(MV_SAMPLE)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout, self.read_expected("mv_to_dram_sample.dump.txt")
        )

    def test_direct_vsm_input_runs_and_matches_expected_dump(self) -> None:
        result = self.run_cli(MV_SAMPLE_VSM)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(
            result.stdout, self.read_expected("mv_to_dram_sample.dump.txt")
        )

    def test_out_dir_writes_dump_matching_expected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mncore_runner_test_") as temp_dir:
            out_dir = Path(temp_dir)
            result = self.run_cli(MV_SAMPLE_VSM, "--out-dir", out_dir)

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertEqual(
                result.stdout, self.read_expected("mv_to_dram_sample.dump.txt")
            )
            self.assertTrue((out_dir / "mv_to_dram_sample.vsm").exists())
            self.assertTrue((out_dir / "mv_to_dram_sample.asm").exists())
            self.assertEqual(
                (out_dir / "mv_to_dram_sample.dmp").read_text(encoding="utf-8"),
                self.read_expected("mv_to_dram_sample.dump.txt"),
            )

    def test_python_builder_exception_surfaces_traceback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mncore_runner_error_") as temp_dir:
            script_path = Path(temp_dir) / "broken_program.py"
            script_path.write_text(
                "from asm_wrapper import InstructionBuilder\n"
                "\n"
                "def build():\n"
                "    InstructionBuilder()\n"
                "    raise RuntimeError('intentional builder failure')\n",
                encoding="utf-8",
            )

            result = self.run_cli(script_path)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Traceback", result.stderr)
            self.assertIn("intentional builder failure", result.stderr)


if __name__ == "__main__":
    unittest.main()
