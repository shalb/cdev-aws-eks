from nacl import public
import base64
import requests
import time
import io
import zipfile

def create_branch(repo, new_branch_name, base_branch, token):
    url = f"https://api.github.com/repos/{repo}/git/refs/heads/{base_branch}"
    headers = {"Authorization": f"token {token}"}
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed to get base branch ref. Response: {r.text}")
        return False, r.json()

    ref_sha = r.json().get("object").get("sha")
    data = {
        "ref": f"refs/heads/{new_branch_name}",
        "sha": ref_sha
    }
    url = f"https://api.github.com/repos/{repo}/git/refs"
    r = requests.post(url, json=data, headers=headers)
    success = r.status_code in [200, 201]
    return success, r.json() if not success else None

def push_multiple_files_to_github(files, repo, branch, token):
    base_url = f"https://api.github.com/repos/{repo}"
    headers = {"Authorization": f"token {token}"}

    # Step 1: Get the latest commit SHA of the branch
    r = requests.get(f"{base_url}/git/ref/heads/{branch}", headers=headers)
    if r.status_code != 200:
        return False, r.json()
    latest_commit_sha = r.json()["object"]["sha"]

    # Step 2: Get the tree SHA of the latest commit
    r = requests.get(f"{base_url}/git/commits/{latest_commit_sha}", headers=headers)
    if r.status_code != 200:
        return False, r.json()
    base_tree_sha = r.json()["tree"]["sha"]

    # Step 3: Create a new tree object
    tree_data = []
    for filename, content in files.items():
        tree_data.append({"path": filename, "mode": "100644", "type": "blob", "content": content})

    tree_payload = {
        "base_tree": base_tree_sha,
        "tree": tree_data
    }
    r = requests.post(f"{base_url}/git/trees", json=tree_payload, headers=headers)
    if r.status_code != 201:
        return False, r.json()
    new_tree_sha = r.json()["sha"]

    # Step 4: Create a new commit object
    commit_payload = {
        "message": "Cluster.dev push configuration",
        "tree": new_tree_sha,
        "parents": [latest_commit_sha]
    }
    r = requests.post(f"{base_url}/git/commits", json=commit_payload, headers=headers)
    if r.status_code != 201:
        return False, r.json()
    new_commit_sha = r.json()["sha"]

    # Step 5: Update the reference
    ref_payload = {
        "sha": new_commit_sha
    }
    r = requests.patch(f"{base_url}/git/refs/heads/{branch}", json=ref_payload, headers=headers)
    success = r.status_code in [200, 201]
    # Return both the success status and the response content (if not successful)
    return success, r.json() if not success else None

def create_pull_request(repo, new_branch_name, base_branch, token):
    url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {"Authorization": f"token {token}"}
    data = {
        "title": f"Add/update files from {new_branch_name}",
        "head": new_branch_name,
        "base": base_branch
    }
    r = requests.post(url, json=data, headers=headers)
    if r.status_code != 201:
        print(f"Failed to create pull request. Response: {r.text}")
        return None
    return r.json().get("html_url")

def create_or_update_github_secret(repo_name, secret_name, secret_value, token):
    # Get the public key
    url = f"https://api.github.com/repos/{repo_name}/actions/secrets/public-key"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        error_message = f"Failed to get public key. GitHub says: {response.json().get('message', 'Unknown error')}"
        print(error_message)
        return False, error_message

    public_key = response.json()['key']
    key_id = response.json()['key_id']

    # Encrypt the secret using the public key
    public_key_bytes = base64.b64decode(public_key)
    sealed_box = public.SealedBox(public.PublicKey(public_key_bytes))
    encrypted_value = base64.b64encode(sealed_box.encrypt(secret_value.encode())).decode()

    # Create or update the secret
    url = f"https://api.github.com/repos/{repo_name}/actions/secrets/{secret_name}"
    data = {"encrypted_value": encrypted_value, "key_id": key_id}
    response = requests.put(url, json=data, headers=headers)

    if response.status_code not in [201, 204]:
        error_message = f"Failed to create/update secret. GitHub says: {response.json().get('message', 'Unknown error')}"
        print(error_message)
        return False, error_message

    print(f"Secret {secret_name} successfully created/updated.")
    return True, None

def get_workflow_status(repo, token, branch_name, timeout=1500, callback=None):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    end_time = time.time() + timeout
    job_statuses = []  # Initialize as an empty list

    while time.time() < end_time:
        # Get the workflow runs for the repository
        url = f"https://api.github.com/repos/{repo}/actions/runs"
        response = requests.get(url, headers=headers)
        response_data = response.json()

        # Find the workflow run for the given branch
        for run in response_data.get('workflow_runs', []):
            if run['head_branch'] == branch_name:
                if run['status'] == 'completed':
                    # Fetch the jobs for this workflow run
                    jobs_url = run['jobs_url']
                    jobs_response = requests.get(jobs_url, headers=headers)

                    for job in jobs_response.json().get('jobs', []):
                        job_statuses.append({
                            'name': job['name'],
                            'status': job['conclusion'],
                            'url': job['html_url']
                        })
                    return job_statuses  # Return the list of dictionaries
                break

        # Invoke the callback if provided
        if callback:
            elapsed_time = time.time() - (end_time - timeout)
            progress = elapsed_time / timeout
            callback(progress)

        # Sleep for a while before polling again
        time.sleep(10)

    return job_statuses  # Return the list of dictionaries

def merge_pr(repo, pr_number, token):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/merge"

    response = requests.put(url, headers=headers)

    if response.status_code == 200:
        # Fetch the merged commit SHA
        merge_commit_sha = response.json().get('sha')
        return True, "PR merged successfully!", merge_commit_sha
    else:
        return False, f"Failed to merge PR. GitHub says: {response.json()['message']}", None

def get_run_id_for_commit(repo, token, commit_sha, workflow_name, timeout=60):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    url = f"https://api.github.com/repos/{repo}/commits/{commit_sha}/check-runs"

    end_time = time.time() + timeout
    while time.time() < end_time:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            print(f"Unsuccessful request. Status code: {response.status_code}. Response: {response.json()}")
            time.sleep(5)  # Wait for 5 seconds before polling again
            continue

        check_runs = response.json().get('check_runs', [])
        if check_runs:
            for run in check_runs:
                if "apply" in run['name'].lower():
                    print(f"Successful request. Check runs: {check_runs}")
                    return run
            # If no matching run found, sleep for a short duration before polling again
            time.sleep(5)
        else:
            print("Successful request but no check runs found yet.")
            time.sleep(5)

    return None

def fetch_run_logs(repo, run_id, token):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    logs_url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/logs"

    response = requests.get(logs_url, headers=headers, stream=True)

    if response.status_code == 200:
        content_type = response.headers.get('content-type')
        if 'zip' in content_type:
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                with z.open('apply/4_Run_ClusterDev_Apply.txt') as f:
                    return f.read().decode('utf-8')
        else:
            return response.text
    else:
        return None