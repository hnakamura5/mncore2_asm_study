from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .builder import InstructionBuilder


ROOT = Path(__file__).resolve().parent.parent
EMUENV_ROOT = ROOT / "mncore_judge" / "judge-py" / "mncore2_emuenv"
DEFAULT_JUDGE = ROOT / "mncore_judge" / "judge-py" / "judge.py"
DEFAULT_ASSEMBLER = EMUENV_ROOT / "assemble3"
DEFAULT_EMULATOR = EMUENV_ROOT / "gpfn3_package_main"


@dataclass(frozen=True)
class ProgramSource:
    text: str
    origin: str


@dataclass(frozen=True)
class RunArtifacts:
    workspace: Path
    vsm_path: Path
    asm_path: Path
    dump_path: Path
    dump_text: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render asm_wrapper output, assemble it with the bundled toolchain, and run the emulator."
    )
    parser.add_argument("input", help="Path to a .py builder script or a .vsm file")
    parser.add_argument(
        "--format",
        choices=("auto", "python", "vsm"),
        default="auto",
        help="Interpret INPUT as python or vsm. Auto chooses from the file extension.",
    )
    parser.add_argument(
        "--entry-function",
        default="build",
        help="Function name to call for Python inputs. It must return an InstructionBuilder or a VSM string.",
    )
    parser.add_argument(
        "--builder-variable",
        default="builder",
        help="Fallback variable name for a module-level InstructionBuilder.",
    )
    parser.add_argument(
        "--source-variable",
        default="source",
        help="Fallback variable name for a module-level VSM string.",
    )
    parser.add_argument(
        "--assembler",
        type=Path,
        default=DEFAULT_ASSEMBLER,
        help="Path to the assembler binary.",
    )
    parser.add_argument(
        "--judge-script",
        type=Path,
        default=DEFAULT_JUDGE,
        help="Path to the judge.py script used by --testcase mode.",
    )
    parser.add_argument(
        "--emulator",
        type=Path,
        default=DEFAULT_EMULATOR,
        help="Path to the emulator binary.",
    )
    parser.add_argument(
        "--testcase",
        type=Path,
        help="Run judge-compatible validation with this testcase.vsm after rendering INPUT.",
    )
    parser.add_argument(
        "--device",
        choices=("noto", "lime"),
        default="noto",
        help="Device profile. The wrapper mirrors judge.py defaults.",
    )
    parser.add_argument("--enable-get", action="store_true", help="Preserve 'd get*' in judge validation mode.")
    parser.add_argument("--enable-set", action="store_true", help="Preserve 'd set' in judge validation mode.")
    parser.add_argument("--seccomp-log", action="store_true", help="Enable the judge seccomp logger.")
    parser.add_argument("--seccomp", action="store_true", help="Enable the judge seccomp sandbox.")
    parser.add_argument("--dirty", action="store_true", help="Pass --dirty to the emulator.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Keep generated .vsm/.asm/.dmp files in this directory instead of a temporary directory.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the temporary artifact directory when --out-dir is not specified.",
    )
    parser.add_argument("--print-vsm", action="store_true", help="Print rendered VSM to stderr before assembling.")
    parser.add_argument("--print-asm", action="store_true", help="Print sanitized emulator input to stderr.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Print toolchain commands and artifact paths.")
    return parser.parse_args(argv)


def detect_format(input_path: Path, requested_format: str) -> str:
    if requested_format != "auto":
        return requested_format
    if input_path.suffix == ".py":
        return "python"
    return "vsm"


def load_program(input_path: Path, args: argparse.Namespace) -> ProgramSource:
    source_format = detect_format(input_path, args.format)
    if source_format == "python":
        return load_python_program(input_path, args)
    return ProgramSource(text=input_path.read_text(encoding="utf-8"), origin=str(input_path))


def load_python_program(input_path: Path, args: argparse.Namespace) -> ProgramSource:
    module = load_module(input_path)

    if hasattr(module, args.entry_function):
        entry = getattr(module, args.entry_function)
        if not callable(entry):
            raise TypeError(f"{input_path}: {args.entry_function} exists but is not callable")
        return coerce_program_source(entry(), f"{input_path}:{args.entry_function}()")

    if hasattr(module, args.builder_variable):
        return coerce_program_source(getattr(module, args.builder_variable), f"{input_path}:{args.builder_variable}")

    if hasattr(module, args.source_variable):
        return coerce_program_source(getattr(module, args.source_variable), f"{input_path}:{args.source_variable}")

    raise ValueError(
        f"{input_path}: expected {args.entry_function}(), {args.builder_variable}, or {args.source_variable}"
    )


def load_module(input_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_asm_wrapper_input_{input_path.stem}", input_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load Python source from {input_path}")

    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(input_path.parent.resolve()))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def coerce_program_source(value: Any, origin: str) -> ProgramSource:
    if isinstance(value, InstructionBuilder):
        return ProgramSource(text=value.to_source(), origin=origin)
    if isinstance(value, str):
        return ProgramSource(text=value, origin=origin)

    to_source = getattr(value, "to_source", None)
    if callable(to_source):
        rendered = to_source()
        if isinstance(rendered, str):
            return ProgramSource(text=rendered, origin=origin)

    raise TypeError(f"{origin} returned {type(value).__name__}, expected InstructionBuilder or str")


def sanitize_asm(asm: str, device: str) -> str:
    def is_valid_line(line: str) -> bool:
        tokens = line.split()
        if not tokens:
            return True
        if tokens[0] in {"j", "m", "d"}:
            return True
        if device == "lime" and tokens[0] == "i":
            return True
        return False

    return "\n".join(line for line in asm.splitlines() if is_valid_line(line))


def ensure_executable(path: Path, name: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"{name} not found: {resolved}")
    if not resolved.is_file():
        raise FileNotFoundError(f"{name} is not a file: {resolved}")
    if not os.access(resolved, os.X_OK):
        raise PermissionError(f"{name} is not executable: {resolved}. Run 'chmod +x {resolved}'")
    return resolved


def ensure_file(path: Path, name: str) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"{name} not found: {resolved}")
    if not resolved.is_file():
        raise FileNotFoundError(f"{name} is not a file: {resolved}")
    return resolved


def write_program_source(program: ProgramSource, workspace: Path, stem: str) -> Path:
    vsm_path = workspace / f"{stem}.vsm"
    vsm_path.write_text(program.text, encoding="utf-8")
    return vsm_path


def write_artifacts(
    program: ProgramSource,
    args: argparse.Namespace,
    workspace: Path,
    assembler: Path,
    emulator: Path,
    stem: str,
) -> RunArtifacts:
    vsm_path = write_program_source(program, workspace, stem)
    asm_path = workspace / f"{stem}.asm"
    dump_path = workspace / f"{stem}.dmp"

    assemble_cmd = [str(assembler)]
    if args.device != "lime":
        assemble_cmd += ["--instruction-mode", "flat"]
    assemble_cmd.append(str(vsm_path))

    assemble_result = subprocess.run(assemble_cmd, capture_output=True, text=True, check=False)
    if assemble_result.stderr:
        print(assemble_result.stderr, file=sys.stderr, end="")
    if assemble_result.returncode != 0:
        raise RuntimeError(f"assembler exited with code {assemble_result.returncode}")

    sanitized_asm = sanitize_asm(assemble_result.stdout, args.device)
    asm_path.write_text(sanitized_asm, encoding="utf-8")

    emulate_cmd = [str(emulator)]
    if args.device == "noto":
        emulate_cmd += ["--offchip-memory-init", "zero"]
    if args.dirty:
        emulate_cmd.append("--dirty")
    emulate_cmd += ["-i", str(asm_path), "-d", str(dump_path)]

    emulate_result = subprocess.run(emulate_cmd, capture_output=True, text=True, check=False)
    if emulate_result.stdout:
        print(emulate_result.stdout, file=sys.stderr, end="")
    if emulate_result.stderr:
        print(emulate_result.stderr, file=sys.stderr, end="")
    if emulate_result.returncode != 0:
        raise RuntimeError(f"emulator exited with code {emulate_result.returncode}")

    dump_text = dump_path.read_text(encoding="utf-8") if dump_path.exists() else ""
    return RunArtifacts(
        workspace=workspace,
        vsm_path=vsm_path,
        asm_path=asm_path,
        dump_path=dump_path,
        dump_text=dump_text,
    )


def run_judge_validation(
    *,
    args: argparse.Namespace,
    assembler: Path,
    emulator: Path,
    judge_script: Path,
    testcase_path: Path,
    rendered_vsm_path: Path,
) -> int:
    if args.print_asm:
        raise ValueError("--print-asm is not supported together with --testcase")

    judge_cmd = [
        sys.executable,
        str(judge_script),
        str(testcase_path),
        str(rendered_vsm_path),
        "--device",
        args.device,
        "--assembler",
        str(assembler),
        "--emulator",
        str(emulator),
    ]
    if args.enable_get:
        judge_cmd.append("--enable-get")
    if args.enable_set:
        judge_cmd.append("--enable-set")
    if args.seccomp_log:
        judge_cmd.append("--seccomp-log")
    if args.seccomp:
        judge_cmd.append("--seccomp")
    if args.dirty:
        judge_cmd.append("--dirty")
    if args.verbose:
        judge_cmd.append("-v")

    judge_result = subprocess.run(judge_cmd, capture_output=True, text=True, check=False)
    if judge_result.stdout:
        print(judge_result.stdout, end="")
    if judge_result.stderr:
        print(judge_result.stderr, file=sys.stderr, end="")
    if judge_result.returncode != 0:
        raise RuntimeError(f"judge exited with code {judge_result.returncode}")
    return 0


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input).expanduser().resolve()
    assembler = ensure_executable(args.assembler, "assembler")
    emulator = ensure_executable(args.emulator, "emulator")
    testcase_path = ensure_file(args.testcase, "testcase") if args.testcase is not None else None
    judge_script = ensure_file(args.judge_script, "judge script") if testcase_path is not None else None
    program = load_program(input_path, args)

    if args.print_vsm:
        print("----- rendered vsm -----", file=sys.stderr)
        print(program.text, file=sys.stderr)

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.out_dir is not None:
        workspace = args.out_dir.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="mncore_run_")
        workspace = Path(temp_dir.name)

    stem = input_path.stem or "program"

    try:
        if testcase_path is not None:
            assert judge_script is not None
            rendered_vsm_path = write_program_source(program, workspace, stem)
            if args.verbose:
                print(f"source: {program.origin}", file=sys.stderr)
                print(f"testcase: {testcase_path}", file=sys.stderr)
                print(f"judge: {judge_script}", file=sys.stderr)
                print(f"assembler: {assembler}", file=sys.stderr)
                print(f"emulator: {emulator}", file=sys.stderr)
                print(f"artifacts: {workspace}", file=sys.stderr)
            return run_judge_validation(
                args=args,
                assembler=assembler,
                emulator=emulator,
                judge_script=judge_script,
                testcase_path=testcase_path,
                rendered_vsm_path=rendered_vsm_path,
            )

        artifacts = write_artifacts(program, args, workspace, assembler, emulator, stem)
        if args.print_asm:
            print("----- emulator input asm -----", file=sys.stderr)
            print(artifacts.asm_path.read_text(encoding="utf-8"), file=sys.stderr)
        if args.verbose:
            print(f"source: {program.origin}", file=sys.stderr)
            print(f"assembler: {assembler}", file=sys.stderr)
            print(f"emulator: {emulator}", file=sys.stderr)
            print(f"artifacts: {artifacts.workspace}", file=sys.stderr)
        print(artifacts.dump_text, end="")
        if temp_dir is not None and args.keep_temp:
            temp_dir.cleanup = lambda: None
            print(f"kept temporary artifacts at {artifacts.workspace}", file=sys.stderr)
        return 0
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def main() -> None:
    try:
        raise SystemExit(run())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
