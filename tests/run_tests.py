"""Test runner for the Azure DevOps PR Analytics project."""

import sys
import unittest
from pathlib import Path
import logging

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

# Configure logging for tests
logging.basicConfig(level=logging.WARNING)


def discover_and_run_tests():
    """
    Discover and run all tests in the tests directory.
    
    Returns:
        bool: True if all tests passed, False otherwise
    """
    # Discover tests
    test_loader = unittest.TestLoader()
    test_suite = test_loader.discover('tests', pattern='test_*.py')
    
    # Run tests with detailed output
    runner = unittest.TextTestRunner(
        verbosity=2,
        stream=sys.stdout,
        descriptions=True,
        failfast=False
    )
    
    print("=" * 70)
    print("Azure DevOps PR Analytics - Test Suite")
    print("=" * 70)
    
    result = runner.run(test_suite)
    
    # Print summary
    print("\n" + "=" * 70)
    print("Test Summary:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")
    
    if result.failures:
        print("\nFailures:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nErrors:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")
    
    success_rate = ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100) if result.testsRun > 0 else 0
    print(f"\nSuccess Rate: {success_rate:.1f}%")
    print("=" * 70)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = discover_and_run_tests()
    sys.exit(0 if success else 1)
