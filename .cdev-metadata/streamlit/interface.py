import streamlit as st
import yaml
import uuid
import re
from github_utils import create_branch, push_multiple_files_to_github, create_pull_request, create_or_update_github_secret, get_workflow_status, merge_pr, get_run_id_for_commit,fetch_run_logs

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
    st.subheader("Configuration for EKS")

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
name: Cluster.dev for {project_name}

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
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    container: clusterdev/cluster.dev:v0.7.18
    steps:
    - name: Check out code
      uses: actions/checkout@v3

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
      uses: actions/checkout@v3

    - name: Run ClusterDev Apply
      run: |
        cd .cluster.dev/{project_name}
        cdev plan --force
      env:
        AWS_ACCESS_KEY_ID: ${{{{ secrets.AWS_ACCESS_KEY_ID }}}}
        AWS_SECRET_ACCESS_KEY: ${{{{ secrets.AWS_SECRET_ACCESS_KEY }}}}
        AWS_DEFAULT_REGION: {region}
    """

    return workflow_yaml

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

# Generate GitHub workflow file to push to repo
workflow_file_content = generate_workflow_file(project_yaml_content)

st.subheader("Repository and Cloud Access")
# Inputs for GitHub repository and token
repo = st.text_input("GitHub Repository (e.g., username/repo_name):","voatsap/eks-test")
token = st.text_input("GitHub Token:", type="password", help="https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token")

# Inputs for AWS credentials to be saved to GitHub
aws_access_key_id = st.text_input("AWS Access Key ID:",help="You can save it directly to GitHub Repo Action Secrets and skip this step. The documentation on how to obtain credentials is here: https://docs.aws.amazon.com/keyspaces/latest/devguide/access.credentials.html")
aws_secret_access_key = st.text_input("AWS Secret Access Key:", type="password")

if st.button('Save AWS Secrets to GitHub'):
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

# Check if 'pr_merged' and 'latest_run_url' are initialized in session state
if 'pr_merged' not in st.session_state:
    st.session_state.pr_merged = False
if 'latest_run_url' not in st.session_state:
    st.session_state.latest_run_url = ''
if 'latest_run_id' not in st.session_state:
    st.session_state.latest_run_id = ''
# If PR is merged, display the action triggered message

# Function to be executed on "Merge PR" click
def merge_and_fetch_latest_run(repo, pr_id, token):
    success, message, merge_commit_sha = merge_pr(repo, pr_id, token)
    if success:
        st.session_state.pr_merged = True
        st.success(message)
        # Fetch the GitHub Action run triggered by the PR merge using the commit SHA
        latest_run = get_run_id_for_commit(repo, token, merge_commit_sha, "Cluster.dev")
        if latest_run:
            st.session_state.latest_run_url = latest_run['html_url']
            st.session_state.latest_run_id = re.search(r'/runs/(\d+)/job', latest_run['html_url']).group(1)
        else:
            st.warning("Unable to fetch the latest GitHub Action run.")
    else:
        st.error(message)

if st.session_state.pr_merged and st.session_state.latest_run_url:
    st.success(f"EKS bootstaping triggered: [View Action]({st.session_state.latest_run_url})")
    logs = fetch_run_logs(repo, st.session_state.latest_run_id, token)
    if logs:
        st.text_area("Logs:", value=logs, height=400)
    else:
        st.error("Failed to fetch logs.")
else:
    # Add a button in Streamlit to trigger the push
    if st.button('Push Configuration to GitHub'):
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
                        st.success(f"Files pushed successfully! [Check Pull Request]({pr_url})")

                        # Create a progress bar in Streamlit
                        progress_bar = st.progress(0,text="Executing Workflow")

                        # Define a callback to update the progress bar
                        def update_progress(progress):
                            progress_bar.progress(progress)

                        job_statuses = get_workflow_status(repo, token, new_branch_name, timeout=60, callback=update_progress)
                        # Check the workflow status with the callback
                        if job_statuses:
                            all_successful = all(job['status'] in ['success', 'skipped'] for job in job_statuses)
                        else:
                            st.warning("No job statuses returned.")
                            exit
                        # Clear the progress bar once done
                        progress_bar.empty()
                        # Display the workflow status
                        if all_successful:
                            for job in job_statuses:
                                if job['name'] == 'plan':
                                    st.success(f"All checks have passed for [Plan job]({job['url']})! Now you can review the plan and merge the PR to bootstrap the cluster.")
                            # If PR is not yet merged, show the button
                            if not st.session_state.pr_merged:
                                merge_button = st.button(
                                    "Merge PR",
                                    on_click=merge_and_fetch_latest_run,
                                    args=(repo, pr_url.split('/')[-1], token)
                                )
                        else:
                            for job in job_statuses:
                                if job['status'] == 'failure':
                                    st.error(f"Check failed for [job {job['name']}]({job['url']}).")
                else:
                    if push_error_response and "message" in push_error_response:
                        st.error(f"Failed to push files. GitHub says: {push_error_response['message']}")
                    else:
                        st.error("Failed to push files.")
        else:
            st.warning("Please provide both repository and token.")


