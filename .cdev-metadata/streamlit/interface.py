import streamlit as st
import yaml
import base64
import requests
import uuid
from nacl import public


def generate_project_yaml():

    regions = [
        "us-east-1", "us-east-2", "us-west-1", "us-west-2",
        "af-south-1", "ap-east-1", "ap-south-1", "ap-northeast-1",
        "ap-northeast-2", "ap-northeast-3", "ap-southeast-1", "ap-southeast-2",
        "ca-central-1", "eu-central-1", "eu-west-1", "eu-west-2",
        "eu-west-3", "eu-north-1", "eu-south-1", "me-south-1",
        "sa-east-1"
    ]

    project_yaml = {
        "name":  st.text_input("Name", "my-project"),
        "kind": "Project",
        "backend": "aws-backend",
        "variables": {
            "organization": st.text_input("Organization", "my-company"),
            "region": st.selectbox("Region", regions, index=regions.index("eu-central-1")),
            "state_bucket_name": st.text_input("State Bucket Name", "cdev-state"),
        },
    }
    return yaml.dump(project_yaml)

def generate_backend_yaml(project_yaml):
    project_yaml = yaml.safe_load(project_yaml)

    backend_yaml = {
        "name": "aws-backend",
        "kind": "Backend",
        "provider": "s3",
        "spec": {
            "bucket": project_yaml["variables"]["state_bucket_name"],
            "region": project_yaml["variables"]["region"],
        }
    }
    return yaml.dump(backend_yaml)

def generate_stack_eks_yaml(project_yaml):

    project = yaml.safe_load(project_yaml)

    create_vpc = st.checkbox("Create VPC", value=True)

    vpc_config = None
    if not create_vpc:
        vpc_id = st.text_input("VPC ID")
        public_subnets = st.text_area("Public Subnets (comma-separated)").split(",")
        private_subnets = st.text_area("Private Subnets (comma-separated)").split(",")
        database_subnets = st.text_area("Database Subnets (comma-separated)").split(",")
        vpc_config = {
            "vpc_id": vpc_id,
            "public_subnets": public_subnets,
            "private_subnets": private_subnets,
            "database_subnets": database_subnets,
        }

    cluster_name = st.text_input("Cluster Name", "demo")
    domain = st.text_input("Domain Name", "cluster.dev")

    eks_version = st.selectbox("EKS Version", ["1.27", "1.26", "1.25"])
    instance_types = st.multiselect(
        "Instance Types",
        [
            "t3.xlarge", "t3a.xlarge", "m5.xlarge", "m5n.xlarge",
            "t3.medium", "t3.large", "m6i.large", "m5.large",
            "m5n.large", "t3a.medium", "t3a.large", "m6a.large",
            "m5a.large"
        ],
        default=["t3.xlarge", "m5.xlarge"]
    )
    min_size = st.slider("Min Size", min_value=1, max_value=10, value=2)
    max_size = st.slider("Max Size", min_value=min_size, max_value=10, value=3)

    stack_eks_yaml = {
        "name": "cluster",
        "template": "https://github.com/shalb/cdev-aws-eks?ref=main",
        "kind": "Stack",
        "backend": "aws-backend",
        "cliVersion": ">= 0.7.14",
        "variables": {
            "region": project["variables"]["region"],
            "organization": project["variables"]["organization"],
            "cluster_name": cluster_name,
            "domain": domain,
            "eks_version": eks_version,
            "environment": "demo-env",
            "eks_managed_node_groups": {
                "workers": {
                    "capacity_type": "SPOT",
                    "desired_size": 2,
                    "disk_size": 80,
                    "force_update_version": True,
                    "instance_types": instance_types,
                    "labels": {},
                    "max_size": max_size,
                    "min_size": min_size,
                    "name": "spot-workers",
                    "subnet_ids": '{{ remoteState "cluster.vpc.private_subnets" }}',
                    "taints": [],
                    "update_config": {
                        "max_unavailable": 1
                    },
                    "iam_role_additional_policies": {
                        "ebspolicy": "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
                    },
                }
            },
        }
    }
    eks_addons_list = [
        ("ArgoCD", True),
        ("NGINX", True),
        ("External Secrets", True),
        ("Cluster Autoscaler", True),
        ("AWS LB Controller", True),
        ("External DNS", True),
        ("Cert Manager", True),
        ("EFS", False),
        ("Cert Manager HTTP Issuers", False),
        ("Metrics Server", True),
        ("Reloader", True)
    ]
    eks_addons_options = {f"enable_{name.lower().replace(' ', '_')}": state for name, state in eks_addons_list}

    selected_addons = st.multiselect(
        "Select EKS Addons",
        options=[name for name, _ in eks_addons_list],
        default=[name for name, state in eks_addons_list if state]
    )
    eks_addons = {f"enable_{name.lower().replace(' ', '_')}": (name in selected_addons) for name, _ in eks_addons_list}
    stack_eks_yaml["variables"]["eks_addons"] = eks_addons

    if not create_vpc:
        stack_eks_yaml["variables"].update(vpc_config)

    return yaml.dump(stack_eks_yaml)

def generate_workflow_file(project_yaml):
    # Assuming the project name is part of the project YAML
    project_yaml = yaml.safe_load(project_yaml)
    project_name = project_yaml['name']
    region = project_yaml['variables']['region']
    state_bucket_name =  project_yaml["variables"]["state_bucket_name"]
    workflow_yaml = f"""
name: ClusterDev Plan for {project_name}

on:
  push:
    branches:
      - 'cluster.dev-*'
      - main
    paths:
      - '.cluster.dev/{project_name}/**'
  pull_request:
    branches:
      - main
    paths:
      - '.cluster.dev/{project_name}/**'

jobs:
  plan:
    runs-on: ubuntu-latest
    container: clusterdev/cluster.dev:v0.7.18
    steps:
    - name: Check out code
      uses: actions/checkout@v2

    - name: Run ClusterDev Plan
      run: |
        cd .cluster.dev/{project_name}
        aws s3 mb s3://{state_bucket_name} || true
        cdev plan
      env:
        AWS_ACCESS_KEY_ID: ${{{{ secrets.AWS_ACCESS_KEY_ID }}}}
        AWS_SECRET_ACCESS_KEY: ${{{{ secrets.AWS_SECRET_ACCESS_KEY }}}}
        AWS_DEFAULT_REGION: {region}
  apply:
    if: github.event_name == 'push' && contains(github.ref, 'refs/heads/main')  # Runs only on push to main branch
    runs-on: ubuntu-latest
    container: clusterdev/cluster.dev:v0.7.18
    steps:
    - name: Check out code
      uses: actions/checkout@v2

    - name: Run ClusterDev Apply
      run: |
        cd .cluster.dev/{project_name}
        cdev apply --force
      env:
        AWS_ACCESS_KEY_ID: ${{{{ secrets.AWS_ACCESS_KEY_ID }}}}
        AWS_SECRET_ACCESS_KEY: ${{{{ secrets.AWS_SECRET_ACCESS_KEY }}}}
        AWS_DEFAULT_REGION: {region}
    """

    return workflow_yaml

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
        "message": "Add/update multiple files",
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

st.set_page_config(page_title="Cluster.dev AWS-EKS Configuration")
st.title("Cluster.dev AWS-EKS Configuration")

project_yaml_content = generate_project_yaml()
st.subheader("Project YAML")
st.code(project_yaml_content, language="yaml")

backend_yaml_content = generate_backend_yaml(project_yaml_content)
st.subheader("Backend YAML")
st.code(backend_yaml_content, language="yaml")

stack_eks_yaml_content = generate_stack_eks_yaml(project_yaml_content)
st.subheader("Stack EKS YAML")
st.code(stack_eks_yaml_content, language="yaml")

# Inputs for GitHub repository and token
repo = st.text_input("GitHub Repository (e.g., username/repo_name):","voatsap/eks-test")
token = st.text_input("GitHub Token:", type="password", help="https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token")

# Inputs for AWS credentials to be saved to GitHub
aws_access_key_id = st.text_input("AWS Access Key ID:",help="https://docs.aws.amazon.com/keyspaces/latest/devguide/access.credentials.html")
aws_secret_access_key = st.text_input("AWS Secret Access Key:", type="password")

if st.button('Save AWS Secrets'):
    if aws_access_key_id and aws_secret_access_key:
        success1, error_message1 = create_or_update_github_secret(repo, "AWS_ACCESS_KEY_ID", aws_access_key_id, token)
        success2, error_message2 = create_or_update_github_secret(repo, "AWS_SECRET_ACCESS_KEY", aws_secret_access_key, token)
        if success1 and success2:
            st.success("AWS secrets saved successfully!")
        else:
            error_messages = [msg for msg in [error_message1, error_message2] if msg]
            for msg in error_messages:
                st.error(msg)
    else:
        st.warning("Please provide both AWS Access Key ID and Secret Access Key.")

workflow_file_content = generate_workflow_file(project_yaml_content)

# Add a button in Streamlit to trigger the push
if st.button('Push to GitHub'):
    if repo and token:
        base_branch = "main"
        new_branch_name = f"cluster.dev-{uuid.uuid4().hex[:8]}"
        project = yaml.safe_load(project_yaml_content)
        subdirectory = ".cluster.dev/"+project["name"]
        workflow_path = ".github/workflows/clusterdev-"+project["name"]+".yaml"

        files_to_commit = {
            f"{subdirectory}/project.yaml": project_yaml_content,
            f"{subdirectory}/backend.yaml": backend_yaml_content,
            f"{subdirectory}/stack_eks.yaml": stack_eks_yaml_content,
            workflow_path: workflow_file_content
        }

        # Create a new branch
        branch_success, branch_error_response = create_branch(repo, new_branch_name, base_branch, token)
        if not branch_success:
            if branch_error_response and "message" in branch_error_response:
                st.error(f"Failed to create branch. GitHub says: {branch_error_response['message']}")
            else:
                st.error("Failed to create branch.")
        else:
            # Push the files to the new branch
            push_success, push_error_response = push_multiple_files_to_github(files_to_commit, repo, new_branch_name, token)

            if push_success:
                # Create a pull request
                pr_url = create_pull_request(repo, new_branch_name, base_branch, token)
                if pr_url:
                    st.success(f"Files pushed successfully! [View Pull Request]({pr_url})")
            else:
                if push_error_response and "message" in push_error_response:
                    st.error(f"Failed to push files. GitHub says: {push_error_response['message']}")
                else:
                    st.error("Failed to push files.")
    else:
        st.warning("Please provide both repository and token.")


