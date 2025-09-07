"""
Multi-Platform PR Extraction Tool

Description: Script to extract Pull Request (PR) data from Azure DevOps and/or GitHub and save it into an Excel file.
"""

import logging
import os
import sys

import pandas as pd
from azure_devops_client import AzureDevOpsClient
from config import Config
from dotenv import load_dotenv
from github_client import GitHubClient
from input_validator import InputValidator
from unified_data_processor import UnifiedDataProcessor


def setup_logging() -> logging.Logger:
    """Configure logging for the application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("pr_extraction.log"),
        ],
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
    logger.info("Starting multi-platform PR extraction tool")

    try:
        # Load configuration
        config = Config()
        logger.info(f"Configured platforms: {', '.join(config.platforms)}")

        # Cleanup existing output file
        cleanup_existing_file(config.output_filename, logger)

        # Initialize input validator and unified data processor
        validator = InputValidator(logger)
        processor = UnifiedDataProcessor(logger, config)
        all_filtered_data = []

        # Validate configuration
        validated_config = validator.validate_config_data(
            {
                "organization": getattr(config, "organization", ""),
                "project": getattr(config, "project", ""),
                "github_owner": getattr(config, "github_owner", ""),
                "token": getattr(config, "token", ""),
                "github_token": getattr(config, "github_token", ""),
            }
        )

        if not any(validated_config.values()):
            logger.error("Configuration validation failed - no valid credentials found")
            return

        # Process Azure DevOps if configured
        if "azure_devops" in config.platforms:
            logger.info("Fetching data from Azure DevOps...")
            azure_client = AzureDevOpsClient(config, logger)
            azure_pr_data = azure_client.fetch_all_pull_requests()

            if azure_pr_data:
                logger.info(
                    f"Processing {
                        len(azure_pr_data)} Azure DevOps pull requests..."
                )
                azure_filtered_data = processor.process_pull_requests(
                    azure_pr_data, "azure_devops"
                )
                all_filtered_data.extend(azure_filtered_data)
            else:
                logger.warning("No Azure DevOps pull request data available.")

        # Process GitHub if configured
        if "github" in config.platforms:
            logger.info("Fetching data from GitHub...")
            github_client = GitHubClient(config, logger)
            github_pr_data = github_client.fetch_all_pull_requests()

            if github_pr_data:
                logger.info(
                    f"Processing {
                        len(github_pr_data)} GitHub pull requests..."
                )
                github_filtered_data = processor.process_pull_requests(
                    github_pr_data, "github"
                )
                all_filtered_data.extend(github_filtered_data)
            else:
                logger.warning("No GitHub pull request data available.")

        if not all_filtered_data:
            logger.warning(
                "No pull request data available to export from any platform."
            )
            return

        # Validate output file path
        if not validator.validate_file_path(config.output_filename):
            logger.error(f"Invalid output file path: {config.output_filename}")
            return

        # Export to Excel
        logger.info(
            f"Exporting {
                len(all_filtered_data)} total pull requests to '{
                config.output_filename}'..."
        )
        df = pd.DataFrame(all_filtered_data)

        # Sort by platform and creation date for better organization
        df["Created Date"] = pd.to_datetime(df["Created Date"])
        df = df.sort_values(["Platform", "Created Date"], ascending=[True, False])

        df.to_excel(config.output_filename, index=False)

        # Log summary by platform
        platform_counts = df["Platform"].value_counts()
        for platform, count in platform_counts.items():
            logger.info(f"  {platform}: {count} pull requests")

        logger.info(
            f"Successfully exported {
                len(all_filtered_data)} pull requests from {
                len(
                    config.platforms)} platform(s)."
        )
        logger.info(f"File '{config.output_filename}' created successfully.")

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
