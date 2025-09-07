"""GitHub API client for fetching pull request data."""

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


class GitHubClient:
    """Client for interacting with GitHub API."""
    
    def __init__(self, config: Config, logger: logging.Logger):
        """Initialize the GitHub client."""
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
        
        # Setup authentication using GitHub token
        session.headers.update({
            'Accept': 'application/vnd.github+json',
            'Authorization': f'Bearer {self.config.github_token}',
            'X-GitHub-Api-Version': '2022-11-28'
        })
        
        return session
    
    def fetch_all_repositories(self) -> List[Dict[str, Any]]:
        """Fetch all repositories for the organization or user."""
        try:
            self.logger.info(f"Fetching repositories from GitHub for {self.config.github_owner}...")
            
            # Determine if this is an organization or user
            if self.config.github_type == 'org':
                url = f"https://api.github.com/orgs/{self.config.github_owner}/repos"
            else:
                url = f"https://api.github.com/users/{self.config.github_owner}/repos"
            
            all_repos = []
            page = 1
            per_page = 100
            
            while True:
                params = {
                    'page': page,
                    'per_page': per_page,
                    'sort': 'updated',
                    'direction': 'desc'
                }
                
                response = self.session.get(url, params=params, timeout=30)
                
                if response.status_code != 200:
                    self.logger.error(f"Failed to fetch repositories: {response.status_code}")
                    self.logger.error(f"Response: {response.text}")
                    break
                
                repos = response.json()
                if not repos:
                    break
                
                all_repos.extend(repos)
                
                # Check if we have more pages
                if len(repos) < per_page:
                    break
                
                page += 1
            
            self.logger.info(f"Found {len(all_repos)} repositories for {self.config.github_owner}")
            for repo in all_repos[:10]:  # Log first 10 repos
                self.logger.info(f"  - {repo.get('name', 'Unknown')} (ID: {repo.get('id', 'Unknown')})")
            
            if len(all_repos) > 10:
                self.logger.info(f"  ... and {len(all_repos) - 10} more repositories")
            
            return all_repos
            
        except Exception as e:
            self.logger.error(f"Error fetching repositories: {e}")
            return []

    def fetch_pull_requests_for_repository(self, repository: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch all pull requests for a specific repository with detailed information."""
        repo_name = repository.get('name', 'Unknown')
        repo_full_name = repository.get('full_name', '')
        
        all_pr_data = []
        page = 1
        per_page = 100
        
        while True:
            # Build URL for GitHub PRs API
            url = f"https://api.github.com/repos/{repo_full_name}/pulls"
            params = {
                'state': 'closed',  # Only fetch closed PRs (equivalent to completed in Azure DevOps)
                'page': page,
                'per_page': per_page,
                'sort': 'updated',
                'direction': 'desc'
            }
            
            try:
                response = self.session.get(url, params=params, timeout=15)
                
                if response.status_code != 200:
                    if response.status_code == 404:
                        # Repo has no PRs or access denied - log as info, not warning
                        pass
                    else:
                        self.logger.warning(f"API request failed for {repo_name}: {response.status_code}")
                    break
                
                # Parse JSON response
                page_results = response.json()
                
                if not page_results:
                    break
                
                # Enhance each PR with repository information
                for pr in page_results:
                    pr['repository_name'] = repo_name
                    pr['repository_full_name'] = repo_full_name
                    pr['repository_id'] = repository.get('id')
                
                all_pr_data.extend(page_results)
                
                if page_results:
                    self.logger.info(f"  Page {page}: {len(page_results)} PRs from {repo_name}")
                
                # Check if we have more pages
                if len(page_results) < per_page:
                    break
                
                page += 1
                
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
            all_pr_data = self._fetch_pr_details_parallel(all_pr_data, repo_full_name, repo_name)
        
        if all_pr_data:
            self.logger.info(f"Repository {repo_name}: {len(all_pr_data)} total PRs fetched")
        
        return all_pr_data
    
    def fetch_all_pull_requests(self) -> List[Dict[str, Any]]:
        """Fetch all pull requests from all repositories using parallel processing."""
        # First, fetch all repositories
        repositories = self.fetch_all_repositories()
        
        if not repositories:
            self.logger.warning("No repositories found")
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
    
    def _fetch_pr_details_parallel(self, pr_data: List[Dict[str, Any]], repo_full_name: str, repo_name: str) -> List[Dict[str, Any]]:
        """Fetch detailed information (reviews and comments) for PRs in parallel."""
        if not pr_data:
            return pr_data
            
        # Use a smaller worker pool for detailed fetching to avoid overwhelming the API
        detail_workers = min(8, len(pr_data))
        
        with ThreadPoolExecutor(max_workers=detail_workers) as executor:
            # Submit tasks for fetching PR details
            future_to_pr = {
                executor.submit(self._fetch_single_pr_details, pr, repo_full_name): pr 
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
                    pr_number = pr.get('number', 'unknown')
                    self.logger.warning(f"Failed to fetch details for PR {pr_number} in {repo_name}: {e}")
                    # Set empty defaults so processing doesn't fail
                    pr['reviews'] = []
                    pr['review_comments'] = []
                    pr['issue_comments'] = []
        
        return pr_data
    
    def _fetch_single_pr_details(self, pr: Dict[str, Any], repo_full_name: str) -> Dict[str, Any]:
        """Fetch detailed information for a single PR."""
        pr_number = pr.get('number')
        details = {}
        
        if pr_number:
            # Fetch reviews, review comments, and issue comments concurrently
            with ThreadPoolExecutor(max_workers=3) as executor:
                reviews_future = executor.submit(self._fetch_pr_reviews, repo_full_name, pr_number)
                review_comments_future = executor.submit(self._fetch_pr_review_comments, repo_full_name, pr_number)
                issue_comments_future = executor.submit(self._fetch_pr_issue_comments, repo_full_name, pr_number)
                
                details['reviews'] = reviews_future.result()
                details['review_comments'] = review_comments_future.result()
                details['issue_comments'] = issue_comments_future.result()
        else:
            details['reviews'] = []
            details['review_comments'] = []
            details['issue_comments'] = []
            
        return details
    
    def _fetch_pr_reviews(self, repo_full_name: str, pr_number: int) -> List[Dict[str, Any]]:
        """Fetch all reviews for a specific PR."""
        try:
            url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/reviews"
            
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                return []
        except Exception:
            return []
    
    def _fetch_pr_review_comments(self, repo_full_name: str, pr_number: int) -> List[Dict[str, Any]]:
        """Fetch all review comments (code comments) for a specific PR."""
        try:
            url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}/comments"
            
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                return []
        except Exception:
            return []
    
    def _fetch_pr_issue_comments(self, repo_full_name: str, pr_number: int) -> List[Dict[str, Any]]:
        """Fetch all issue comments (general comments) for a specific PR."""
        try:
            url = f"https://api.github.com/repos/{repo_full_name}/issues/{pr_number}/comments"
            
            response = self.session.get(url, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                return []
        except Exception:
            return []
