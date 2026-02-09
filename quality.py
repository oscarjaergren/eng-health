#!/usr/bin/env python3
"""
Comprehensive code quality management tool.
Handles formatting, linting, type checking, and automated fixes.
"""
import argparse
import subprocess
import sys
from pathlib import Path


class CodeQualityManager:
    """Manages all code quality operations in one place."""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)
        self.source_dirs = ["pr_analytics/", "tests/"]

    def run_command(self, cmd: list[str], description: str) -> bool:
        """Run a command and return success status."""
        print(f"\n{'='*50}")
        print(f"Running {description}")
        print(f"{'='*50}")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=self.project_root
            )
            print(f"Exit code: {result.returncode}")

            if result.stdout:
                print("STDOUT:")
                print(result.stdout)
            if result.stderr:
                print("STDERR:")
                print(result.stderr)

            return result.returncode == 0
        except Exception as e:
            print(f"Error running command: {e}")
            return False

    def check_tools_installed(self) -> bool:
        """Check if all required tools are available."""
        tools = ["black", "isort", "autoflake", "flake8", "mypy", "autopep8"]
        missing = []

        for tool in tools:
            try:
                subprocess.run(
                    [sys.executable, "-m", tool, "--version"],
                    capture_output=True,
                    check=True,
                )
            except subprocess.CalledProcessError:
                missing.append(tool)

        if missing:
            print(f"Missing tools: {', '.join(missing)}")
            print("Install with: pip install --user " + " ".join(missing))
            return False
        return True

    def auto_fix(self) -> bool:
        """Run all auto-formatters to fix code quality issues."""
        print("Running automated code quality fixes...")

        # 1. Remove unused imports and variables
        autoflake_success = self.run_command(
            [sys.executable, "-m", "autoflake", "--remove-all-unused-imports", "--remove-unused-variables", "--in-place", "--recursive"] + self.source_dirs,
            "AutoFlake (Remove unused imports/variables)",
        )

        # 2. Sort and organize imports
        isort_success = self.run_command(
            [sys.executable, "-m", "isort"] + self.source_dirs + ["--profile", "black"],
            "isort (Sort imports)",
        )

        # 3. Fix PEP 8 violations
        autopep8_success = self.run_command(
            [sys.executable, "-m", "autopep8", "--in-place", "--aggressive", "--aggressive", "--recursive"] + self.source_dirs,
            "autopep8 (Fix PEP 8 violations)",
        )

        # 4. Apply Black formatting (final pass)
        black_success = self.run_command(
            [sys.executable, "-m", "black"] + self.source_dirs,
            "Black (Final formatting)",
        )

        results = {
            "AutoFlake": autoflake_success,
            "isort": isort_success,
            "autopep8": autopep8_success,
            "Black": black_success,
        }

        self._print_results("AUTO-FIX SUMMARY", results)
        return all(results.values())

    def check(self, strict: bool = False) -> bool:
        """Run code quality checks."""
        print("Running code quality checks...")

        # Flake8 linting
        ignore_codes = "E203,W503" if strict else "E203,W503,E501,F541"
        flake8_success = self.run_command(
            [sys.executable, "-m", "flake8"] + self.source_dirs + ["--max-line-length=88", f"--extend-ignore={ignore_codes}"],
            "Flake8 (Linting)",
        )

        # MyPy type checking
        mypy_args = ["--ignore-missing-imports", "--no-strict-optional"]

        mypy_success = self.run_command(
            [sys.executable, "-m", "mypy", "pr_analytics/"] + mypy_args,
            "MyPy (Type checking)",
        )

        # Black formatting check
        black_success = self.run_command(
            [sys.executable, "-m", "black", "--check", "--diff"] + self.source_dirs,
            "Black (Format check)",
        )

        results = {
            "Flake8": flake8_success,
            "MyPy": mypy_success,
            "Black": black_success,
        }

        self._print_results("QUALITY CHECK SUMMARY", results)
        return all(results.values())

    def fix_and_check(self, strict: bool = False) -> bool:
        """Run auto-fixes followed by quality checks."""
        print("Running complete code quality workflow...")

        fix_success = self.auto_fix()
        check_success = self.check(strict=strict)

        print(f"\n{'='*50}")
        print("FINAL WORKFLOW SUMMARY")
        print(f"{'='*50}")
        print(f"Auto-fixes: {'PASS' if fix_success else 'FAIL'}")
        print(f"Quality checks: {'PASS' if check_success else 'FAIL'}")

        if fix_success and check_success:
            print("\nAll code quality operations completed successfully!")
        elif fix_success:
            print("\nAuto-fixes completed, but some quality issues remain.")
            print("Consider running with --strict for detailed type checking.")
        else:
            print("\nSome operations failed. Check the output above for details.")

        return fix_success and check_success

    def install_pre_commit(self) -> bool:
        """Install and configure pre-commit hooks."""
        print("Setting up pre-commit hooks...")

        # Create pre-commit config if it doesn't exist
        config_path = self.project_root / ".pre-commit-config.yaml"
        if not config_path.exists():
            config_content = """repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.4.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files

  - repo: https://github.com/pycqa/isort
    rev: 5.12.0
    hooks:
      - id: isort
        args: ["--profile", "black"]

  - repo: https://github.com/pycqa/autoflake
    rev: v2.2.1
    hooks:
      - id: autoflake
        args: [
          "--remove-all-unused-imports",
          "--remove-unused-variables",
          "--in-place"
        ]

  - repo: https://github.com/psf/black
    rev: 23.7.0
    hooks:
      - id: black

  - repo: https://github.com/pycqa/flake8
    rev: 6.0.0
    hooks:
      - id: flake8
        args: ["--max-line-length=88", "--extend-ignore=E203,W503"]
"""
            with open(config_path, "w") as f:
                f.write(config_content)
            print(f"Created {config_path}")

        # Install pre-commit
        install_success = self.run_command(
            [sys.executable, "-m", "pip", "install", "--user", "pre-commit"],
            "Install pre-commit",
        )

        if install_success:
            setup_success = self.run_command(
                [sys.executable, "-m", "pre_commit", "install"],
                "Setup pre-commit hooks",
            )
            return setup_success

        return False

    def _print_results(self, title: str, results: dict):
        """Print formatted results summary."""
        print(f"\n{'='*50}")
        print(title)
        print(f"{'='*50}")
        for tool, success in results.items():
            status = "PASS" if success else "FAIL"
            print(f"{tool}: {status}")


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(
        description="Comprehensive code quality management tool"
    )
    parser.add_argument(
        "action",
        choices=["check", "fix", "auto", "pre-commit"],
        help="Action to perform: check=run checks only, fix=run auto-fixes only, auto=fix then check, pre-commit=setup hooks",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Use strict quality checking (more type errors)",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root directory (default: current directory)",
    )

    args = parser.parse_args()

    manager = CodeQualityManager(args.project_root)

    # Check if tools are available
    if not manager.check_tools_installed():
        return 1

    if args.action == "check":
        success = manager.check(strict=args.strict)
    elif args.action == "fix":
        success = manager.auto_fix()
    elif args.action == "auto":
        success = manager.fix_and_check(strict=args.strict)
    elif args.action == "pre-commit":
        success = manager.install_pre_commit()
    else:
        parser.print_help()
        return 1

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
