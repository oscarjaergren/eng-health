"""
Multi-Platform PR Extraction Tool

Description: Script to extract Pull Request (PR) data from Azure DevOps and/or GitHub and save it into an Excel file.
"""

import logging
import os
import sys


import pandas as pd
from azure_pr_analytics.clients.azure_devops_client import AzureDevOpsClient
from azure_pr_analytics.core.config import Config
from dotenv import load_dotenv
from azure_pr_analytics.clients.github_client import GitHubClient
from azure_pr_analytics.core.input_validator import InputValidator
from azure_pr_analytics.processors.unified_data_processor import UnifiedDataProcessor


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
                logger.info(f"Processing {len(azure_pr_data)} Azure DevOps pull requests...")
                azure_filtered_data = processor.process_pull_requests(
                    azure_pr_data, "azure_devops"
                )
                all_filtered_data.extend(azure_filtered_data)
            else:
                logger.warning("No Azure DevOps pull request data available.")

        # Process GitHub if configured and credentials are valid
        github_owner = validated_config.get("github_owner", "")
        github_token = validated_config.get("github_token", "")
        if (
            "github" in config.platforms
            and github_owner
            and github_token
        ):
            logger.info("Fetching data from GitHub...")
            github_client = GitHubClient(config, logger)
            github_pr_data = github_client.fetch_all_pull_requests()

            if github_pr_data:
                logger.info(f"Processing {len(github_pr_data)} GitHub pull requests...")
                github_filtered_data = processor.process_pull_requests(
                    github_pr_data, "github"
                )
                all_filtered_data.extend(github_filtered_data)
            else:
                logger.warning("No GitHub pull request data available.")
        elif "github" in config.platforms:
            logger.info("GitHub extraction skipped: missing or invalid github_owner or github_token.")

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
            f"Exporting {len(all_filtered_data)} total pull requests to '{config.output_filename}'..."
        )
        df = pd.DataFrame(all_filtered_data)

        # Sort by platform and creation date for better organization
        if "Created Date" in df.columns:
            df["Created Date"] = pd.to_datetime(df["Created Date"], errors="coerce")
            # Remove timezone info if present
            if df["Created Date"].dt.tz is not None:
                df["Created Date"] = df["Created Date"].dt.tz_localize(None)
        df = df.sort_values([col for col in ["Platform", "Created Date"] if col in df.columns], ascending=[True, False])

        # Remove timezone info from all datetime columns before export
        for col in df.columns:
            if df[col].dtype.name.startswith('datetime64[ns,') or 'datetime' in str(df[col].dtype):
                try:
                    # Convert to datetime and remove timezone if present
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                    if hasattr(df[col].dtype, 'tz') and df[col].dtype.tz is not None:
                        df[col] = df[col].dt.tz_localize(None)
                except Exception as e:
                    logger.warning(f"Could not process datetime column {col}: {e}")

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
