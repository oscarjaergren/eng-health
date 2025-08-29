"""
Azure DevOps PR Extraction Tool

Description: Script to extract Pull Request (PR) data from Azure DevOps and save it into an Excel file.
"""

import logging
import os
import sys
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from config import Config
from azure_devops_client import AzureDevOpsClient
from data_processor import DataProcessor


def setup_logging() -> logging.Logger:
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('pr_extraction.log')
        ]
    )
    return logging.getLogger(__name__)


def cleanup_existing_file(filename: str, logger: logging.Logger) -> None:
    """Remove existing output file if it exists."""
    if os.path.exists(filename):
        os.remove(filename)
        logger.info(f"Existing file '{filename}' has been deleted.")
    else:
        logger.info(f"File '{filename}' does not exist.")


def main() -> None:
    """Main execution function."""
    # Load environment variables
    load_dotenv()
    
    # Setup logging
    logger = setup_logging()
    logger.info("Starting Azure DevOps PR extraction tool")
    
    try:
        # Load configuration
        config = Config()
        
        # Cleanup existing output file
        cleanup_existing_file(config.output_filename, logger)
        
        # Initialize Azure DevOps client
        client = AzureDevOpsClient(config, logger)
        
        # Fetch pull requests
        logger.info("Fetching all repositories and their pull requests from Azure DevOps...")
        all_pr_data = client.fetch_all_pull_requests()
        
        if not all_pr_data:
            logger.warning("No pull request data available to export.")
            return
        
        # Process data
        logger.info(f"Processing {len(all_pr_data)} pull requests...")
        processor = DataProcessor(logger, config)
        filtered_pr_data = processor.process_pull_requests(all_pr_data)
        
        # Export to Excel
        logger.info(f"Exporting data to '{config.output_filename}'...")
        df = pd.DataFrame(filtered_pr_data)
        df.to_excel(config.output_filename, index=False)
        
        logger.info(f"Successfully exported {len(filtered_pr_data)} pull requests.")
        logger.info(f"File '{config.output_filename}' created successfully.")
        
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
