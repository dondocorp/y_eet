resource "helm_release" "grafana" {
  name             = "grafana"
  namespace        = "monitoring"
  create_namespace = false
  repository       = "https://grafana.github.io/helm-charts"
  chart            = "grafana"
  version          = var.grafana_version

  values = [
    yamlencode({
      replicas = 2

      adminPassword = var.admin_password

      persistence = {
        enabled = true
        size    = "10Gi"
      }

      resources = {
        requests = { cpu = "100m", memory = "256Mi" }
        limits   = { cpu = "500m", memory = "512Mi" }
      }

      grafana_ini = {
        server = {
          root_url     = "https://grafana.${var.domain}"
          serve_from_sub_path = false
        }
        auth = {
          disable_login_form = false
        }
        "auth.generic_oauth" = {
          enabled       = true
          name          = "SSO"
          allow_sign_up = true
          client_id     = var.oauth_client_id
          client_secret = var.oauth_client_secret
          scopes        = "openid email profile"
          auth_url      = var.oauth_auth_url
          token_url     = var.oauth_token_url
          api_url       = var.oauth_api_url
          role_attribute_path = "contains(groups[*], 'platform-sre') && 'Admin' || contains(groups[*], 'service-owners') && 'Editor' || 'Viewer'"
        }
        users = {
          default_theme = "dark"
        }
        alerting = {
          enabled = false  # use Grafana unified alerting
        }
        "unified_alerting" = {
          enabled = true
        }
        analytics = {
          reporting_enabled = false
          check_for_updates = false
        }
      }

      # Provision datasources and dashboards from ConfigMaps
      sidecar = {
        datasources = {
          enabled            = true
          searchNamespace    = "ALL"
          label              = "grafana_datasource"
        }
        dashboards = {
          enabled            = true
          searchNamespace    = "ALL"
          label              = "grafana_dashboard"
          folderAnnotation   = "grafana_folder"
          provider = {
            foldersFromFilesStructure = true
          }
        }
      }

      # Inline datasource provisioning
      datasources = {
        "datasources.yaml" = {
          apiVersion = 1
          datasources = [
            {
              name      = "Prometheus"
              uid       = "prometheus"
              type      = "prometheus"
              url       = "http://thanos-query.monitoring.svc.cluster.local:9090"
              isDefault = true
              access    = "proxy"
              jsonData = {
                httpMethod            = "POST"
                prometheusType        = "Thanos"
                prometheusVersion     = "0.34.0"
                incrementalQuerying   = true
                exemplarTraceIdDestinations = [{
                  name           = "trace_id"
                  datasourceUid  = "tempo"
                }]
              }
            },
            {
              name   = "Loki"
              uid    = "loki"
              type   = "loki"
              url    = "http://loki-gateway.monitoring.svc.cluster.local"
              access = "proxy"
              jsonData = {
                maxLines = 5000
                derivedFields = [{
                  matcherRegex    = "\"trace_id\":\"([a-f0-9]{32})\""
                  name            = "TraceID"
                  url             = "$${__value.raw}"
                  datasourceUid   = "tempo"
                  urlDisplayLabel = "View Trace"
                }]
              }
            },
            {
              name   = "Tempo"
              uid    = "tempo"
              type   = "tempo"
              url    = "http://tempo-query-frontend.monitoring.svc.cluster.local:3200"
              access = "proxy"
              jsonData = {
                tracesToLogsV2 = {
                  datasourceUid        = "loki"
                  filterByTraceID      = true
                  filterBySpanID       = false
                }
                serviceMap = { datasourceUid = "prometheus" }
                nodeGraph  = { enabled = true }
                lokiSearch = { datasourceUid = "loki" }
              }
            }
          ]
        }
      }

      ingress = {
        enabled = true
        annotations = {
          "kubernetes.io/ingress.class"               = "alb"
          "alb.ingress.kubernetes.io/scheme"          = "internet-facing"
          "alb.ingress.kubernetes.io/target-type"     = "ip"
          "alb.ingress.kubernetes.io/certificate-arn" = var.acm_cert_arn
          "alb.ingress.kubernetes.io/listen-ports"    = "[{\"HTTPS\":443}]"
        }
        hosts = ["grafana.${var.domain}"]
        tls   = [{ hosts = ["grafana.${var.domain}"] }]
      }
    })
  ]
}

variable "grafana_version" { default = "7.3.11" }
variable "environment"     {}
variable "admin_password"  { sensitive = true }
variable "domain"          { default = "y_eet.internal" }
variable "oauth_client_id"     { default = "" }
variable "oauth_client_secret" { sensitive = true; default = "" }
variable "oauth_auth_url"      { default = "" }
variable "oauth_token_url"     { default = "" }
variable "oauth_api_url"       { default = "" }
variable "acm_cert_arn"        { default = "" }
