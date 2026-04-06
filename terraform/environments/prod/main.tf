terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.13"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.27"
    }
  }
  backend "s3" {
    bucket         = "y_eet-terraform-state-prod"
    key            = "observability/prod/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "y_eet-terraform-locks"
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Environment = "prod"
      ManagedBy   = "terraform"
      Team        = "platform"
      Project     = "y_eet-observability"
    }
  }
}

data "aws_eks_cluster" "main" {
  name = var.eks_cluster_name
}

data "aws_eks_cluster_auth" "main" {
  name = var.eks_cluster_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.main.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.main.certificate_authority[0].data)
  token                  = data.aws_eks_cluster_auth.main.token
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.main.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.main.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.main.token
  }
}

# ── S3 buckets for observability backends ─────────────────────────────────────
module "observability_storage" {
  source      = "../../modules/observability-storage"
  environment = var.environment
  aws_region  = var.aws_region
}

# ── Prometheus + Thanos ───────────────────────────────────────────────────────
module "prometheus" {
  source              = "../../modules/prometheus"
  environment         = var.environment
  thanos_s3_bucket    = module.observability_storage.thanos_bucket_id
  alertmanager_config = file("${path.module}/../../alertmanager/alertmanager.yaml")
  depends_on          = [module.observability_storage]
}

# ── Loki ──────────────────────────────────────────────────────────────────────
module "loki" {
  source       = "../../modules/loki"
  environment  = var.environment
  s3_bucket_id = module.observability_storage.loki_bucket_id
  aws_region   = var.aws_region
  depends_on   = [module.observability_storage]
}

# ── Tempo ─────────────────────────────────────────────────────────────────────
module "tempo" {
  source       = "../../modules/tempo"
  environment  = var.environment
  s3_bucket_id = module.observability_storage.tempo_bucket_id
  aws_region   = var.aws_region
  depends_on   = [module.observability_storage]
}

# ── Grafana ───────────────────────────────────────────────────────────────────
module "grafana" {
  source          = "../../modules/grafana"
  environment     = var.environment
  grafana_version = var.grafana_version
  admin_password  = var.grafana_admin_password   # from AWS Secrets Manager
  depends_on      = [module.prometheus, module.loki, module.tempo]
}

# ── OTEL Collector ────────────────────────────────────────────────────────────
module "otel_collector" {
  source      = "../../modules/otel-collector"
  environment = var.environment
  depends_on  = [module.prometheus, module.loki, module.tempo]
}

# ── CloudWatch exporter ───────────────────────────────────────────────────────
module "cloudwatch_exporter" {
  source         = "../../modules/cloudwatch-exporter"
  environment    = var.environment
  aws_region     = var.aws_region
  eks_oidc_url   = data.aws_eks_cluster.main.identity[0].oidc[0].issuer
  depends_on     = [module.prometheus]
}

# ── Istio observability config (K8s CRDs) ─────────────────────────────────────
module "istio_observability" {
  source      = "../../modules/istio-observability"
  environment = var.environment
}

# ── Fluent Bit log shipper ────────────────────────────────────────────────────
module "fluent_bit" {
  source       = "../../modules/fluent-bit"
  environment  = var.environment
  loki_url     = module.loki.gateway_url
  depends_on   = [module.loki]
}
