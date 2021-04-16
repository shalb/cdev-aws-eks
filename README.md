# cdev-aws-eks

Template to Deploy EKS with Cluster.dev

Components that would be created:

```bash
+----------------------------+
|        WILL BE DEPLOYED    |
+----------------------------+
| vpc route53                |
| subnets_tagging            |
| iam_policy_route53         |
| eks                        |
| iam_assumable_role_route53 |
| eks_auth                   |
| cert-manager               |
| ingress-nginx              |
| cert-manager-issuer        |
| argocd                     |
| argocd_apps                |
+----------------------------+
```
