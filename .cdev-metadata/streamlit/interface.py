import streamlit as st
import yaml
import base64
import requests


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
        "name": "dev",
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

    eks_version = st.selectbox("EKS Version", ["1.26", "1.25", "1.24"])
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
        "template": "../",
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
    if not create_vpc:
        stack_eks_yaml["variables"].update(vpc_config)

    return yaml.dump(stack_eks_yaml)

def push_to_github(content, filename, repo, branch, token):
    url = f"https://api.github.com/repos/{repo}/contents/{filename}"

    # Get the file SHA if it exists
    headers = {"Authorization": f"token {token}"}
    r = requests.get(url, headers=headers)
    sha = None
    if r.status_code == 200:
        sha = r.json().get("sha")

    # Prepare the data
    content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    data = {
        "message": f"Add/update {filename}",
        "content": content_base64,
        "branch": branch
    }
    if sha:
        data["sha"] = sha

    # Push the file
    r = requests.put(url, json=data, headers=headers)
    if r.status_code != 200:
        print(f"Failed to push {filename}. Status Code: {r.status_code}. Response: {r.text}")
        return False
    return True


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
repo = st.text_input("GitHub Repository (e.g., username/repo_name):")
token = st.text_input("GitHub Token:", type="password")

# Add a button in Streamlit to trigger the push
if st.button('Push to GitHub') and repo and token:
    # Replace the branch with your value or make it an input
    branch = "main"

    # Push the files
    if (push_to_github(project_yaml_content, "project.yaml", repo, branch, token) and
        push_to_github(backend_yaml_content, "backend.yaml", repo, branch, token) and
        push_to_github(stack_eks_yaml_content, "stack_eks.yaml", repo, branch, token)):
        st.success("Files pushed successfully!")
    else:
        st.error("Failed to push files.")
else:
    st.warning("Please provide both repository and token.")