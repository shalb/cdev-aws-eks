# cdev-aws-eks

Cdev uses [project templates](https://cluster.dev/stack-template-development/) to generate users' projects in a desired cloud. AWS-EKS is a cdev template that creates and provisions Kubernetes clusters in [AWS cloud](https://cluster.dev/aws-cloud-provider/) by means of Amazon Elastic Kubernetes Service (EKS). 

In this repository you will find all information and samples necessary to start an EKS cluster in AWS with cdev. 

The resources to be created:

* *(optional, if your use cluster.dev domain)* Route53 zone **<cluster-name>.cluster.dev** 
* *(optional, if vpc_id is not set)* VPC for EKS cluster
* EKS Kubernetes cluster with addons:
  * cert-manager
  * ingress-nginx
  * external-dns
  * argocd
* AWS IAM roles for EKS IRSA cert-manager and external-dns

## Prerequisites

1. Terraform version 13+
2. AWS account.
3. AWS CLI installed.
4. kubectl installed.
5. [Cdev installed](https://cluster.dev/getting-started/#cdev-install).

## Quick Start

1. [Configure access to AWS](https://cluster.dev/aws-cloud-provider/) and export required variables. 
2. Clone example project:
    ```
    git clone https://github.com/shalb/cdev-aws-eks.git
    cd examples/
    ```

3. Edit variables in the example's files, if necessary.
4. Run `cdev plan`
5. Run `cdev apply`

