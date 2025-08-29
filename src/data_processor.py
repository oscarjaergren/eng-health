"""Data processing utilities for pull request data."""

import logging
from typing import Dict, List, Any


class DataProcessor:
    """Processes raw pull request data from Azure DevOps API."""
    
    def __init__(self, logger: logging.Logger):
        """Initialize the data processor."""
        self.logger = logger
    
    def process_pull_requests(self, pr_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process raw pull request data into the desired format."""
        filtered_pr_data = []
        
        for pr in pr_data:
            try:
                processed_pr = {
                    'ID': pr.get('pullRequestId'),
                    'Repository': pr.get('repository_name', 'Unknown'),
                    'Work Item Type': "Code Review Request",
                    'Created Date': pr.get('creationDate'),
                    'Title': pr.get('title'),
                    'Description': pr.get('description', ''),
                    'Created By': self._extract_created_by(pr),
                    'Assigned To': self._extract_reviewers(pr),
                    'State': 'Closed'
                }
                filtered_pr_data.append(processed_pr)
                
            except Exception as e:
                self.logger.warning(f"Failed to process PR {pr.get('pullRequestId', 'unknown')}: {e}")
                continue
        
        self.logger.info(f"Successfully processed {len(filtered_pr_data)} pull requests")
        return filtered_pr_data
    
    def _extract_created_by(self, pr: Dict[str, Any]) -> str:
        """Extract the creator's unique name from pull request data."""
        created_by = pr.get('createdBy', {})
        return created_by.get('uniqueName', 'Unknown')
    
    def _extract_reviewers(self, pr: Dict[str, Any]) -> List[str]:
        """Extract and format assigned reviewers."""
        reviewers = pr.get('reviewers', [])
        reviewers_info = []
        
        for reviewer in reviewers:
            display_name = reviewer.get('displayName', 'Unknown')
            unique_name = reviewer.get('uniqueName', 'Unknown')
            reviewers_info.append(f"{display_name} - {unique_name}")
        
        return reviewers_info
