# Multi-Platform PR Analytics Tool

A comprehensive Python application to extract Pull Request (PR) data from Azure DevOps and/or GitHub with an interactive analytics dashboard.

## 🚀 Features

### Multi-Platform Support
- **Azure DevOps**: Extract from ALL projects in an Azure DevOps organization
- **GitHub**: Extract from all repositories in a GitHub organization or user account
- **Unified Analytics**: Combine data from both platforms in a single dashboard
- **Flexible Configuration**: Use one or both platforms as needed

### Core Capabilities
- Interactive Streamlit dashboard with advanced visualizations
- Handles pagination for large datasets automatically
- Exports data to Excel format with repository and platform information
- Secure token handling with environment variables
- Comprehensive error handling and logging
- Parallel processing for optimal performance
- Smart filtering (excludes IAC PRs and personal approvals)

## 📋 Prerequisites

### For Docker Installation (Recommended)
- Docker and Docker Compose installed
- **For Azure DevOps**: Personal Access Token (PAT) with appropriate permissions
- **For GitHub**: Personal Access Token with repo access permissions
- Access to your Azure DevOps organization/project and/or GitHub organization/account

### For Local Python Installation
- Python 3.8 or higher
- **For Azure DevOps**: Personal Access Token (PAT) with appropriate permissions
- **For GitHub**: Personal Access Token with repo access permissions
- Access to your Azure DevOps organization/project and/or GitHub organization/account

## 🛠️ Installation

### Option 1: Docker (Recommended for Self-Hosting)

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd azure-devops-pr-analytics
   ```

2. Copy `.env.example` to `.env` and configure your credentials (see Configuration section)

3. Build and start the dashboard:
   ```bash
   docker-compose up -d dashboard
   ```

4. Access the dashboard at `http://localhost:8501`

5. To collect data, run the CLI:
   ```bash
   docker-compose run --rm cli
   ```
### Option 2: Local Python Installation

1. Clone this repository:
   ```bash
   git clone <repository-url>
   cd azure-devops-pr-analytics
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

## ⚙️ Configuration

1. Copy `.env.example` to `.env` and configure your platform(s):

   **For Azure DevOps:**
   ```
   AZURE_DEVOPS_ORGANIZATION=your-organization-name
   AZURE_DEVOPS_PAT=your-personal-access-token
   ```

   **For GitHub:**
   ```
   GITHUB_TOKEN=your-github-personal-access-token
   GITHUB_OWNER=your-github-organization-or-username
   GITHUB_TYPE=org  # 'org' for organization, 'user' for personal account
   ```

   **Common Settings:**
   ```
   OUTPUT_FILENAME=pr_data.xlsx
   MAX_PARALLEL_WORKERS=16
   ```

   **Note**: You can configure both platforms to extract from both sources, or just one platform.

## 🎯 Usage

### Quick Start
Use our convenient launcher scripts:

**Windows:**
```bash
scripts\start_dashboard.bat
```

**Linux/macOS:**
```bash
scripts/start_dashboard.sh
```

These scripts will:
- Set up virtual environment if needed
- Install dependencies
- Check for configuration
- Extract data if needed
- Launch the dashboard

### Manual Usage

#### Data Collection
Run the script to collect comprehensive PR data:
```bash
python main.py
```

The script will:
- **Auto-detect configured platforms** (Azure DevOps and/or GitHub)
- Discover all repositories across ALL projects in the Azure DevOps organization
- Authenticate using your Personal Access Token(s)
- Fetch all completed pull requests from every repository
- **Automatically filter** IAC PRs, personal approvals, and system accounts
- **Collect detailed review information** (comments, approvals, discussions)
- **Unify data format** across platforms for consistent analytics
- Process and format the data with repository and platform information
- Export results to a single Excel file with combined data

#### Dashboard Visualization
Launch the interactive Streamlit dashboard:
```bash
streamlit run dashboard_main.py
```

#### VS Code Integration
Use the provided launch configurations:
- **🚀 Start Dashboard**: Launch Streamlit dashboard with debugging
- **📊 Extract PR Data**: Run data extraction with debugging

## 🐳 Docker Deployment

### Architecture

The Docker setup provides two services from a single image:

1. **Dashboard Service**: Runs the Streamlit web interface (always on)
2. **CLI Service**: Runs data collection manually or on schedule

### Basic Commands

**Start the dashboard:**
```bash
docker-compose up -d dashboard
```

**Collect data:**
```bash
docker-compose run --rm cli
```

**View logs:**
```bash
docker-compose logs -f dashboard
```

**Stop services:**
```bash
docker-compose down
```

**Rebuild after code changes:**
```bash
docker-compose build
docker-compose up -d dashboard
```

### Data Persistence

Data is stored in Docker volumes mounted to your local directories:
- `./data/` - Excel files with PR data
- `./cache/` - API response cache for faster subsequent runs

### Scheduled Data Collection

To automate data collection, you can use:

**Linux/macOS (cron):**
```bash
# Add to crontab (crontab -e)
# Run every day at 2 AM
0 2 * * * cd /path/to/azure-devops-pr-analytics && docker-compose run --rm cli
```

**Windows (Task Scheduler):**
Create a scheduled task that runs:
```powershell
cd C:\path\to\azure-devops-pr-analytics
docker-compose run --rm cli
```

### Environment Variables

Required in your `.env` file:
- Azure DevOps: `AZURE_DEVOPS_ORGANIZATION`, `AZURE_DEVOPS_PAT`
- GitHub: `GITHUB_TOKEN`, `GITHUB_OWNER`, `GITHUB_TYPE`
- Common: `OUTPUT_FILENAME`, `MAX_PARALLEL_WORKERS`

### Health Checks

The dashboard includes health checks. View status:
```bash
docker-compose ps
```

### Troubleshooting

**Port already in use:**
```bash
# Change port in docker-compose.yml
ports:
  - "8502:8501"  # Use 8502 instead
```

**Permission issues (Linux/macOS):**
```bash
sudo chown -R $USER:$USER data/ cache/
```

**View detailed logs:**
```bash
docker-compose logs --tail=100 dashboard
```

## Performance Optimization

The tool includes several performance optimizations for faster data extraction:

### **Parallel Processing**
- Repositories are processed concurrently using thread pools
- PR details (comments/threads) are fetched in parallel
- Configurable worker limits to balance speed vs. API rate limits

### **Performance Settings**
You can adjust parallel worker count for optimal performance:
```bash
MAX_PARALLEL_WORKERS=32        # Adjust parallel worker count
```

Configure this option in your `.env` file:
```bash
MAX_PARALLEL_WORKERS=16        # Number of parallel API calls (adjust based on rate limits)
```

⚡ **Comprehensive Analytics**: The tool always fetches detailed PR information including comments and discussion threads to provide complete analytics. Processing time is typically 15-25 minutes depending on repository size and API rate limits.

## Intelligent Filtering

The tool applies smart filtering to focus on meaningful code reviews:

### **Always Excluded:**
- **IAC-related PRs**: Infrastructure as Code changes (Terraform, Bicep, YAML, Docker, etc.)
- **Personal Approvals**: Self-approvals where the PR creator approves their own work
- **System Accounts**: All service/system identities (vstfs-based accounts)

### **Why Filter?**
- **Focus on Code Quality**: IAC changes often follow different review patterns
- **Meaningful Metrics**: Self-approvals don't represent peer review effectiveness
- **Cleaner Analytics**: Get insights into actual collaborative review processes
- **Human-Centered Data**: System accounts don't provide meaningful review insights

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
