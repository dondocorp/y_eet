resource "helm_release" "kube_prometheus_stack" {
  name             = "kube-prometheus-stack"
  namespace        = "monitoring"
  create_namespace = true
  repository       = "https://prometheus-community.github.io/helm-charts"
  chart            = "kube-prometheus-stack"
  version          = var.chart_version

  values = [
    yamlencode({
      prometheus = {
        prometheusSpec = {
          retention           = "2d"          # short local; Thanos handles long-term
          retentionSize       = "20GB"
          storageSpec = {
            volumeClaimTemplate = {
              spec = {
                resources = { requests = { storage = "30Gi" } }
              }
            }
          }
          # Thanos sidecar for remote storage
          thanos = {
            objectStorageConfig = {
              existingSecret = {
                name = "thanos-objstore-secret"
                key  = "objstore.yml"
              }
            }
          }
          externalLabels = {
            cluster     = var.cluster_name
            environment = var.environment
          }
          # Pick up all PrometheusRule CRDs in any namespace
          ruleNamespaceSelector = {}
          ruleSelector          = {}
          # Pick up ServiceMonitors in any namespace
          serviceMonitorNamespaceSelector = {}
          serviceMonitorSelector          = {}
          # Pick up PodMonitors in any namespace
          podMonitorNamespaceSelector = {}
          podMonitorSelector          = {}
          additionalScrapeConfigsSecret = {
            enabled = true
            name    = "additional-scrape-configs"
            key     = "additional-scrape-configs.yaml"
          }
          resources = {
            requests = { cpu = "200m", memory = "1Gi" }
            limits   = { cpu = "1000m", memory = "3Gi" }
          }
        }
      }
      alertmanager = {
        alertmanagerSpec = {
          replicas = 3
          storage = {
            volumeClaimTemplate = {
              spec = {
                resources = { requests = { storage = "5Gi" } }
              }
            }
          }
        }
        config = var.alertmanager_config
      }
      grafana = {
        enabled = false    # deployed via separate module
      }
    })
  ]
}

# Thanos Query (federates across Prometheus + S3 historical data)
resource "helm_release" "thanos" {
  name       = "thanos"
  namespace  = "monitoring"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "thanos"
  version    = var.thanos_chart_version

  values = [
    yamlencode({
      query = {
        enabled = true
        replicaCount = 2
        stores = [
          "dnssrv+_grpc._tcp.kube-prometheus-stack-thanos-discovery.monitoring.svc.cluster.local"
        ]
      }
      storegateway = {
        enabled = true
        persistence = {
          size = "20Gi"
        }
        objectStorageConfig = {
          existingSecret = {
            name = "thanos-objstore-secret"
            key  = "objstore.yml"
          }
        }
      }
      compactor = {
        enabled = true
        retentionResolutionRaw = "30d"
        retentionResolution5m  = "90d"
        retentionResolution1h  = "365d"
        objectStorageConfig = {
          existingSecret = {
            name = "thanos-objstore-secret"
            key  = "objstore.yml"
          }
        }
      }
    })
  ]
}

# Secret: Thanos object store config
resource "kubernetes_secret" "thanos_objstore" {
  metadata {
    name      = "thanos-objstore-secret"
    namespace = "monitoring"
  }
  data = {
    "objstore.yml" = yamlencode({
      type = "S3"
      config = {
        bucket   = var.thanos_s3_bucket
        endpoint = "s3.amazonaws.com"
        region   = var.aws_region
        # auth via IRSA — no credentials needed
      }
    })
  }
}

variable "chart_version"        { default = "58.7.2" }
variable "thanos_chart_version" { default = "15.6.0" }
variable "cluster_name"         { default = "eks-prod-us-east-1" }
variable "environment"          {}
variable "aws_region"           { default = "us-east-1" }
variable "thanos_s3_bucket"     {}
variable "alertmanager_config"  {}
