"""Type hints enhancement utility for improving code quality and IDE support."""

import ast
import inspect
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union, Callable, Type
import logging


class TypeHintsEnhancer:
    """
    Utility class for analyzing and enhancing type hints coverage in Python files.
    
    This class provides methods to:
    - Analyze existing type hints coverage
    - Suggest type hints for functions and methods
    - Generate comprehensive type annotations
    - Validate type hint consistency
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the type hints enhancer.
        
        Args:
            logger: Optional logger instance for structured logging
        """
        self.logger = logger or logging.getLogger(__name__)
        
        # Common type mappings for inference
        self.type_mappings = {
            'str': 'str',
            'int': 'int',
            'float': 'float',
            'bool': 'bool',
            'list': 'List[Any]',
            'dict': 'Dict[str, Any]',
            'tuple': 'Tuple[Any, ...]',
            'set': 'Set[Any]',
            'None': 'None',
            'NoneType': 'None'
        }
    
    def analyze_file_coverage(self, file_path: Path) -> Dict[str, Any]:
        """
        Analyze type hints coverage for a Python file.
        
        Args:
            file_path: Path to the Python file to analyze
            
        Returns:
            Dictionary containing coverage analysis results
            
        Raises:
            FileNotFoundError: If the file doesn't exist
            SyntaxError: If the file has syntax errors
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source_code = f.read()
            
            tree = ast.parse(source_code)
            
            analysis = {
                'file_path': str(file_path),
                'total_functions': 0,
                'functions_with_hints': 0,
                'total_parameters': 0,
                'parameters_with_hints': 0,
                'functions_with_return_hints': 0,
                'coverage_percentage': 0.0,
                'missing_hints': [],
                'suggestions': []
            }
            
            # Analyze functions and methods
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    analysis['total_functions'] += 1
                    
                    # Check function parameters
                    has_param_hints = True
                    missing_params = []
                    
                    for arg in node.args.args:
                        analysis['total_parameters'] += 1
                        if arg.annotation is None and arg.arg != 'self' and arg.arg != 'cls':
                            has_param_hints = False
                            missing_params.append(arg.arg)
                        elif arg.annotation is not None:
                            analysis['parameters_with_hints'] += 1
                    
                    # Check return type hint
                    has_return_hint = node.returns is not None
                    if has_return_hint:
                        analysis['functions_with_return_hints'] += 1
                    
                    # Track functions with complete hints
                    if has_param_hints and has_return_hint:
                        analysis['functions_with_hints'] += 1
                    else:
                        missing_info = {
                            'function_name': node.name,
                            'line_number': node.lineno,
                            'missing_parameters': missing_params,
                            'missing_return_hint': not has_return_hint
                        }
                        analysis['missing_hints'].append(missing_info)
            
            # Calculate coverage percentage
            if analysis['total_functions'] > 0:
                analysis['coverage_percentage'] = (
                    analysis['functions_with_hints'] / analysis['total_functions']
                ) * 100
            
            return analysis
            
        except SyntaxError as e:
            raise SyntaxError(f"Syntax error in {file_path}: {e}")
        except Exception as e:
            self.logger.error(f"Error analyzing file {file_path}: {e}")
            raise
    
    def suggest_type_hints(self, function_node: ast.FunctionDef, 
                          context: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """
        Suggest type hints for a function based on analysis.
        
        Args:
            function_node: AST node representing the function
            context: Optional context information for better inference
            
        Returns:
            Dictionary mapping parameter names to suggested type hints
        """
        suggestions = {}
        
        # Analyze function body for type clues
        for node in ast.walk(function_node):
            # Look for variable assignments and operations
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        # Infer type from assignment value
                        suggested_type = self._infer_type_from_value(node.value)
                        if suggested_type and target.id in [arg.arg for arg in function_node.args.args]:
                            suggestions[target.id] = suggested_type
        
        # Default suggestions based on common patterns
        for arg in function_node.args.args:
            if arg.arg not in suggestions and arg.arg not in ['self', 'cls']:
                # Use naming conventions for hints
                if 'id' in arg.arg.lower() or arg.arg.endswith('_id'):
                    suggestions[arg.arg] = 'int'
                elif 'name' in arg.arg.lower() or 'title' in arg.arg.lower():
                    suggestions[arg.arg] = 'str'
                elif 'count' in arg.arg.lower() or 'size' in arg.arg.lower():
                    suggestions[arg.arg] = 'int'
                elif 'data' in arg.arg.lower():
                    suggestions[arg.arg] = 'Dict[str, Any]'
                elif 'list' in arg.arg.lower() or arg.arg.endswith('s'):
                    suggestions[arg.arg] = 'List[Any]'
                elif 'config' in arg.arg.lower():
                    suggestions[arg.arg] = 'Config'
                elif 'logger' in arg.arg.lower():
                    suggestions[arg.arg] = 'logging.Logger'
                else:
                    suggestions[arg.arg] = 'Any'
        
        return suggestions
    
    def _infer_type_from_value(self, value_node: ast.AST) -> Optional[str]:
        """
        Infer type from an AST value node.
        
        Args:
            value_node: AST node representing a value
            
        Returns:
            Suggested type hint as string, or None if cannot infer
        """
        if isinstance(value_node, ast.Constant):
            value_type = type(value_node.value).__name__
            return self.type_mappings.get(value_type)
        
        elif isinstance(value_node, ast.List):
            return 'List[Any]'
        
        elif isinstance(value_node, ast.Dict):
            return 'Dict[str, Any]'
        
        elif isinstance(value_node, ast.Tuple):
            return 'Tuple[Any, ...]'
        
        elif isinstance(value_node, ast.Set):
            return 'Set[Any]'
        
        elif isinstance(value_node, ast.Call):
            if isinstance(value_node.func, ast.Name):
                func_name = value_node.func.id
                if func_name == 'list':
                    return 'List[Any]'
                elif func_name == 'dict':
                    return 'Dict[str, Any]'
                elif func_name == 'set':
                    return 'Set[Any]'
                elif func_name == 'tuple':
                    return 'Tuple[Any, ...]'
        
        return None
    
    def generate_enhanced_function_signature(self, 
                                           function_node: ast.FunctionDef,
                                           suggestions: Dict[str, str]) -> str:
        """
        Generate an enhanced function signature with type hints.
        
        Args:
            function_node: AST node representing the function
            suggestions: Dictionary of suggested type hints
            
        Returns:
            Enhanced function signature as string
        """
        # Build parameter list with type hints
        params = []
        
        for arg in function_node.args.args:
            param_str = arg.arg
            
            # Add type hint if available
            if arg.annotation:
                # Keep existing annotation
                param_str += f": {ast.unparse(arg.annotation)}"
            elif arg.arg in suggestions:
                # Add suggested type hint
                param_str += f": {suggestions[arg.arg]}"
            
            params.append(param_str)
        
        # Add return type hint
        return_hint = ""
        if function_node.returns:
            return_hint = f" -> {ast.unparse(function_node.returns)}"
        else:
            # Suggest return type based on function name and content
            if function_node.name.startswith('get_') or function_node.name.startswith('fetch_'):
                return_hint = " -> Optional[Any]"
            elif function_node.name.startswith('is_') or function_node.name.startswith('has_'):
                return_hint = " -> bool"
            elif function_node.name.startswith('create_') or function_node.name.startswith('build_'):
                return_hint = " -> Any"
            else:
                return_hint = " -> None"
        
        signature = f"def {function_node.name}({', '.join(params)}){return_hint}:"
        return signature
    
    def analyze_project_coverage(self, project_path: Path) -> Dict[str, Any]:
        """
        Analyze type hints coverage for an entire project.
        
        Args:
            project_path: Path to the project directory
            
        Returns:
            Dictionary containing project-wide coverage analysis
        """
        project_analysis = {
            'project_path': str(project_path),
            'total_files': 0,
            'analyzed_files': 0,
            'total_functions': 0,
            'functions_with_hints': 0,
            'overall_coverage_percentage': 0.0,
            'file_analyses': [],
            'top_files_needing_improvement': []
        }
        
        # Find all Python files
        python_files = list(project_path.rglob("*.py"))
        
        for py_file in python_files:
            # Skip __pycache__ and other generated files
            if '__pycache__' in str(py_file) or py_file.name.startswith('.'):
                continue
            
            project_analysis['total_files'] += 1
            
            try:
                file_analysis = self.analyze_file_coverage(py_file)
                project_analysis['analyzed_files'] += 1
                project_analysis['total_functions'] += file_analysis['total_functions']
                project_analysis['functions_with_hints'] += file_analysis['functions_with_hints']
                project_analysis['file_analyses'].append(file_analysis)
                
            except Exception as e:
                self.logger.warning(f"Could not analyze {py_file}: {e}")
        
        # Calculate overall coverage
        if project_analysis['total_functions'] > 0:
            project_analysis['overall_coverage_percentage'] = (
                project_analysis['functions_with_hints'] / project_analysis['total_functions']
            ) * 100
        
        # Identify files needing most improvement
        files_by_coverage = sorted(
            project_analysis['file_analyses'],
            key=lambda x: x['coverage_percentage']
        )
        
        project_analysis['top_files_needing_improvement'] = files_by_coverage[:10]
        
        return project_analysis
    
    def generate_improvement_report(self, analysis: Dict[str, Any]) -> str:
        """
        Generate a human-readable improvement report.
        
        Args:
            analysis: Analysis results from analyze_file_coverage or analyze_project_coverage
            
        Returns:
            Formatted improvement report as string
        """
        if 'file_analyses' in analysis:
            # Project-wide report
            return self._generate_project_report(analysis)
        else:
            # Single file report
            return self._generate_file_report(analysis)
    
    def _generate_file_report(self, analysis: Dict[str, Any]) -> str:
        """Generate report for a single file."""
        report = []
        report.append(f"Type Hints Coverage Report: {analysis['file_path']}")
        report.append("=" * 60)
        report.append(f"Overall Coverage: {analysis['coverage_percentage']:.1f}%")
        report.append(f"Functions: {analysis['functions_with_hints']}/{analysis['total_functions']} with complete hints")
        report.append(f"Parameters: {analysis['parameters_with_hints']}/{analysis['total_parameters']} with hints")
        report.append("")
        
        if analysis['missing_hints']:
            report.append("Functions needing type hints:")
            report.append("-" * 30)
            for missing in analysis['missing_hints']:
                report.append(f"• {missing['function_name']} (line {missing['line_number']})")
                if missing['missing_parameters']:
                    report.append(f"  Missing parameter hints: {', '.join(missing['missing_parameters'])}")
                if missing['missing_return_hint']:
                    report.append(f"  Missing return type hint")
                report.append("")
        
        return "\n".join(report)
    
    def _generate_project_report(self, analysis: Dict[str, Any]) -> str:
        """Generate report for entire project."""
        report = []
        report.append(f"Project Type Hints Coverage Report: {analysis['project_path']}")
        report.append("=" * 70)
        report.append(f"Overall Coverage: {analysis['overall_coverage_percentage']:.1f}%")
        report.append(f"Files Analyzed: {analysis['analyzed_files']}/{analysis['total_files']}")
        report.append(f"Functions: {analysis['functions_with_hints']}/{analysis['total_functions']} with complete hints")
        report.append("")
        
        if analysis['top_files_needing_improvement']:
            report.append("Files needing most improvement:")
            report.append("-" * 40)
            for file_analysis in analysis['top_files_needing_improvement'][:5]:
                file_name = Path(file_analysis['file_path']).name
                coverage = file_analysis['coverage_percentage']
                report.append(f"• {file_name}: {coverage:.1f}% coverage")
        
        return "\n".join(report)
