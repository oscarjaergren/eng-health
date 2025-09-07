"""Azure DevOps API client for fetching pull request data."""

import base64
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
        
        # Performance settings
        self.max_workers = min(config.max_parallel_workers, (os.cpu_count() or 1) + 4)
    
    def _create_session(self) -> requests.Session:
        """Create a requests session with retry strategy and authentication."""
        session = requests.Session()
        
        # Setup retry strategy with more aggressive retries for performance
        retry_strategy = Retry(
            total=2,  # Reduced retries for faster failure
            backoff_factor=0.5,  # Faster backoff
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=100, pool_maxsize=100)
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
        """Fetch all pull requests for a specific repository with detailed information."""
        repo_name = repository.get('name', 'Unknown')
        repo_id = repository.get('id', '')
        
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
                response = self.session.get(url, timeout=15)  # Reduced timeout
                
                if response.status_code != 200:
                    if response.status_code == 404:
                        # Repo has no PRs or access denied - log as info, not warning
                        pass
                    else:
                        self.logger.warning(f"API request failed for {repo_name}: {response.status_code}")
                    break
                
                # Parse JSON response
                pr_data = response.json()
                page_results = pr_data.get('value', [])
                
                # Enhance each PR with repository information
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
        
        # Always fetch detailed information in parallel
        if all_pr_data:
            all_pr_data = self._fetch_pr_details_parallel(all_pr_data, repo_id, repo_name)
        
        if all_pr_data:
            self.logger.info(f"Repository {repo_name}: {len(all_pr_data)} total PRs fetched")
        
        return all_pr_data
    
    def fetch_all_pull_requests(self) -> List[Dict[str, Any]]:
        """Fetch all pull requests from all repositories in the project using parallel processing."""
        # First, fetch all repositories
        repositories = self.fetch_all_repositories()
        
        if not repositories:
            self.logger.warning("No repositories found in the project")
            return []
        
        # Fetch PRs from repositories in parallel
        all_pr_data = []
        completed_repos = 0
        total_repos = len(repositories)
        
        self.logger.info(f"Fetching PRs from {total_repos} repositories using {min(self.max_workers, total_repos)} parallel workers...")
        start_time = time.time()
        
        # Use thread pool for parallel API calls
        with ThreadPoolExecutor(max_workers=min(self.max_workers, total_repos)) as executor:
            # Submit all repository PR fetch tasks
            future_to_repo = {
                executor.submit(self.fetch_pull_requests_for_repository, repo): repo 
                for repo in repositories
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_repo):
                repo = future_to_repo[future]
                repo_name = repo.get('name', 'Unknown')
                completed_repos += 1
                
                try:
                    repo_prs = future.result()
                    all_pr_data.extend(repo_prs)
                    
                    # Progress reporting
                    elapsed = time.time() - start_time
                    progress = (completed_repos / total_repos) * 100
                    self.logger.info(f"Progress: {completed_repos}/{total_repos} repositories ({progress:.1f}%) - "
                                   f"Elapsed: {elapsed:.1f}s - Current: {repo_name}")
                    
                except Exception as e:
                    self.logger.error(f"Failed to fetch PRs for repository {repo_name}: {e}")
        
        elapsed_total = time.time() - start_time
        self.logger.info(f"Total pull requests fetched across all repositories: {len(all_pr_data)} "
                        f"(completed in {elapsed_total:.1f}s)")
        return all_pr_data
    
    def _fetch_pr_details_parallel(self, pr_data: List[Dict[str, Any]], repo_id: str, repo_name: str) -> List[Dict[str, Any]]:
        """Fetch detailed information (threads and iterations) for PRs in parallel."""
        if not pr_data:
            return pr_data
            
        # Use a smaller worker pool for detailed fetching to avoid overwhelming the API
        detail_workers = min(8, len(pr_data))
        
        with ThreadPoolExecutor(max_workers=detail_workers) as executor:
            # Submit tasks for fetching PR details
            future_to_pr = {
                executor.submit(self._fetch_single_pr_details, pr, repo_id): pr 
                for pr in pr_data
            }
            
            # Collect results
            for future in as_completed(future_to_pr):
                pr = future_to_pr[future]
                try:
                    updated_pr = future.result()
                    # Update the original PR data with fetched details
                    pr.update(updated_pr)
                except Exception as e:
                    pr_id = pr.get('pullRequestId', 'unknown')
                    self.logger.warning(f"Failed to fetch details for PR {pr_id} in {repo_name}: {e}")
                    # Set empty defaults so processing doesn't fail
                    pr['threads'] = []
                    pr['iterations'] = []
        
        return pr_data
    
    def _fetch_single_pr_details(self, pr: Dict[str, Any], repo_id: str) -> Dict[str, Any]:
        """Fetch detailed information for a single PR."""
        pr_id = pr.get('pullRequestId')
        details = {}
        
        if pr_id:
            # Fetch threads and iterations concurrently
            with ThreadPoolExecutor(max_workers=2) as executor:
                threads_future = executor.submit(self._fetch_pr_threads, repo_id, pr_id)
                iterations_future = executor.submit(self._fetch_pr_iterations, repo_id, pr_id)
                
                details['threads'] = threads_future.result()
                details['iterations'] = iterations_future.result()
        else:
            details['threads'] = []
            details['iterations'] = []
            
        return details
    
    def _fetch_pr_threads(self, repo_id: str, pr_id: int) -> List[Dict[str, Any]]:
        """Fetch all threads (comments and discussions) for a specific PR."""
        try:
            # Construct URL for PR threads - base_url already includes project
            threads_url = f"{self.config.base_url}/git/repositories/{repo_id}/pullRequests/{pr_id}/threads?api-version=7.1"
            
            response = self.session.get(threads_url, timeout=10)  # Reduced timeout
            if response.status_code == 200:
                threads_data = response.json()
                return threads_data.get('value', [])
            else:
                return []
        except Exception:
            return []
    
    def _fetch_pr_iterations(self, repo_id: str, pr_id: int) -> List[Dict[str, Any]]:
        """Fetch all iterations for a specific PR."""
        try:
            # Construct URL for PR iterations - base_url already includes project
            iterations_url = f"{self.config.base_url}/git/repositories/{repo_id}/pullRequests/{pr_id}/iterations?api-version=7.1"
            
            response = self.session.get(iterations_url, timeout=10)  # Reduced timeout
            if response.status_code == 200:
                iterations_data = response.json()
                return iterations_data.get('value', [])
            else:
                return []
        except Exception:
            return []
