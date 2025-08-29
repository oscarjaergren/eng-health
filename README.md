# Azure DevOps PR Extraction Tool

A Python script to extract Pull Request (PR) data from Azure DevOps and save it into an Excel file.

## Features

- Extracts completed pull requests from **all repositories** in an Azure DevOps project
- Handles pagination for large datasets
- Exports data to Excel format with repository information
- Secure token handling with environment variables
- Comprehensive error handling and logging
- Processes multiple repositories automatically

## Prerequisites

- Python 3.8 or higher
- Azure DevOps Personal Access Token (PAT) with appropriate permissions
- Access to Azure DevOps organization and project

## Installation

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd azure-devops-pr-extractor
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Edit the `.env` file with your Azure DevOps details:
   ```
   AZURE_DEVOPS_ORGANIZATION=your-organization-name
   AZURE_DEVOPS_PROJECT=your-project-name
   AZURE_DEVOPS_PAT=your-personal-access-token
   OUTPUT_FILENAME=pr_data.xlsx
   ```

## Usage

Run the script:
```bash
python src/main.py
```

The script will:
- Discover all repositories in the specified Azure DevOps project
- Authenticate with Azure DevOps using your PAT
- Fetch all completed pull requests from every repository
- Process and format the data with repository information
- Export results to an Excel file

## Output Format

The Excel file contains the following columns:
- ID: Pull Request ID
- Repository: Name of the repository
- Work Item Type: Always "Code Review Request"
- Created Date: When the PR was created
- Title: PR title
- Description: PR description
- Created By: Author of the PR
- Assigned To: List of reviewers
- State: Always "Closed" for completed PRs

## Security Notes

- Never commit your Personal Access Token to version control
- Use environment variables or secure secret management
- Review the required permissions for your PAT
- Consider using Azure Key Vault for production deployments

## Error Handling

The script includes comprehensive error handling for:
- Network connectivity issues
- Authentication failures
- API rate limiting
- Data processing errors

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Author

Original script by Aman Rastogi
Enhanced with security and best practices
