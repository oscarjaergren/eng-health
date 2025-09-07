"""Safe data parsing utilities to replace unsafe eval() usage."""

import ast
import json
import logging
from typing import Any, List, Dict, Union


def safe_parse_list(data: Union[str, List, None]) -> List:
    """
    Safely parse string representation of list or return existing list.
    
    Args:
        data: String representation of list, actual list, or None
        
    Returns:
        List: Parsed list or empty list if parsing fails
    """
    if not data:
        return []
    
    if isinstance(data, list):
        return data
    
    if not isinstance(data, str):
        return []
    
    # Handle empty list string representations
    if data.strip() in ['[]', '', 'None']:
        return []
    
    try:
        # Try ast.literal_eval first (safest)
        result = ast.literal_eval(data)
        return result if isinstance(result, list) else []
    except (ValueError, SyntaxError):
        try:
            # Fallback to JSON parsing
            result = json.loads(data)
            return result if isinstance(result, list) else []
        except json.JSONDecodeError:
            # Last resort: split by comma if it looks like a simple list
            if ',' in data and not any(char in data for char in ['{', '}', '(', ')']):
                return [item.strip().strip('"\'') for item in data.split(',') if item.strip()]
            return []


def safe_parse_dict(data: Union[str, Dict, None]) -> Dict:
    """
    Safely parse string representation of dictionary or return existing dict.
    
    Args:
        data: String representation of dict, actual dict, or None
        
    Returns:
        Dict: Parsed dictionary or empty dict if parsing fails
    """
    if not data:
        return {}
    
    if isinstance(data, dict):
        return data
    
    if not isinstance(data, str):
        return {}
    
    # Handle empty dict string representations
    if data.strip() in ['{}', '', 'None']:
        return {}
    
    try:
        # Try ast.literal_eval first (safest)
        result = ast.literal_eval(data)
        return result if isinstance(result, dict) else {}
    except (ValueError, SyntaxError):
        try:
            # Fallback to JSON parsing
            result = json.loads(data)
            return result if isinstance(result, dict) else {}
        except json.JSONDecodeError:
            return {}


def safe_count_items(data: Union[str, List, None]) -> int:
    """
    Safely count items in a list representation.
    
    Args:
        data: String representation of list, actual list, or None
        
    Returns:
        int: Count of items in the list
    """
    parsed_list = safe_parse_list(data)
    return len(parsed_list)


def safe_parse_with_fallback(data: Any, fallback_value: Any = None) -> Any:
    """
    Safely parse data with a fallback value if parsing fails.
    
    Args:
        data: Data to parse
        fallback_value: Value to return if parsing fails
        
    Returns:
        Any: Parsed data or fallback value
    """
    if not data or data in ['', 'None', 'null']:
        return fallback_value
    
    if isinstance(data, str):
        try:
            return ast.literal_eval(data)
        except (ValueError, SyntaxError):
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                return fallback_value
    
    return data
