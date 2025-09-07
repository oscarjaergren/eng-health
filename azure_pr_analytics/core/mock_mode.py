"""
Mock Mode Configuration and Data Provider

Enables running the dashboard and data processors in mock mode for testing
without requiring actual Azure DevOps or GitHub API integrations.
"""

import os
import json
from typing import Dict, List, Any, Optional
from pathlib import Path
import pandas as pd
from azure_pr_analytics.utils.mock_data_generator import MockDataGenerator


class MockModeConfig:
    """Configuration for mock mode operation."""
    
    def __init__(self):
        self.enabled = self._is_mock_mode_enabled()
        self.data_file = os.getenv('MOCK_DATA_FILE', 'mock_pr_data.json')
        self.excel_file = os.getenv('MOCK_EXCEL_FILE', 'mock_pr_data.xlsx')
        self.generate_on_startup = os.getenv('MOCK_GENERATE_ON_STARTUP', 'true').lower() == 'true'
        self.pr_count = int(os.getenv('MOCK_PR_COUNT', '50'))
        self.seed = int(os.getenv('MOCK_SEED', '42'))
    
    def _is_mock_mode_enabled(self) -> bool:
        """Check if mock mode is enabled via environment variable."""
        return os.getenv('MOCK_MODE', 'false').lower() in ('true', '1', 'yes', 'on')


class MockDataProvider:
    """Provides mock data for testing the dashboard and processors."""
    
    def __init__(self, config: Optional[MockModeConfig] = None):
        self.config = config or MockModeConfig()
        self.generator = MockDataGenerator(seed=self.config.seed)
        self._cached_data = None
    
    def get_mock_excel_data(self) -> pd.DataFrame:
        """
        Get mock data in Excel format compatible with the dashboard.
        
        Returns:
            DataFrame with processed PR data ready for dashboard consumption
        """
        if self._cached_data is not None:
            return self._cached_data
        
        # Check if mock Excel file exists
        excel_path = Path(self.config.excel_file)
        if excel_path.exists() and not self.config.generate_on_startup:
            try:
                df = pd.read_excel(excel_path)
                self._cached_data = df
                return df
            except Exception as e:
                print(f"⚠️ Failed to load existing mock Excel file: {e}")
        
        # Generate new mock data
        print("🔄 Generating mock PR data for dashboard...")
        mock_data = self.generator.generate_excel_compatible_data(count=self.config.pr_count)
        
        # Convert to DataFrame
        df = pd.DataFrame(mock_data)
        
        # Save to Excel file for future use
        try:
            df.to_excel(excel_path, index=False)
            print(f"💾 Mock data saved to {excel_path}")
        except Exception as e:
            print(f"⚠️ Failed to save mock Excel file: {e}")
        
        self._cached_data = df
        return df
    
    def get_mock_raw_data(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get mock raw PR data for testing processors.
        
        Returns:
            Dictionary with 'azure_devops' and 'github' keys containing raw PR data
        """
        # Check if mock data file exists
        data_path = Path(self.config.data_file)
        if data_path.exists() and not self.config.generate_on_startup:
            try:
                with open(data_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Failed to load existing mock data file: {e}")
        
        # Generate new mock data
        print("🔄 Generating mock raw PR data...")
        mock_data = self.generator.generate_mixed_data(
            azure_count=self.config.pr_count // 2,
            github_count=self.config.pr_count // 2
        )
        
        # Save to file for future use
        try:
            with open(data_path, 'w', encoding='utf-8') as f:
                json.dump(mock_data, f, indent=2, ensure_ascii=False)
            print(f"💾 Mock raw data saved to {data_path}")
        except Exception as e:
            print(f"⚠️ Failed to save mock data file: {e}")
        
        return mock_data
    
    def get_mock_config(self) -> 'MockConfig':
        """Get a mock configuration object for testing."""
        class MockConfig:
            def __init__(self):
                self.exclude_iac = True
                self.exclude_personal_approvals = True
                self.system_accounts = ['system', 'bot', 'automation']
                self.iac_keywords = [
                    'terraform', 'docker', 'kubernetes', 'ansible', 'ci/cd', 'pipeline',
                    'deployment', 'infrastructure', 'config', 'environment'
                ]
                self.azure_devops_organization = 'mock-org'
                self.azure_devops_project = 'mock-project'
                self.github_owner = 'mock-owner'
                self.github_type = 'organization'
                self.output_filename = 'mock_output.xlsx'
                self.max_parallel_workers = 4
        
        return MockConfig()
    
    def clear_cache(self):
        """Clear cached data to force regeneration."""
        self._cached_data = None
        print("🗑️ Mock data cache cleared")


def setup_mock_environment():
    """
    Set up environment variables for mock mode.
    This can be called to enable mock mode programmatically.
    """
    os.environ['MOCK_MODE'] = 'true'
    os.environ['MOCK_GENERATE_ON_STARTUP'] = 'true'
    os.environ['MOCK_PR_COUNT'] = '50'
    os.environ['MOCK_SEED'] = '42'
    print("🎭 Mock mode environment configured")


def is_mock_mode() -> bool:
    """Check if the application is running in mock mode."""
    return MockModeConfig().enabled


def get_mock_provider() -> MockDataProvider:
    """Get a configured mock data provider."""
    return MockDataProvider()


def create_mock_data_files():
    """
    Create mock data files for testing.
    Useful for setting up test environment.
    """
    provider = MockDataProvider()
    
    # Generate and save Excel data
    excel_df = provider.get_mock_excel_data()
    print(f"📊 Generated Excel data with {len(excel_df)} PRs")
    
    # Generate and save raw data
    raw_data = provider.get_mock_raw_data()
    total_raw = sum(len(data) for data in raw_data.values())
    print(f"📊 Generated raw data with {total_raw} PRs")
    
    return excel_df, raw_data


def main():
    """CLI interface for mock mode utilities."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Mock mode utilities for PR analytics')
    parser.add_argument('--setup', action='store_true', help='Set up mock mode environment')
    parser.add_argument('--generate', action='store_true', help='Generate mock data files')
    parser.add_argument('--clear-cache', action='store_true', help='Clear mock data cache')
    parser.add_argument('--count', type=int, default=50, help='Number of PRs to generate')
    parser.add_argument('--seed', type=int, default=42, help='Random seed for reproducible data')
    
    args = parser.parse_args()
    
    if args.setup:
        setup_mock_environment()
        os.environ['MOCK_PR_COUNT'] = str(args.count)
        os.environ['MOCK_SEED'] = str(args.seed)
        print("✅ Mock mode environment set up")
    
    if args.generate:
        # Override config with CLI args
        os.environ['MOCK_PR_COUNT'] = str(args.count)
        os.environ['MOCK_SEED'] = str(args.seed)
        os.environ['MOCK_GENERATE_ON_STARTUP'] = 'true'
        
        excel_df, raw_data = create_mock_data_files()
        print("✅ Mock data files generated")
    
    if args.clear_cache:
        provider = get_mock_provider()
        provider.clear_cache()
        print("✅ Mock data cache cleared")
    
    if not any([args.setup, args.generate, args.clear_cache]):
        # Show current mock mode status
        config = MockModeConfig()
        print(f"🎭 Mock Mode Status:")
        print(f"   Enabled: {config.enabled}")
        print(f"   Data file: {config.data_file}")
        print(f"   Excel file: {config.excel_file}")
        print(f"   Generate on startup: {config.generate_on_startup}")
        print(f"   PR count: {config.pr_count}")
        print(f"   Seed: {config.seed}")


if __name__ == '__main__':
    main()
