from diagrams import Diagram, Cluster
from diagrams.aws.compute import EKS
from diagrams.aws.network import Route53, VPC
from diagrams.programming.language import Bash
from diagrams.programming.flowchart import Document

with Diagram("AWS EKS Cluster", show=False, direction="TB"):
    route53 = Route53("route53\ntfmodule")
    vpc = VPC("vpc\ntfmodule")

    with Cluster("EKS Cluster"):
        eks = EKS("eks\ntfmodule")
        eks_addons = EKS("eks-addons\ntfmodule")
        kubeconfig = Bash("kubeconfig\nshell")

    outputs = Document("outputs\nprinter")

    # Connections
    route53 >> vpc
    vpc >> eks
    eks >> eks_addons
    eks_addons >> kubeconfig
    kubeconfig >> outputs

    # Dependencies based on remoteState
    eks - vpc
    eks_addons - eks
    eks_addons - vpc
    eks_addons - route53
