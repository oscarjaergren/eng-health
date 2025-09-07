"""Docstring standardization utility following PEP 257 conventions."""

import ast
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import logging


class DocstringStandardizer:
    """
    Utility for standardizing docstrings according to PEP 257 and Google/NumPy style guides.

    This class provides methods to:
    - Analyze existing docstring quality and consistency
    - Generate standardized docstrings for functions and classes
    - Validate docstring format and completeness
    - Suggest improvements for existing docstrings
    """

    def __init__(self, style: str = "google", logger: Optional[logging.Logger] = None):
        """
        Initialize the docstring standardizer.

        Args:
            style: Docstring style to use ("google", "numpy", or "sphinx")
            logger: Optional logger instance for structured logging

        Raises:
            ValueError: If an unsupported style is specified
        """
        if style not in ["google", "numpy", "sphinx"]:
            raise ValueError(f"Unsupported docstring style: {style}")

        self.style = style
        self.logger = logger or logging.getLogger(__name__)

        # Docstring templates for different styles
        self.templates = {
            "google": {
                "function": '''"""
{summary}

{description}

Args:
{args}

Returns:
{returns}

Raises:
{raises}
"""''',
                "class": '''"""
{summary}

{description}

Attributes:
{attributes}
"""''',
                "method": '''"""
{summary}

{description}

Args:
{args}

Returns:
{returns}

Raises:
{raises}
"""''',
            }
        }

    def analyze_docstring_coverage(self, file_path: Path) -> Dict[str, Any]:
        """
        Analyze docstring coverage and quality for a Python file.

        Args:
            file_path: Path to the Python file to analyze

        Returns:
            Dictionary containing docstring analysis results

        Raises:
            FileNotFoundError: If the file doesn't exist
            SyntaxError: If the file has syntax errors
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                source_code = f.read()

            tree = ast.parse(source_code)

            analysis = {
                "file_path": str(file_path),
                "module_docstring": None,
                "total_functions": 0,
                "functions_with_docstrings": 0,
                "total_classes": 0,
                "classes_with_docstrings": 0,
                "total_methods": 0,
                "methods_with_docstrings": 0,
                "docstring_coverage_percentage": 0.0,
                "missing_docstrings": [],
                "docstring_quality_issues": [],
            }

            # Check module docstring
            if (
                tree.body
                and isinstance(tree.body[0], ast.Expr)
                and isinstance(tree.body[0].value, ast.Constant)
                and isinstance(tree.body[0].value.value, str)
            ):
                analysis["module_docstring"] = tree.body[0].value.value

            # Analyze classes and functions
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    analysis["total_classes"] += 1
                    docstring = ast.get_docstring(node)

                    if docstring:
                        analysis["classes_with_docstrings"] += 1
                        # Analyze docstring quality
                        quality_issues = self._analyze_docstring_quality(
                            docstring, node.name, "class"
                        )
                        if quality_issues:
                            analysis["docstring_quality_issues"].extend(quality_issues)
                    else:
                        analysis["missing_docstrings"].append(
                            {"type": "class", "name": node.name, "line": node.lineno}
                        )

                    # Analyze methods within the class
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            analysis["total_methods"] += 1
                            method_docstring = ast.get_docstring(item)

                            if method_docstring:
                                analysis["methods_with_docstrings"] += 1
                                quality_issues = self._analyze_docstring_quality(
                                    method_docstring,
                                    f"{node.name}.{item.name}",
                                    "method",
                                )
                                if quality_issues:
                                    analysis["docstring_quality_issues"].extend(
                                        quality_issues
                                    )
                            else:
                                # Skip special methods like __init__, __str__, etc.
                                if not (
                                    item.name.startswith("_")
                                    and item.name.endswith("_")
                                ):
                                    analysis["missing_docstrings"].append(
                                        {
                                            "type": "method",
                                            "name": f"{node.name}.{item.name}",
                                            "line": item.lineno,
                                        }
                                    )

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Only count top-level functions (not methods)
                    if not any(
                        isinstance(parent, ast.ClassDef)
                        for parent in ast.walk(tree)
                        if hasattr(parent, "body")
                        and node in getattr(parent, "body", [])
                    ):
                        analysis["total_functions"] += 1
                        docstring = ast.get_docstring(node)

                        if docstring:
                            analysis["functions_with_docstrings"] += 1
                            quality_issues = self._analyze_docstring_quality(
                                docstring, node.name, "function"
                            )
                            if quality_issues:
                                analysis["docstring_quality_issues"].extend(
                                    quality_issues
                                )
                        else:
                            analysis["missing_docstrings"].append(
                                {
                                    "type": "function",
                                    "name": node.name,
                                    "line": node.lineno,
                                }
                            )

            # Calculate overall coverage
            total_items = (
                analysis["total_functions"]
                + analysis["total_classes"]
                + analysis["total_methods"]
            )
            items_with_docstrings = (
                analysis["functions_with_docstrings"]
                + analysis["classes_with_docstrings"]
                + analysis["methods_with_docstrings"]
            )

            if total_items > 0:
                analysis["docstring_coverage_percentage"] = (
                    items_with_docstrings / total_items
                ) * 100

            return analysis

        except SyntaxError as e:
            raise SyntaxError(f"Syntax error in {file_path}: {e}")
        except Exception as e:
            self.logger.error(f"Error analyzing file {file_path}: {e}")
            raise

    def _analyze_docstring_quality(
        self, docstring: str, name: str, item_type: str
    ) -> List[Dict[str, str]]:
        """
        Analyze the quality of a docstring and identify issues.

        Args:
            docstring: The docstring text to analyze
            name: Name of the function/class/method
            item_type: Type of item ("function", "class", "method")

        Returns:
            List of quality issues found
        """
        issues = []

        # Check for empty or too short docstrings
        if len(docstring.strip()) < 10:
            issues.append(
                {
                    "name": name,
                    "type": item_type,
                    "issue": "Docstring too short or empty",
                    "severity": "high",
                }
            )
            return issues

        # Check for proper summary line
        lines = docstring.strip().split("\n")
        summary_line = lines[0].strip()

        if not summary_line:
            issues.append(
                {
                    "name": name,
                    "type": item_type,
                    "issue": "Missing summary line",
                    "severity": "high",
                }
            )
        elif not summary_line.endswith("."):
            issues.append(
                {
                    "name": name,
                    "type": item_type,
                    "issue": "Summary line should end with a period",
                    "severity": "medium",
                }
            )
        elif len(summary_line) > 79:
            issues.append(
                {
                    "name": name,
                    "type": item_type,
                    "issue": "Summary line too long (>79 characters)",
                    "severity": "medium",
                }
            )

        # Check for proper sections based on style
        if self.style == "google":
            self._check_google_style_sections(docstring, name, item_type, issues)

        return issues

    def _check_google_style_sections(
        self, docstring: str, name: str, item_type: str, issues: List[Dict[str, str]]
    ) -> None:
        """Check for proper Google-style docstring sections."""
        # Look for common sections
        has_args = "Args:" in docstring or "Arguments:" in docstring
        has_returns = "Returns:" in docstring or "Return:" in docstring
        has_raises = "Raises:" in docstring or "Raise:" in docstring

        # For functions and methods, check if Args section is needed
        if item_type in ["function", "method"]:
            # This is a simplified check - in practice, you'd parse the AST to check parameters
            if "(" in name and not has_args:
                issues.append(
                    {
                        "name": name,
                        "type": item_type,
                        "issue": "Missing Args section for function with parameters",
                        "severity": "medium",
                    }
                )

            if "return" in docstring.lower() and not has_returns:
                issues.append(
                    {
                        "name": name,
                        "type": item_type,
                        "issue": "Missing Returns section",
                        "severity": "medium",
                    }
                )

    def generate_standard_docstring(
        self, node: ast.AST, existing_docstring: Optional[str] = None
    ) -> str:
        """
        Generate a standardized docstring for a function or class.

        Args:
            node: AST node representing the function or class
            existing_docstring: Existing docstring to enhance (optional)

        Returns:
            Generated standardized docstring

        Raises:
            ValueError: If the node type is not supported
        """
        if isinstance(node, ast.ClassDef):
            return self._generate_class_docstring(node, existing_docstring)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return self._generate_function_docstring(node, existing_docstring)
        else:
            raise ValueError(f"Unsupported node type: {type(node)}")

    def _generate_function_docstring(
        self, node: ast.FunctionDef, existing_docstring: Optional[str] = None
    ) -> str:
        """Generate standardized docstring for a function."""
        # Extract function information
        function_name = node.name
        args = []

        # Process arguments
        for arg in node.args.args:
            if arg.arg not in ["self", "cls"]:
                arg_info = {
                    "name": arg.arg,
                    "type": ast.unparse(arg.annotation) if arg.annotation else "Any",
                    "description": f"Description for {arg.arg}",
                }
                args.append(arg_info)

        # Determine return type
        return_type = "None"
        if node.returns:
            return_type = ast.unparse(node.returns)

        # Generate summary based on function name
        summary = self._generate_summary_from_name(function_name, "function")

        # Build docstring components
        args_section = ""
        if args:
            args_lines = []
            for arg in args:
                args_lines.append(
                    f"            {arg['name']} ({arg['type']}): {arg['description']}"
                )
            args_section = "\n".join(args_lines)

        returns_section = f"            {return_type}: Description of return value"
        raises_section = (
            "            Exception: Description of when this exception is raised"
        )

        # Use template
        template = self.templates[self.style]["function"]
        docstring = template.format(
            summary=summary,
            description="Detailed description of the function.",
            args=args_section if args_section else "            None",
            returns=returns_section,
            raises=raises_section,
        )

        return docstring.strip()

    def _generate_class_docstring(
        self, node: ast.ClassDef, existing_docstring: Optional[str] = None
    ) -> str:
        """Generate standardized docstring for a class."""
        class_name = node.name

        # Extract class attributes (simplified)
        attributes = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                attr_info = {
                    "name": item.target.id,
                    "type": ast.unparse(item.annotation) if item.annotation else "Any",
                    "description": f"Description for {item.target.id}",
                }
                attributes.append(attr_info)

        # Generate summary
        summary = self._generate_summary_from_name(class_name, "class")

        # Build attributes section
        attributes_section = ""
        if attributes:
            attr_lines = []
            for attr in attributes:
                attr_lines.append(
                    f"        {attr['name']} ({attr['type']}): {attr['description']}"
                )
            attributes_section = "\n".join(attr_lines)

        # Use template
        template = self.templates[self.style]["class"]
        docstring = template.format(
            summary=summary,
            description="Detailed description of the class.",
            attributes=attributes_section if attributes_section else "        None",
        )

        return docstring.strip()

    def _generate_summary_from_name(self, name: str, item_type: str) -> str:
        """Generate a summary line based on the name and type."""
        # Convert camelCase/PascalCase to words
        words = re.sub(r"([A-Z])", r" \1", name).strip().lower().split()

        if item_type == "function":
            if name.startswith("get_") or name.startswith("fetch_"):
                return f"Get {' '.join(words[1:])}."
            elif name.startswith("set_") or name.startswith("update_"):
                return f"Set {' '.join(words[1:])}."
            elif name.startswith("create_") or name.startswith("build_"):
                return f"Create {' '.join(words[1:])}."
            elif name.startswith("delete_") or name.startswith("remove_"):
                return f"Delete {' '.join(words[1:])}."
            elif name.startswith("is_") or name.startswith("has_"):
                return f"Check if {' '.join(words[1:])}."
            else:
                return f"Execute {' '.join(words)} operation."

        elif item_type == "class":
            return f"{' '.join(words).title()} class."

        return f"{' '.join(words).capitalize()}."

    def generate_improvement_suggestions(self, analysis: Dict[str, Any]) -> List[str]:
        """
        Generate improvement suggestions based on docstring analysis.

        Args:
            analysis: Results from analyze_docstring_coverage

        Returns:
            List of improvement suggestions
        """
        suggestions = []

        # Coverage suggestions
        coverage = analysis["docstring_coverage_percentage"]
        if coverage < 50:
            suggestions.append(
                f"Low docstring coverage ({coverage:.1f}%). Consider adding docstrings "
                "to improve code documentation."
            )
        elif coverage < 80:
            suggestions.append(
                f"Moderate docstring coverage ({coverage:.1f}%). Add docstrings to "
                "remaining functions and classes."
            )

        # Missing module docstring
        if not analysis["module_docstring"]:
            suggestions.append(
                "Add a module-level docstring describing the purpose and contents of this module."
            )

        # Quality issues
        high_priority_issues = [
            issue
            for issue in analysis["docstring_quality_issues"]
            if issue["severity"] == "high"
        ]

        if high_priority_issues:
            suggestions.append(
                f"Fix {len(high_priority_issues)} high-priority docstring quality issues."
            )

        # Specific missing docstrings
        missing_functions = [
            item
            for item in analysis["missing_docstrings"]
            if item["type"] == "function"
        ]

        if missing_functions:
            suggestions.append(
                f"Add docstrings to {len(missing_functions)} functions: "
                f"{', '.join([item['name'] for item in missing_functions[:3]])}..."
            )

        return suggestions

    def generate_docstring_report(self, analysis: Dict[str, Any]) -> str:
        """
        Generate a comprehensive docstring quality report.

        Args:
            analysis: Results from analyze_docstring_coverage

        Returns:
            Formatted report as string
        """
        report = []
        report.append(f"Docstring Quality Report: {Path(analysis['file_path']).name}")
        report.append("=" * 60)
        report.append(
            f"Overall Coverage: {analysis['docstring_coverage_percentage']:.1f}%"
        )
        report.append("")

        # Coverage breakdown
        report.append("Coverage Breakdown:")
        report.append(
            f"  Functions: {analysis['functions_with_docstrings']}/{analysis['total_functions']}"
        )
        report.append(
            f"  Classes: {analysis['classes_with_docstrings']}/{analysis['total_classes']}"
        )
        report.append(
            f"  Methods: {analysis['methods_with_docstrings']}/{analysis['total_methods']}"
        )
        report.append("")

        # Missing docstrings
        if analysis["missing_docstrings"]:
            report.append("Missing Docstrings:")
            for missing in analysis["missing_docstrings"]:
                report.append(
                    f"  • {missing['type'].title()}: {missing['name']} (line {missing['line']})"
                )
            report.append("")

        # Quality issues
        if analysis["docstring_quality_issues"]:
            report.append("Quality Issues:")
            for issue in analysis["docstring_quality_issues"]:
                severity_marker = "⚠️" if issue["severity"] == "high" else "💡"
                report.append(f"  {severity_marker} {issue['name']}: {issue['issue']}")
            report.append("")

        # Improvement suggestions
        suggestions = self.generate_improvement_suggestions(analysis)
        if suggestions:
            report.append("Improvement Suggestions:")
            for i, suggestion in enumerate(suggestions, 1):
                report.append(f"  {i}. {suggestion}")

        return "\n".join(report)
