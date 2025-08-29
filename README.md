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
   
   # Filtering Options (default: true)
   EXCLUDE_IAC=true
   EXCLUDE_PERSONAL_APPROVALS=true
   ```

## Usage

### Data Collection
Run the script to collect comprehensive PR data:
```bash
python src/main.py
```

The script will:
- Discover all repositories in the specified Azure DevOps project
- Authenticate with Azure DevOps using your PAT
- Fetch all completed pull requests from every repository
- **Apply intelligent filtering** (exclude IAC PRs and personal approvals by default)
- **Collect detailed review information** (comments, approvals, discussions)
- Process and format the data with repository information
- Export results to an Excel file

### Dashboard Visualization
Launch the interactive Streamlit dashboard:
```bash
streamlit run dashboard.py
```

## Performance Optimization

The tool includes several performance optimizations for faster data extraction:

### **Parallel Processing**
- Repositories are processed concurrently using thread pools
- PR details (comments/threads) are fetched in parallel
- Configurable worker limits to balance speed vs. API rate limits

### **Optional Detail Fetching**
For maximum speed, you can skip detailed comment/thread data:
```bash
FETCH_PR_DETAILS=false         # Skip comment/thread fetching (much faster)
MAX_PARALLEL_WORKERS=32        # Adjust parallel worker count
```

### **Performance Settings**
Configure these options in your `.env` file:
```bash
FETCH_PR_DETAILS=true          # Set to false for 5-10x faster execution
MAX_PARALLEL_WORKERS=16        # Number of parallel API calls (adjust based on rate limits)
```

⚡ **Speed vs. Data Trade-off**: Disabling `FETCH_PR_DETAILS` can reduce extraction time from ~25 minutes to ~3-5 minutes, but you'll lose comment and discussion thread analytics in the dashboard.

## Intelligent Filtering

By default, the tool applies smart filtering to focus on meaningful code reviews:

### **Excluded by Default:**
- **IAC-related PRs**: Infrastructure as Code changes (Terraform, Bicep, YAML, Docker, etc.)
- **Personal Approvals**: Self-approvals where the PR creator approves their own work

### **Customization:**
To include these items, set the following in your `.env` file:
```bash
EXCLUDE_IAC=false              # Include infrastructure changes
EXCLUDE_PERSONAL_APPROVALS=false  # Include self-approvals
```

### **Why Filter?**
- **Focus on Code Quality**: IAC changes often follow different review patterns
- **Meaningful Metrics**: Self-approvals don't represent peer review effectiveness
- **Cleaner Analytics**: Get insights into actual collaborative review processes

## Features

### Repository Analytics
- Total PRs per repository
- Repository activity overview
- Top performing repositories

### Temporal Analysis
- PR creation trends over time
- Monthly/daily activity patterns
- Historical analysis

### Contributor Insights
- Most active contributors
- PR creation patterns
- Individual productivity metrics

### **NEW: Enhanced Review Analytics**
- **Top Approvers**: Who approves the most PRs
- **Most Active Commenters**: Who engages most in discussions
- **Review Patterns**: Comments vs approvals analysis
- **Thread Resolution**: How well teams resolve discussions
- **Approval/Rejection Statistics**: Detailed review outcomes

### Activity Heatmaps
- Day/hour activity patterns
- Visual activity distribution

### Interactive Filtering
- Filter by repository, contributor, date range
- Real-time data exploration

## Output Format

The Excel file contains the following columns:

**Basic Data:**
- ID: Pull Request ID
- Repository: Name of the repository
- Work Item Type: Always "Code Review Request"
- Created Date: When the PR was created
- Title: PR title
- Description: PR description
- Created By: Author of the PR
- Assigned To: List of reviewers
- State: PR status (Active, Completed, Abandoned)

**Enhanced Review Data:**
- Approved By: List of users who approved the PR
- Rejected By: List of users who rejected the PR
- Waiting Reviewers: Reviewers who haven't voted yet
- Total Comments: Number of comments on the PR
- Commenters: List of users who commented
- Active Threads: Number of unresolved discussion threads
- Resolved Threads: Number of resolved discussion threads
- Approval Count: Total number of approvals
- Rejection Count: Total number of rejections

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
