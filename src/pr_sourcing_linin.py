import os
import re
import time
import csv
import argparse
from datetime import datetime
from github import Github, GithubException, RateLimitExceededException

# --- Configuration ---

# IMPORTANT: Set your GitHub Personal Access Token as an environment variable named 'GITHUB_TOKEN'
# This is required for making a high volume of requests to the GitHub API.
# How to create a token: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/creating-a-personal-access-token
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# The start date for issues and PRs (YYYY-MM-DD).
# For testing, you can change this to a past date, e.g., '2023-11-01'.
START_DATE = "2024-11-01"

# The minimum number of stars a repository must have.
MIN_STARS = 2000

# Keywords to identify PR categories from labels and titles.
CATEGORY_KEYWORDS = {
    "Bugfix": ["bug", "fix", "defect", "patch"],
    "New feature / enhancement": ["feature", "enhancement", "improvement", "feat"],
    "UI/UX changes": ["ui", "ux", "frontend", "user interface", "design"],
    "Reliability / stability improvements": ["reliability", "stability", "crash", "resilience"],
    "Application logic updates": ["logic", "refactor", "business", "core"],
    "Server-side logic": ["backend", "server", "api", "database"]
}

# Output file name
OUTPUT_CSV_FILE = "github_issue_pr_pairs.csv"


def get_linked_issue_number(pr_body):
    """
    Parses a PR body to find keywords that link to and close an issue.
    Looks for patterns like 'closes #123', 'fixes #456', etc.
    """
    if not pr_body:
        return None
    match = re.search(r'(?i)(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#(\d+)', pr_body)
    if match:
        return int(match.group(1))
    return None

# TODO(lilin): use LLM judge for categorization
def get_pr_categories(pull_request):
    """
    Categorizes a PR based on its labels and title.
    """
    categories = set()
    text_to_search = pull_request.title.lower()
    for label in pull_request.get_labels():
        text_to_search += f" {label.name.lower()}"
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text_to_search for keyword in keywords):
            categories.add(category)
    return list(categories) if categories else ["Uncategorized"]

# lilin: This Heuristic approach might be sufficient. If not, we could consider using LLM judge.
def has_test_files(pull_request):
    """
    Heuristic to check if a PR modifies test files.
    """
    try:
        files = pull_request.get_files()
        for file in files:
            if file.filename.startswith('src/test/') or 'Test.java' in file.filename:
                return True
    except GithubException as e:
        print(f"  [Warning] Could not retrieve files for PR #{pull_request.number}: {e}")
    return False

def has_modern_toolchain(repo, cache):
    """
    Checks if a repository contains a pom.xml (Maven) or build.gradle (Gradle).
    """
    if repo.full_name in cache:
        return cache[repo.full_name]
    try:
        repo.get_contents("pom.xml")
        cache[repo.full_name] = True
        return True
    except GithubException:
        try:
            repo.get_contents("build.gradle")
            cache[repo.full_name] = True
            return True
        except GithubException:
            cache[repo.full_name] = False
            return False

def is_english(text):
    """
    A more lenient heuristic to check if a string is likely in English.
    Returns True if over 90% of characters are ASCII.
    """
    if not text or not text.strip():
        return True  # Assume empty descriptions are fine
    
    total_chars = len(text)
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    
    # If the proportion of ASCII characters is high, assume it's English
    if (ascii_chars / total_chars) >= 0.9:
        return True
        
    return False

def main(target_pr_count):
    """
    Main function to orchestrate the scraping process using a continuous funnel approach.
    It finds eligible repositories one by one and processes their PRs until the target is met.
    """
    if not GITHUB_TOKEN:
        print("Error: GITHUB_TOKEN environment variable not set.")
        return

    print("Initializing GitHub client...")
    g = Github(GITHUB_TOKEN)
    
    results = []
    repo_toolchain_cache = {}
    
    # Query for popular, active Java repos
    repo_query = f"language:java stars:>{MIN_STARS} sort:stars-desc"
    
    try:
        repositories = g.search_repositories(query=repo_query)
        print("Starting search for eligible repositories and PRs...")
        
        # --- Continuous Funnel: Find a repo, then process its PRs ---
        for repo in repositories:
            if len(results) >= target_pr_count:
                print(f"\nTarget of {target_pr_count} PRs reached. Halting search.")
                break
                
            print(f"\n--- Checking repository: {repo.full_name} ---")

            # Rule 4: Modern toolchain (Maven/Gradle)
            if not has_modern_toolchain(repo, repo_toolchain_cache):
                print(f"  [Skip] Repo does not use Maven or Gradle.")
                continue

            print(f"  [Pass] Repo is eligible. Searching for PRs...")

            try:
                # Query for merged PRs within this specific repo (Rule 3)
                pr_query = f"repo:{repo.full_name} is:pr is:merged created:>={START_DATE} sort:created-desc"
                pull_requests = g.search_issues(query=pr_query)

                for pr_issue_obj in pull_requests:
                    if len(results) >= target_pr_count:
                        break
                    
                    print(f"    Processing PR: {pr_issue_obj.html_url}")
                    
                    # Rule 2: PR must fully resolve an issue
                    linked_issue_num = get_linked_issue_number(pr_issue_obj.body)
                    if not linked_issue_num:
                        print(f"      [Skip] PR #{pr_issue_obj.number} does not link to a closing issue.")
                        continue

                    try:
                        issue = repo.get_issue(number=linked_issue_num)
                        
                        # **FIX**: Ensure the linked item is an actual issue, not another PR.
                        # An Issue object that is a PR will have a 'pull_request' attribute.
                        if issue.pull_request:
                            print(f"      [Skip] Linked item #{issue.number} is a Pull Request, not an Issue.")
                            continue

                        # Get the full PullRequest object to access PR-specific methods
                        full_pr = repo.get_pull(pr_issue_obj.number)

                        # Rule 6: All descriptions must be in English
                        if not (is_english(full_pr.title) and is_english(full_pr.body) and is_english(issue.title) and is_english(issue.body)):
                            print(f"      [Skip] PR #{full_pr.number} or Issue #{issue.number} contains too many non-English characters.")
                            continue
                        
                        # Rule 7: Must include test file changes
                        if not has_test_files(full_pr):
                            print(f"      [Skip] PR #{full_pr.number} does not appear to modify test files.")
                            continue
                        
                        # --- All Rules Passed: Gather Final Data ---
                        categories = get_pr_categories(full_pr)
                        files_changed = full_pr.changed_files
                        lines_added = full_pr.additions
                        lines_deleted = full_pr.deletions

                        results.append({
                            "repository": repo.full_name,
                            "issue_title": issue.title,
                            "issue_url": issue.html_url,
                            "pr_title": full_pr.title,
                            "pr_url": full_pr.html_url,
                            "categories": ", ".join(categories),
                            "files_changed": files_changed,
                            "lines_added": lines_added,
                            "lines_deleted": lines_deleted
                        })
                        print(f"      [Success] Added pair. Total found: {len(results)}/{target_pr_count}")

                    except RateLimitExceededException:
                        print("      Rate limit exceeded. Waiting for 60 seconds...")
                        time.sleep(60)
                        continue
                    except GithubException as e:
                        print(f"      [Skip] Error processing PR #{pr_issue_obj.number} or issue #{linked_issue_num}: {e}")
                        continue
            
            except RateLimitExceededException:
                print(f"    Rate limit exceeded while searching PRs in {repo.full_name}. Waiting...")
                time.sleep(60)
                continue
            except Exception as e:
                print(f"    An unexpected error occurred while processing {repo.full_name}: {e}")
                continue

    except RateLimitExceededException:
        print("Rate limit exceeded during initial repository search. Please wait and try again.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    # --- Save results to CSV ---
    if results:
        print(f"\nSearch complete. Found {len(results)} pairs. Saving to {OUTPUT_CSV_FILE}...")
        with open(OUTPUT_CSV_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                "repository", "issue_title", "issue_url", "pr_title", "pr_url",
                "categories", "files_changed", "lines_added", "lines_deleted"
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        print("Successfully saved results to CSV.")
    else:
        print("\nSearch complete. No matching issue/PR pairs were found.")
        print(f"NOTE: Your start date is set to {START_DATE}. If this is in the future, no results will be found.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape GitHub for issue/PR pairs based on a set of rules.")
    parser.add_argument("--target_pr_count", type=int, default=1000,
                        help="The total number of issue/PR pairs you want to find.")
    args = parser.parse_args()
    
    main(args.target_pr_count)