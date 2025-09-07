"""
Mock Data Generator for PR Analytics Testing

This utility generates realistic mock PR data for testing the dashboard and data processing
without requiring actual Azure DevOps or GitHub API integrations.
"""

import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


class MockDataGenerator:
    """Generates realistic mock PR data for testing purposes."""

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize the mock data generator.

        Args:
            seed: Random seed for reproducible data generation
        """
        if seed:
            random.seed(seed)

        # Sample data for realistic generation
        self.repositories = [
            "UserService",
            "PaymentAPI",
            "WebApp",
            "MobileApp",
            "DataPipeline",
            "AuthService",
            "NotificationService",
            "ReportingEngine",
            "AdminPortal",
            "CustomerPortal",
            "AnalyticsService",
            "FileStorage",
            "MessageQueue",
        ]

        self.developers = [
            {"name": "Alice Johnson", "email": "alice.johnson@company.com"},
            {"name": "Bob Smith", "email": "bob.smith@company.com"},
            {"name": "Charlie Brown", "email": "charlie.brown@company.com"},
            {"name": "Diana Prince", "email": "diana.prince@company.com"},
            {"name": "Eve Wilson", "email": "eve.wilson@company.com"},
            {"name": "Frank Miller", "email": "frank.miller@company.com"},
            {"name": "Grace Lee", "email": "grace.lee@company.com"},
            {"name": "Henry Davis", "email": "henry.davis@company.com"},
            {"name": "Ivy Chen", "email": "ivy.chen@company.com"},
            {"name": "Jack Taylor", "email": "jack.taylor@company.com"},
        ]

        self.pr_titles = [
            "Add user authentication feature",
            "Fix memory leak in data processing",
            "Implement caching layer for better performance",
            "Update API documentation",
            "Refactor database connection handling",
            "Add unit tests for payment module",
            "Fix bug in user registration flow",
            "Implement rate limiting for API endpoints",
            "Update dependencies to latest versions",
            "Add logging and monitoring improvements",
            "Fix cross-site scripting vulnerability",
            "Implement search functionality",
            "Optimize database queries",
            "Add support for multiple languages",
            "Fix responsive design issues",
            "Implement data validation",
            "Add error handling improvements",
            "Update UI components",
            "Fix integration test failures",
            "Implement backup and recovery system",
        ]

        self.iac_titles = [
            "Update terraform configuration for new environment",
            "Add Docker configuration for microservices",
            "Update Kubernetes deployment manifests",
            "Configure CI/CD pipeline for automated deployment",
            "Add infrastructure monitoring with Prometheus",
            "Update Ansible playbooks for server configuration",
            "Configure load balancer settings",
            "Add database migration scripts",
            "Update environment variables configuration",
            "Configure SSL certificates for production",
        ]

        self.pr_descriptions = [
            "This PR implements the requested feature with proper error handling and tests.",
            "Fixing a critical bug that was causing issues in production.",
            "Performance improvement that reduces response time by 40%.",
            "Adding comprehensive documentation for the new API endpoints.",
            "Refactoring legacy code to improve maintainability.",
            "Adding missing test coverage for critical business logic.",
            "Security fix to prevent potential data exposure.",
            "Feature enhancement based on user feedback.",
            "Dependency update to address security vulnerabilities.",
            "Code cleanup and optimization for better performance.",
        ]

        self.comment_templates = [
            "LGTM! Great work on this implementation.",
            "Could you add some unit tests for this functionality?",
            "This looks good, but please update the documentation.",
            "I have some concerns about the performance impact.",
            "Nice solution! Very clean and readable code.",
            "Please consider edge cases in the error handling.",
            "This change might break backward compatibility.",
            "Excellent refactoring! Much cleaner now.",
            "Can we add some logging for debugging purposes?",
            "This implementation follows our coding standards well.",
        ]

    def generate_azure_devops_pr_data(
        self,
        count: int = 50,
        include_iac: bool = True,
        include_personal_approvals: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Generate mock Azure DevOps PR data.

        Args:
            count: Number of PRs to generate
            include_iac: Whether to include Infrastructure as Code PRs
            include_personal_approvals: Whether to include self-approvals

        Returns:
            List of mock Azure DevOps PR data
        """
        prs = []
        start_date = datetime.now() - timedelta(days=90)

        for i in range(count):
            pr_id = i + 1
            created_date = start_date + timedelta(days=random.randint(0, 90))
            creator = random.choice(self.developers)
            repository = random.choice(self.repositories)

            # Determine if this should be an IAC PR
            is_iac = include_iac and random.random() < 0.15  # 15% chance

            if is_iac:
                title = random.choice(self.iac_titles)
                description = (
                    "Infrastructure changes for improved deployment and scaling."
                )
            else:
                title = random.choice(self.pr_titles)
                description = random.choice(self.pr_descriptions)

            # Generate reviewers
            available_reviewers = [
                dev for dev in self.developers if dev["email"] != creator["email"]
            ]
            num_reviewers = random.randint(1, 4)
            reviewers = random.sample(
                available_reviewers, min(num_reviewers, len(available_reviewers))
            )

            # Add personal approval if enabled
            if include_personal_approvals and random.random() < 0.1:  # 10% chance
                reviewers.append(creator)

            # Generate reviewer data
            reviewer_data = []
            for reviewer in reviewers:
                vote = random.choices([10, 5, 0, -10], weights=[60, 20, 15, 5])[
                    0
                ]  # Weighted towards approval
                reviewer_data.append(
                    {
                        "displayName": reviewer["name"],
                        "uniqueName": reviewer["email"],
                        "vote": vote,
                        "isRequired": random.choice([True, False]),
                    }
                )

            # Generate threads/comments
            threads = []
            num_threads = random.randint(0, 5)
            for _ in range(num_threads):
                thread_author = random.choice(reviewers + [creator])
                threads.append(
                    {
                        "id": random.randint(1000, 9999),
                        "status": random.choice(["active", "resolved"]),
                        "comments": [
                            {
                                "author": {"displayName": thread_author["name"]},
                                "content": random.choice(self.comment_templates),
                                "publishedDate": (
                                    created_date + timedelta(days=random.randint(0, 5))
                                ).isoformat(),
                            }
                        ],
                    }
                )

            pr_data = {
                "pullRequestId": pr_id,
                "repository": {"name": repository, "id": f"repo-{repository.lower()}"},
                "title": title,
                "description": description,
                "creationDate": created_date.isoformat(),
                "closedDate": (
                    created_date + timedelta(days=random.randint(1, 7))
                ).isoformat(),
                "status": random.choices(
                    ["completed", "active", "abandoned"], weights=[80, 15, 5]
                )[0],
                "createdBy": {
                    "displayName": creator["name"],
                    "uniqueName": creator["email"],
                },
                "reviewers": reviewer_data,
                "threads": threads,
                "targetRefName": "refs/heads/main",
                "sourceRefName": f"refs/heads/feature/pr-{pr_id}",
            }

            prs.append(pr_data)

        return prs

    def generate_github_pr_data(
        self,
        count: int = 50,
        include_iac: bool = True,
        include_personal_approvals: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Generate mock GitHub PR data.

        Args:
            count: Number of PRs to generate
            include_iac: Whether to include Infrastructure as Code PRs
            include_personal_approvals: Whether to include self-approvals

        Returns:
            List of mock GitHub PR data
        """
        prs = []
        start_date = datetime.now() - timedelta(days=90)

        for i in range(count):
            pr_id = i + 1000  # Different ID range for GitHub
            created_date = start_date + timedelta(days=random.randint(0, 90))
            creator = random.choice(self.developers)
            repository = random.choice(self.repositories)

            # Determine if this should be an IAC PR
            is_iac = include_iac and random.random() < 0.15  # 15% chance

            if is_iac:
                title = random.choice(self.iac_titles)
                body = "Infrastructure changes for improved deployment and scaling."
            else:
                title = random.choice(self.pr_titles)
                body = random.choice(self.pr_descriptions)

            # Generate state and merge status
            state = random.choices(["closed", "open"], weights=[85, 15])[0]
            merged = (
                state == "closed" and random.random() < 0.9
            )  # 90% of closed PRs are merged

            # Generate reviewers and reviews
            available_reviewers = [
                dev for dev in self.developers if dev["email"] != creator["email"]
            ]
            num_reviewers = random.randint(1, 4)
            reviewers = random.sample(
                available_reviewers, min(num_reviewers, len(available_reviewers))
            )

            # Add personal approval if enabled
            if include_personal_approvals and random.random() < 0.1:  # 10% chance
                reviewers.append(creator)

            # Generate reviews
            reviews = []
            for reviewer in reviewers:
                review_state = random.choices(
                    ["APPROVED", "CHANGES_REQUESTED", "COMMENTED"], weights=[65, 15, 20]
                )[0]

                reviews.append(
                    {
                        "id": random.randint(10000, 99999),
                        "user": {"login": reviewer["email"].split("@")[0]},
                        "state": review_state,
                        "body": (
                            random.choice(self.comment_templates)
                            if review_state == "COMMENTED"
                            else ""
                        ),
                        "submitted_at": (
                            created_date + timedelta(days=random.randint(0, 5))
                        ).isoformat(),
                    }
                )

            # Generate comments
            comments = []
            num_comments = random.randint(0, 8)
            for _ in range(num_comments):
                commenter = random.choice(reviewers + [creator])
                comments.append(
                    {
                        "id": random.randint(100000, 999999),
                        "user": {"login": commenter["email"].split("@")[0]},
                        "body": random.choice(self.comment_templates),
                        "created_at": (
                            created_date + timedelta(days=random.randint(0, 5))
                        ).isoformat(),
                    }
                )

            pr_data = {
                "id": pr_id,
                "number": pr_id - 999,  # GitHub PR number
                "title": title,
                "body": body,
                "user": {"login": creator["email"].split("@")[0]},
                "created_at": created_date.isoformat(),
                "updated_at": (
                    created_date + timedelta(days=random.randint(0, 7))
                ).isoformat(),
                "closed_at": (
                    (created_date + timedelta(days=random.randint(1, 7))).isoformat()
                    if state == "closed"
                    else None
                ),
                "merged_at": (
                    (created_date + timedelta(days=random.randint(1, 7))).isoformat()
                    if merged
                    else None
                ),
                "state": state,
                "merged": merged,
                "repository_name": repository,
                "repository_full_name": f"company/{repository.lower()}",
                "repository_id": random.randint(1000000, 9999999),
                "base": {"ref": "main"},
                "head": {"ref": f"feature/pr-{pr_id}"},
                "reviews": reviews,
                "comments": comments,
            }

            prs.append(pr_data)

        return prs

    def generate_mixed_data(
        self,
        azure_count: int = 25,
        github_count: int = 25,
        include_iac: bool = True,
        include_personal_approvals: bool = True,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate mixed Azure DevOps and GitHub PR data.

        Args:
            azure_count: Number of Azure DevOps PRs to generate
            github_count: Number of GitHub PRs to generate
            include_iac: Whether to include Infrastructure as Code PRs
            include_personal_approvals: Whether to include self-approvals

        Returns:
            Dictionary with 'azure_devops' and 'github' keys containing respective PR data
        """
        return {
            "azure_devops": self.generate_azure_devops_pr_data(
                azure_count, include_iac, include_personal_approvals
            ),
            "github": self.generate_github_pr_data(
                github_count, include_iac, include_personal_approvals
            ),
        }

    def save_to_file(self, data: Dict[str, Any], filename: str) -> None:
        """
        Save generated data to a JSON file.

        Args:
            data: Data to save
            filename: Output filename
        """
        output_path = Path(filename)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"✅ Mock data saved to {output_path}")

    def generate_excel_compatible_data(self, count: int = 50) -> List[Dict[str, Any]]:
        """
        Generate data in the same format as the processed Excel output.
        This can be used to test the dashboard without running the full pipeline.

        Args:
            count: Number of PRs to generate

        Returns:
            List of processed PR data compatible with the dashboard
        """
        processed_data = []
        start_date = datetime.now() - timedelta(days=90)

        for i in range(count):
            pr_id = i + 1
            created_date = start_date + timedelta(days=random.randint(0, 90))
            creator = random.choice(self.developers)
            repository = random.choice(self.repositories)
            platform = random.choice(["Azure DevOps", "GitHub"])

            # Generate reviewers
            available_reviewers = [
                dev for dev in self.developers if dev["email"] != creator["email"]
            ]
            num_reviewers = random.randint(1, 4)
            reviewers = random.sample(
                available_reviewers, min(num_reviewers, len(available_reviewers))
            )

            # Generate approvals and rejections
            approvers = []
            rejectors = []
            waiting_reviewers = []

            for reviewer in reviewers:
                decision = random.choices(
                    ["approve", "reject", "waiting"], weights=[70, 10, 20]
                )[0]
                if decision == "approve":
                    approvers.append(reviewer["name"])
                elif decision == "reject":
                    rejectors.append(reviewer["name"])
                else:
                    waiting_reviewers.append(reviewer["name"])

            # Generate comments
            commenters = random.sample(reviewers, random.randint(0, len(reviewers)))
            total_comments = random.randint(0, 10)

            processed_pr = {
                "PR ID": pr_id,
                "Repository": repository,
                "Title": random.choice(self.pr_titles),
                "Description": random.choice(self.pr_descriptions),
                "Created By": creator["name"],
                "Created Date": created_date.strftime("%Y-%m-%d %H:%M:%S"),
                "Updated Date": (
                    created_date + timedelta(days=random.randint(0, 5))
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "Closed Date": (
                    created_date + timedelta(days=random.randint(1, 7))
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "Status": random.choices(
                    ["Completed", "Active", "Abandoned"], weights=[80, 15, 5]
                )[0],
                "Platform": platform,
                "Assigned To": [r["name"] for r in reviewers],
                "Approved By": approvers,
                "Rejected By": rejectors,
                "Waiting Reviewers": waiting_reviewers,
                "Total Reviewers": len(reviewers),
                "Approval Count": len(approvers),
                "Rejection Count": len(rejectors),
                "Reviewer Count": len(reviewers),
                "Total Comments": total_comments,
                "Commenters": [c["name"] for c in commenters],
                "Comment Count": len(commenters),
                "Active Threads": random.randint(0, 3),
                "Resolved Threads": random.randint(0, 5),
                "Total Threads": random.randint(0, 8),
                "Year": created_date.year,
                "Month": created_date.month,
                "Day": created_date.day,
                "Weekday": created_date.strftime("%A"),
                "Hour": created_date.hour,
                "Year-Month": created_date.strftime("%Y-%m"),
            }

            processed_data.append(processed_pr)

        return processed_data


def main():
    """CLI interface for the mock data generator."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate mock PR data for testing")
    parser.add_argument(
        "--azure-count", type=int, default=25, help="Number of Azure DevOps PRs"
    )
    parser.add_argument(
        "--github-count", type=int, default=25, help="Number of GitHub PRs"
    )
    parser.add_argument("--output", default="mock_data.json", help="Output filename")
    parser.add_argument("--seed", type=int, help="Random seed for reproducible data")
    parser.add_argument(
        "--excel-format", action="store_true", help="Generate Excel-compatible format"
    )
    parser.add_argument("--no-iac", action="store_true", help="Exclude IAC PRs")
    parser.add_argument(
        "--no-personal-approvals",
        action="store_true",
        help="Exclude personal approvals",
    )

    args = parser.parse_args()

    generator = MockDataGenerator(seed=args.seed)

    if args.excel_format:
        data = generator.generate_excel_compatible_data(
            args.azure_count + args.github_count
        )
        output_file = args.output.replace(".json", ".json")
    else:
        data = generator.generate_mixed_data(
            azure_count=args.azure_count,
            github_count=args.github_count,
            include_iac=not args.no_iac,
            include_personal_approvals=not args.no_personal_approvals,
        )
        output_file = args.output

    generator.save_to_file(data, output_file)
    print(
        f"📊 Generated mock data with {
            len(data) if isinstance(
                data, list) else sum(
                len(v) for v in data.values())} PRs"
    )


if __name__ == "__main__":
    main()
