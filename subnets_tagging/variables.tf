variable "private_subnets" {
  default = []
  type = list
  description = "list of private subnets IDs for tagging for ingress NLB"
}

variable "public_subnets" {
  default = []
  type = list
  description = "list of public subnets IDs for tagging for ingress NLB"
}

variable "cluster_name" {
  type = string
  description = "k8s cluster name for tagging"
}