import re
from time import sleep
import asyncio
import traceback
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from openai import OpenAI
from datetime import datetime

# from github import GithubException

from src.constants import HEADERS
from src.github_requests import github_requests
from src.db_client import db
from src.util.is_test_file import is_test_file
from src.util.is_asset_file import is_asset_file
from src.db_client import Instance
from src.extract_pr_changed_files import extract_pr_changed_files_from_patch
from src.util.extract_patch import extract_patch
from src.context import context
from src.env import env


LANGUAGE_CONFIG = json.load(open("src/pr_sourcing/language_config.json"))
MIN_ISSUE_WORDS = 50
MAX_ISSUE_WORDS = 6000
MIN_PR_CODE_CHANGES = 20

# Prompt for the AI agent to evaluate GitHub issues.
AGENT_PROMPT = """
You are a senior software engineer evaluating a GitHub issue to determine if it's suitable for a "Good PR".

A "Good PR" is linked to an issue that meets these criteria:
1.  **Clear and Actionable**: It describes a specific, actionable problem or feature, providing enough context for a developer to start working.
2.  **Not a Revert**: The issue must not be a request to simply revert previous changes or roll back to an older version.
3.  **Not a Question or Vague Request**: It must not be a simple user question, a vague request for help, or a request for documentation.
4.  **Single Issue Focus**: The issue should be focused on closing a single, well-defined problem or feature request.
5.  **Primarily in English**: At least 90 percent of the issue content should be written in English.

Analyze the following issue body and determine if it represents a "Good PR" or a "Bad PR" based on these criteria.

---
{issue_body}
---

Respond with a JSON object containing two keys:
1. "result": A string, either "Good PR" or "Bad PR".
2. "comment": A brief explanation for your decision.
"""


def count_words(text):
    return len(re.findall(r'\b\w+\b', text))


def get_issue_details(owner, repo, issue_id):
    query = """
        query ($owner: String!, $name: String!, $issueNumber: Int!) {
            repository(owner: $owner, name: $name) {
                issue(number: $issueNumber) {
                    title
                    body
                    url
                    labels(first: 10) {
                        nodes {
                            name
                            color
                        }
                    }
                    comments(first: 100) {
                        nodes {
                            author { login }
                            body
                            createdAt
                        }
                    }
                }
            }
        }
    """
    vars = {"owner": owner, "name": repo, "issueNumber": issue_id}

    issue_details = github_requests.graphql(query, vars)

    if issue_details.get('errors'):
        print(
            f"Error fetching issue details for {owner}/{repo} {issue_id}: {issue_details['errors'][0]['message']}")
        return None, None, None

    issue = issue_details.get('data', {}).get('repository', {}).get('issue')

    if issue is None:
        return None, None, None

    title = issue.get('title', '')
    body = issue.get('body', '')

    labels = [label['name']
              for label in issue.get('labels', {}).get('nodes', [])]

    comments_data = issue.get('comments', None)

    if comments_data and 'nodes' in comments_data:
        comments = [
            {
                'author': comment['author']['login'] if comment['author'] else None,
                'content': comment['body'],
                'timestamp': comment['createdAt']
            }
            for comment in comments_data['nodes']
        ]
    else:
        comments = [{'author': None, 'content': None, 'timestamp': None}]

    return f"{title}\n{body}", labels, comments

#@deprecated get it from closing issue node instead
def extract_issue_id(pr_body: str) -> str:
    """
    Extracts the issue ID from the PR body.
    """
    if not pr_body:
        return None
    return re.search(r'#(\d+)', pr_body).group(1)

def safe_run_llm_check(issue_body: str):
    """
    Runs the LLM check in a separate thread with a timeout to prevent hang-ups.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_llm_check, issue_body)
        try:
            # Wait a maximum of 20 seconds for the LLM response
            return future.result(timeout=20)
        except TimeoutError:
            context.logger.warning("LLM check timed out!")
            return "Bad PR", "LLM check timed out."
        except Exception as e:
            context.logger.error(f"Exception during LLM check: {e}")
            return "Bad PR", f"LLM check failed: {e}"


def run_llm_check(issue_body: str):
    """
    Calls the OpenAI API to evaluate an issue body against predefined criteria.
    """
    print("Running LLM check for issue body...")
    if not issue_body or len(issue_body.strip()) < 50:
        # context.logger.info("Issue body is too short for LLM analysis.")
        print("Issue body is too short for LLM analysis")
        return "Bad PR", "Issue body is too short."
    try:
        client = OpenAI(api_key=env.OPENAI_API_KEY)
        prompt = AGENT_PROMPT.format(issue_body=issue_body)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        print(f"LLM result: {result}")
        # context.logger.info(f"LLM result: {result}")
        return result.get("result"), result.get("comment", "LLM response missing comment.")
    except Exception as e:
        context.logger.error(f"LLM analysis failed: {e}")
        return "Bad PR", f"LLM analysis failed: {e}"


def is_english(text: str) -> bool:
    """
    Checks if at least 90% of the text is in English.
    """
    if not text:
        return False
    # A simple heuristic: check the proportion of ASCII characters.
    # This is not perfect but often good enough.
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    return (ascii_chars / len(text)) >= 0.9


def is_test_file_path(filename: str, language_config_for_repo: dict) -> bool:
    """
    Checks if a filename corresponds to a typical test file for the given language.
    """
    if not language_config_for_repo:
        return is_test_file({'language': 'default'}, filename)

    if is_test_file({'language': language_config_for_repo.get('name', 'default')}, filename):
        return True

    for pattern in language_config_for_repo.get("file_analysis", {}).get("test_patterns", []):
        if re.search(pattern, filename):
            return True
    return False

def is_asset_file_path(filename: str, language_config_for_repo: dict) -> bool:
    """
    Checks if a filename corresponds to an asset file.
    """
    if not language_config_for_repo:
        return is_asset_file({'language': 'default'}, filename)
    return is_asset_file({'language': language_config_for_repo.get('name', 'default')}, filename)


def get_full_patch(repo, base_commit, head_commit):
    diff_headers = HEADERS.copy()
    diff_headers["Accept"] = "application/vnd.github.v3.diff"
    response = github_requests.get(
        f"https://api.github.com/repos/{repo}/compare/{base_commit}...{head_commit}", headers=diff_headers)
    if response.status_code != 200:
        print(f"[ERROR] GitHub API failed: HTTP {response.status_code}")
        raise Exception(
            f"Failed to get full patch for instance {repo} {base_commit} {head_commit}")

    return response.text


def fetch_prs(owner, repo, cursor=None, page_size=100):
    query = """
        query($owner: String!, $name: String!, $cursor: String, $page_size: Int!) {
            repository(owner: $owner, name: $name) {
                primaryLanguage { name }
                pullRequests(first: $page_size, after: $cursor, states: MERGED, orderBy: { field: CREATED_AT, direction: DESC }) {
                    pageInfo {
                        endCursor
                        hasNextPage
                    }
                    nodes {
                        number
                        body
                        baseRefOid
                        headRefOid
                        mergedAt
                        files(first: 100) {
                            nodes { path, changeType, additions, deletions }
                        }
                        closingIssuesReferences(first: 1) {
                            nodes {
                                number
                                title
                                body
                                url
                                labels(first: 10) {
                                    nodes {
                                        name
                                        color
                                    }
                                }
                                comments(first: 100) {
                                    nodes {
                                        author { login }
                                        body
                                        createdAt
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    """
    vars = {"owner": owner, "name": repo,
            "cursor": cursor, "page_size": page_size}

    return github_requests.graphql(query, vars)


def fetch_relevant_prs(
    owner, repo,
    max_prs=None,
    min_test_files=1,
    max_non_test_files=100,
    nocache=False,
    start_date: str = "2024-11-01",
):
    """
    Fetches pull requests from GitHub, ensuring no more than `max_prs` are fetched in total.
    It then filters these based on relevance criteria and saves them to the database.
    """
    cursor = None
    count = 0
    saved = 0
    stop_fetching = False

    session = db.get_session()
    g = github_requests.get_github_client()
    try:
        repo_obj = g.get_repo(f"{owner}/{repo}")
    except GithubException as e:
        context.logger.error(f"Failed to get repo {owner}/{repo}: {e}")
        return

    effective_start_date = datetime.fromisoformat(
        start_date).replace(tzinfo=datetime.now().astimezone().tzinfo)

    try:
        while True:
            page_size = 100
            if max_prs is not None:
                # Calculate how many more PRs we are allowed to fetch to stay under max_prs
                remaining_to_fetch_overall = max_prs - count
                if remaining_to_fetch_overall <= 0:
                    print(
                        f"Already fetched {count} PRs, which meets or exceeds max_prs ({max_prs}). Stopping new API requests.")
                    break
                page_size = min(100, remaining_to_fetch_overall)

            print(
                f"Fetching {page_size} PRs from GitHub (total processed so far: {count})...")

            res = fetch_prs(owner, repo, cursor, page_size)

            if res.get('errors'):
                print(
                    f"Error fetching PRs for {owner}/{repo}: {res['errors'][0]['message']}")
                context.logger.error(
                    f"Error fetching PRs for {owner}/{repo}: {res['errors'][0]['message']}")
                break

            repo_data = res.get('data', {}).get('repository', {})
            language = repo_data.get('primaryLanguage', {}).get('name', None)
            pr_nodes = repo_data.get('pullRequests', {}).get('nodes', [])
            page_info = repo_data.get('pullRequests', {}).get('pageInfo', {})

            if language is None:
                print(f"No language found for {owner}/{repo}")
                break

            language_config = LANGUAGE_CONFIG.get(language)
            if not language_config:
                context.logger.warning(
                    f"No language config found for {language}, skipping...")
                break

            for pr in pr_nodes:
                instance_id = f"{owner}__{repo}-{pr['number']}"

                count += 1
                print(f'[{saved}/{count}] {owner}/{repo} {pr["number"]}')

                pr_merged_at = datetime.fromisoformat(
                    pr["mergedAt"].replace("Z", "+00:00"))
                if pr_merged_at < effective_start_date:
                    context.logger.info(
                        f"PR {pr['number']} is older than {start_date}. Stopping.")
                    stop_fetching = True
                    break

                instance = session.query(Instance).filter(
                    Instance.instance_id == instance_id).first()

                if max_prs is not None and count > max_prs:
                    print(
                        f"Fetched {count} PRs in total for {owner}/{repo}, exceeding max_prs ({max_prs}). Stopping processing this page.")
                    context.logger.info(
                        f"Fetched {count} PRs in total for {owner}/{repo}, exceeding max_prs ({max_prs}). Stopping processing this page.")
                    stop_fetching = True
                    break

                print(
                    f'[{saved}/{count}] Checking PR {owner}/{repo} #{pr["number"]}')

                # skip if instance already exists and nocache is False
                if instance is not None and not nocache:
                    saved += 1
                    print(
                        f"PR {pr['number']} already exists in DB for {owner}/{repo} and caching is enabled. Skipping.")
                    continue

                # skip if to many files changed
                files = [f['path']
                         for f in pr.get('files', {}).get('nodes', [])]
                if len(files) > max_non_test_files:
                    continue

                # skip if no test files
                test_files = [f for f in files if is_test_file_path(
                    f, language_config) and not is_asset_file_path(f, language_config)]
                print(f"{owner}/{repo} {pr['number']} Test files: {test_files}")
                context.logger.info(f"{owner}/{repo} {pr['number']} Test files: {test_files}")
                if len(test_files) < min_test_files:
                    context.logger.info(f"{owner}/{repo} {pr['number']} Test files < min_test_files: {len(test_files)} < {min_test_files}")
                    continue

                code_line_changes = 0
                for file in pr.get('files', {}).get('nodes', []):
                    if not is_test_file_path(file['path'], language_config):
                        code_line_changes += file['additions'] + \
                            file['deletions']

                if code_line_changes < MIN_PR_CODE_CHANGES:
                    continue

                # skip if no linked issue
                issue_nodes = pr.get(
                    "closingIssuesReferences", {}).get("nodes", [])
                if not issue_nodes:
                    continue

                issue_data = issue_nodes[0]
                issue_number = issue_data["number"]

                try:
                    issue = repo_obj.get_issue(number=issue_number)
                except:
                    context.logger.warning(
                        f"Could not retrieve issue #{issue_number} for PR #{pr['number']}.")
                    continue

                if issue.user.type == "Bot":
                    context.logger.info(
                        f"Issue #{issue.number} was created by a bot. Skipping PR #{pr['number']}.")
                    continue

                issue_body = f"{issue.title}\n{issue.body}"
                issue_labels = [label.name for label in issue.labels]
                issue_comments = [
                    {
                        'author': comment.user.login if comment.user else None,
                        'content': comment.body,
                        'timestamp': comment.created_at.isoformat()
                    }
                    for comment in issue.get_comments()
                ]

                word_count = count_words(issue_body or '')

                # skip if issue body is too short or too long
                if word_count < MIN_ISSUE_WORDS or word_count > MAX_ISSUE_WORDS:
                    continue

                if not is_english(issue_body):
                    print(
                        f"Issue body for {pr['number']} is not in English. Skipping.")
                    continue

                llm_result, llm_comment = safe_run_llm_check(issue_body)
                if llm_result != "Good PR":
                    context.logger.info(
                        f"LLM check failed for {pr['number']}: {llm_comment}. Skipping.")
                    print(f"LLM check failed for {pr['number']}: {llm_comment}. Skipping.")
                    continue

                # if got to this point then pr is relevant

                # collect other pr details

                if instance is None:
                    instance = Instance()

                instance.instance_id = instance_id
                instance.repo_id = f"{owner}__{repo}"
                instance.repo = f"{owner}/{repo}"
                instance.pr_id = pr['number']
                instance.issue_id = issue_number

                instance.problem_statement = issue_body
                instance.issue_word_count = word_count
                # instance.conversation = "\n\n".join(issue_comments)
                instance.issue_conversation = issue_comments

                instance.language = language

                instance.base_commit = pr['baseRefOid']
                instance.head_commit = pr['headRefOid']

                full_patch = get_full_patch(
                    instance.repo, instance.base_commit, instance.head_commit)

                instance.pr_changed_files_v2 = extract_pr_changed_files_from_patch(
                    language, pr['files']['nodes'], full_patch)
                print(f"{owner}/{repo} {pr['number']} PR changed files: {instance.pr_changed_files_v2}")
                context.logger.info(f"{owner}/{repo} {pr['number']} PR changed files: {instance.pr_changed_files_v2}")

                context.logger.info(f"{owner}/{repo} {pr['number']} Test files 2: {test_files}")

                test_files = [f['filename']
                              for f in instance.pr_changed_files_v2 if f['is_test_file']]
                non_test_files = [
                    f['filename'] for f in instance.pr_changed_files_v2 if not f['is_test_file']]

                context.logger.info(f"{owner}/{repo} {pr['number']} Test files 3: {test_files}")

                instance.pr_changed_files = [f['filename']
                                             for f in instance.pr_changed_files_v2]
                instance.pr_changed_test_files = [
                    f['filename'] for f in instance.pr_changed_files_v2 if f['is_test_file']]

                instance.test_files_count = len(instance.pr_changed_test_files)
                instance.non_test_files_count = len(
                    instance.pr_changed_files) - instance.test_files_count

                instance.pr_merged_at = pr['mergedAt']
                instance.task_type = 'bugfix'
                instance.pr_labels = issue_labels

                instance.patch = extract_patch(full_patch, non_test_files)
                instance.test_patch = extract_patch(full_patch, test_files)

                instance.before_repo_set_cmd = (
                    f"git fetch origin {instance.base_commit} && "
                    f"git fetch origin {instance.head_commit} && "
                    f"git checkout {instance.base_commit} && "
                    f"git checkout {instance.head_commit} -- {' '.join(test_files)}"
                )

                instance.after_repo_set_cmd = f"git fetch origin {instance.head_commit} && git checkout {instance.head_commit}"

                num_files = len(instance.pr_changed_files or [])
                instance.difficulty_score = 1.0 if num_files <= 2 else 2.0 if num_files <= 5 else 3.0

                session.add(instance)
                session.commit()

                saved += 1
                print(f'[{saved}/{count}] {owner}/{repo} {pr["number"]} saved')

                if max_prs is not None and saved >= max_prs:
                    print(
                        f"Reached the target of {max_prs} relevant PRs saved. Will stop fetching more.")
                    # Setting count to max_prs to trigger the outer loop break on next iteration
                    count = max_prs
                    break

                # sleep for 2 second
                sleep(2)

            if stop_fetching:
                break

            if max_prs is not None and count >= max_prs:
                print(
                    f"Total PRs fetched from GitHub ({count}) reached or exceeded max_prs ({max_prs}). Stopping further API requests.")
                break

            # stop if no more pages
            if not page_info['hasNextPage']:
                print(f"No more pages for {owner}/{repo}")
                break

            # take next cursor
            cursor = page_info['endCursor']

        context.logger.info(f"Processed {saved} PRs for {owner}/{repo}")
    except Exception as e:
        print(f"Error: {str(e)}")
        print(f"Error: {traceback.format_exc()}")
        context.logger.error(f"Error: {str(e)}")
        context.logger.error(f"Error: {traceback.format_exc()}")
        session.rollback()
        raise Exception(f"Error fetching relevant PRs for {owner}/{repo}")
    finally:
        session.close()


async def main():
    await db.connect()

    fetch_relevant_prs('apache', 'arrow', nocache=True)

    await db.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
