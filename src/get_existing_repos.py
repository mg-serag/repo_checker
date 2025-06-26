import requests
import csv
import datetime
import os

# --- CONFIGURATION ---
# PROJECT_ID = 40 # Python project 
# PROJECT_ID = 41 # JS project
# PROJECT_ID = 42 # Java project
PROJECT_ID = 43 # Go project


LT_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6Im1vaGFtYWQuc0B0dXJpbmcuY29tIiwic3ViIjoxMTYsImlhdCI6MTc1MDc0NzY0MywiZXhwIjoxNzUxMzUyNDQzfQ.De_PSAqQl306vqf7BEFIYbjo66zehS8coPtUEfZhk8w"

# --- API URLS ---
BASE_BATCHES_URL = f"https://eval.turing.com/api/batches?sort%5B0%5D=createdAt%2CDESC&join%5B0%5D=batchStats&join%5B1%5D=importAttempts&filter%5B0%5D=projectId%7C%7C%24eq%7C%7C{PROJECT_ID}"
BASE_CONVERSATIONS_URL = "https://eval.turing.com/api/conversations?join%5B0%5D=project%7C%7Cid%2Cname&join%5B1%5D=batch%7C%7Cid%2Cname&join%5B2%5D=seed%7C%7Cmetadata"


def fetch_existing_repos():
    """Fetches all batch data from the API by handling pagination."""
    headers = {"Authorization": f"Bearer {LT_TOKEN}"}
    all_batches = []
    page = 1
    limit = 100

    while True:
        paginated_url = f"{BASE_BATCHES_URL}&limit={limit}&page={page}"
        print(f"Fetching batches from page {page}...")
        try:
            response = requests.get(paginated_url, headers=headers)
            response.raise_for_status()
            json_data = response.json()
            batches_on_page = json_data.get("data")
            if not batches_on_page:
                break
            all_batches.extend(batches_on_page)
            if len(batches_on_page) < limit:
                break
            page += 1
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while fetching batches on page {page}: {e}")
            return None
    return {"data": all_batches}


def fetch_conversations_for_batch(batch_id):
    """Fetches all conversations for a specific batch ID."""
    headers = {"Authorization": f"Bearer {LT_TOKEN}"}
    all_conversations = []
    page = 1
    limit = 100

    while True:
        filter_param = f"&filter%5B0%5D=batchId%7C%7C%24in%7C%7C{batch_id}"
        paginated_url = f"{BASE_CONVERSATIONS_URL}{filter_param}&limit={limit}&page={page}"
        print(f"  Fetching conversations for batch {batch_id}, page {page}...")
        try:
            response = requests.get(paginated_url, headers=headers)
            response.raise_for_status()
            json_data = response.json()
            conversations_on_page = json_data.get("data")
            if not conversations_on_page:
                break
            all_conversations.extend(conversations_on_page)
            if len(conversations_on_page) < limit:
                break
            page += 1
        except requests.exceptions.RequestException as e:
            print(f"An error occurred while fetching conversations for batch {batch_id}: {e}")
            return None
    return all_conversations


def save_repo_summary_to_csv(data, header, filename="existing_repos.csv"):
    """Saves the main repository summary data to a CSV file."""
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(data)
    print(f"\nRepository summary successfully saved to {filename}")


def save_prs_to_csv(batch_name, pr_data, output_dir="batch_prs"):
    """Saves PR data to a batch-specific CSV file."""
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{batch_name}.csv")
    header = ["pr_id"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(pr_data)
    print(f"  Saved {len(pr_data)} PRs to {filename}")


def main():
    """Main function to fetch, process, and save repository data."""
    repo_data = fetch_existing_repos()

    if not repo_data or not repo_data.get("data"):
        print("No repository data received or data is empty.")
        return

    processed_repo_data = []
    
    # Dynamically determine status keys from the first valid item
    status_keys = []
    for item in repo_data["data"]:
        if item and item.get("batchStats"):
            status_keys = sorted(item["batchStats"].keys())
            break
    if not status_keys:
        print("Warning: No batches with batchStats found. CSV will only contain basic info.")
        
    repo_header = ["Repository", "Author", "CreatedAt", "Total Conversations"] + status_keys

    for batch in repo_data["data"]:
        repo_name = batch.get("name", "Unknown").replace("__", "/")
        author_name = batch.get("author", {}).get("name", "Unknown")
        total_conversations = batch.get("countOfConversations", 0)
        created_at_raw = batch.get("createdAt")
        try:
            created_at = datetime.datetime.fromisoformat(created_at_raw).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            created_at = "Invalid Date"
        
        batch_stats = batch.get("batchStats")

        # Handle batches with no stats (e.g., not imported)
        if not batch_stats:
            print(f"Batch '{repo_name}' has no batchStats. Marking as NOT IMPORTANT and skipping PRs.")
            row = [repo_name, author_name, created_at, total_conversations]
            row.extend(["NOT IMPORTANT"] * len(status_keys))
            processed_repo_data.append(row)
            continue

        # Process as a normal batch
        row = [repo_name, author_name, created_at, total_conversations]
        for key in status_keys:
            row.append(batch_stats.get(key, 0))
        processed_repo_data.append(row)

        # Fetch and save PRs for this batch
        batch_id = batch.get("id")
        batch_name = batch.get("name", f"unknown_batch_{batch_id}")
        if not batch_id:
            print(f"Skipping PR fetch for batch '{batch_name}' due to missing ID.")
            continue
        
        print(f"\nProcessing batch: {batch_name} (ID: {batch_id})")
        conversations = fetch_conversations_for_batch(batch_id)
        if conversations:
            pr_ids = []
            for conv in conversations:
                pr_id = conv.get("seed", {}).get("metadata", {}).get("pr_id")
                if pr_id:
                    pr_ids.append([pr_id])
            
            if pr_ids:
                save_prs_to_csv(batch_name, pr_ids)
            else:
                print(f"  No PRs with a 'pr_id' found for batch {batch_name}.")

    if processed_repo_data:
        save_repo_summary_to_csv(processed_repo_data, repo_header)
    else:
        print("No repository summary data was processed.")


if __name__ == "__main__":
    main() 