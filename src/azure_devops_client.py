"""Azure DevOps API client for fetching pull request data."""

import base64
import logging
from typing import Dict, List, Any, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import Config


class AzureDevOpsClient:
    """Client for interacting with Azure DevOps API."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        """Initialize the Azure DevOps client."""
        self.config = config
        self.logger = logger
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry strategy and authentication."""
        session = requests.Session()
        
        # Setup retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Setup authentication using PAT
        pat_encoded = base64.b64encode(f":{self.config.token}".encode()).decode()
        session.headers.update({
            'Content-Type': 'application/json',
            'Authorization': f'Basic {pat_encoded}'
        })
        
        return session
    
    def fetch_all_repositories(self) -> List[Dict[str, Any]]:
        """Fetch all repositories in the project."""
        try:
            self.logger.info("Fetching repositories from Azure DevOps...")
            response = self.session.get(self.config.repositories_url, timeout=30)
            
            if response.status_code != 200:
                self.logger.error(f"Failed to fetch repositories: {response.status_code}")
                self.logger.error(f"Response: {response.text}")
                return []
            
            repos_data = response.json()
            repositories = repos_data.get('value', [])
            
            self.logger.info(f"Found {len(repositories)} repositories in project '{self.config.project}'")
            for repo in repositories:
                self.logger.info(f"  - {repo.get('name', 'Unknown')} (ID: {repo.get('id', 'Unknown')})")
            
            return repositories
            
        except Exception as e:
            self.logger.error(f"Error fetching repositories: {e}")
            return []

    def fetch_pull_requests_for_repository(self, repository: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch all pull requests for a specific repository."""
        repo_name = repository.get('name', 'Unknown')
        repo_id = repository.get('id', '')
        
        self.logger.info(f"Fetching pull requests for repository: {repo_name}")
        
        all_pr_data = []
        continuation_token = None
        page_count = 0
        
        while True:
            page_count += 1
            
            # Build URL with continuation token if available
            url = self.config.get_pull_requests_url(repo_id)
            if continuation_token:
                url += f"&continuationToken={continuation_token}"
            
            try:
                response = self.session.get(url, timeout=30)
                
                if response.status_code != 200:
                    self.logger.warning(f"API request failed for {repo_name}: {response.status_code}")
                    if response.status_code == 404:
                        self.logger.info(f"Repository {repo_name} may not have any pull requests or access denied")
                    break
                
                # Parse JSON response
                pr_data = response.json()
                page_results = pr_data.get('value', [])
                
                # Add repository info to each PR
                for pr in page_results:
                    pr['repository_name'] = repo_name
                    pr['repository_id'] = repo_id
                
                all_pr_data.extend(page_results)
                
                if page_results:
                    self.logger.info(f"  Page {page_count}: {len(page_results)} PRs from {repo_name}")
                
                # Check for continuation token
                continuation_token = response.headers.get('x-ms-continuationtoken')
                if not continuation_token:
                    break
                
            except requests.exceptions.Timeout:
                self.logger.error(f"Request timed out for repository: {repo_name}")
                break
            except requests.exceptions.ConnectionError:
                self.logger.error(f"Connection error for repository: {repo_name}")
                break
            except requests.exceptions.JSONDecodeError as e:
                self.logger.error(f"Failed to parse JSON response for {repo_name}: {e}")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error for repository {repo_name}: {e}")
                break
        
        self.logger.info(f"Repository {repo_name}: {len(all_pr_data)} total PRs fetched")
        return all_pr_data
    
    def fetch_all_pull_requests(self) -> List[Dict[str, Any]]:
        """Fetch all pull requests from all repositories in the project."""
        # First, fetch all repositories
        repositories = self.fetch_all_repositories()
        
        if not repositories:
            self.logger.warning("No repositories found in the project")
            return []
        
        # Fetch PRs from all repositories
        all_pr_data = []
        for repo in repositories:
            repo_prs = self.fetch_pull_requests_for_repository(repo)
            all_pr_data.extend(repo_prs)
        
        self.logger.info(f"Total pull requests fetched across all repositories: {len(all_pr_data)}")
        return all_pr_data
