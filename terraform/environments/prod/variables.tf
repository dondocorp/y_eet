variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment"
  type        = string
  default     = "prod"
}

variable "eks_cluster_name" {
  description = "EKS cluster name"
  type        = string
}

variable "grafana_version" {
  description = "Grafana Helm chart version"
  type        = string
  default     = "7.3.11"
}

variable "grafana_admin_password" {
  description = "Grafana admin password — sourced from AWS Secrets Manager in CI"
  type        = string
  sensitive   = true
}
