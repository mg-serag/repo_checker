import diskcache
import requests
import csv
import datetime


LT_TOKEN = "YOUR_LT_TOKEN"


def get_improper():
    project_id = 41
    url = f"https://eval.turing.com/api/conversations?limit=5000&page=1&join[0]=project%7C%7Cid,name,status,projectType,supportsFunctionCalling,supportsWorkflows,supportsMultipleFilesPerTask,jibbleActivity,instructionsLink,readonly,averageHandleTimeMinutes&join[1]=batch%7C%7Cid,name,status,projectId,jibbleActivity,maxClaimGoldenTaskAllowed,averageHandleTimeMinutes&join[2]=currentUser%7C%7Cid,name,turingEmail,profilePicture,isBlocked&join[3]=currentUser.teamLead%7C%7Cid,name,turingEmail,profilePicture,isBlocked&join[4]=seed%7C%7Cmetadata,turingMetadata&join[5]=labels%7C%7Cid,labelId&join[6]=labels.label&join[7]=latestLabelingWorkflow&join[8]=latestLabelingWorkflow.workflow%7C%7Cstatus,createdAt,currentWorkflowStatus&join[9]=latestLabelingWorkflow.workflow.currentCollaborator%7C%7Cid&join[10]=latestLabelingWorkflow.workflow.currentCollaborator.collaborator%7C%7Cid,name,turingEmail,profilePicture,isBlocked&join[11]=latestLabelingWorkflow.workflow.collaborators%7C%7Crole&join[12]=latestLabelingWorkflow.workflow.collaborators.collaborator%7C%7Cid,name,turingEmail,profilePicture,isBlocked&join[13]=latestLabelingWorkflow.workflow.collaborators.collaborator.teamLead%7C%7Cid,name,turingEmail,profilePicture,isBlocked&join[14]=statusHistory%7C%7Cid,conversationId,oldStatus,newStatus,formStage,updatedAt,createdAt&filter[0]=status%7C%7C$eq%7C%7Cimproper&filter[1]=batch.status%7C%7C$ne%7C%7Cdraft&filter[2]=projectId%7C%7C$eq%7C%7C{project_id}&filter[3]=batch.status%7C%7C$ne%7C%7Cdraft"
    response = requests.get(url, headers={"Authorization": f"Bearer {LT_TOKEN}"})
    return response.json()

def get_task_history(task_id):
    with diskcache.FanoutCache("cache") as cache:
        task_history = cache.get(f"task_history_{task_id}")
        if task_history:
            return task_history
        else:
            url = f"https://eval.turing.com/api/conversations/{task_id}/history"
            response = requests.get(url, headers={"Authorization": f"Bearer {LT_TOKEN}"})
            task_history = response.json()
            cache.set(f"task_history_{task_id}", task_history)
            return task_history

def save_to_csv(data, filename="improper_tasks.csv"):
    """Saves a list of lists to a CSV file with a header."""
    header = ["Task ID", "Trainer", "Improper By", "Date", "Notes"]
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(data)


def main():
    improper = get_improper()
    tasks_to_save = []

    if not improper.get("data"):
        print("No improper tasks found.")
        return

    for task in improper["data"]:
        print("#" * 100, task["id"], "##")
        task_history = get_task_history(task["id"])

        if not isinstance(task_history, list):
            print(f"Skipping task {task['id']} due to invalid history format.")
            continue

        last_in_progress = next(
            (h for h in task_history if isinstance(h, dict) and h.get("newStatus") == "labeling"), None
        )
        if last_in_progress:
            trainer = last_in_progress.get("author", {}).get("name", "Not Found")
        else:
            trainer = "Not Claimed"

        last_improper = next(
            (h for h in task_history if isinstance(h, dict) and h.get("newStatus") == "improper"), None
        )

        if last_improper:
            improper_by = last_improper.get("author", {}).get("name", "Not Found")
            try:
                date = datetime.datetime.fromisoformat(
                    last_improper.get("createdAt", "")
                ).strftime("%Y/%m/%d")
            except (ValueError, TypeError):
                date = "Invalid Date"
            notes = last_improper.get("notes", "")
        else:
            improper_by = "Unknown"
            date = "Unknown"
            notes = ""

        tasks_to_save.append([task["id"], trainer, improper_by, date, notes])

    output_filename = "improper_tasks.csv"
    save_to_csv(tasks_to_save, output_filename)
    print(f"Saved {len(tasks_to_save)} tasks to {output_filename}")

    with diskcache.FanoutCache("cache") as cache:
        cache.clear()
    print("Cache cleared.")


if __name__ == "__main__":
    main()