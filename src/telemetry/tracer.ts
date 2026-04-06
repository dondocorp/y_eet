/**
 * OTEL SDK must be initialized before any other imports.
 * This file is imported first in server.ts.
 */
import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-grpc';
import { PrometheusExporter } from '@opentelemetry/exporter-prometheus';
import { Resource } from '@opentelemetry/resources';
import {
  SEMRESATTRS_SERVICE_NAME,
  SEMRESATTRS_SERVICE_VERSION,
  SEMRESATTRS_DEPLOYMENT_ENVIRONMENT,
  SEMRESATTRS_K8S_CLUSTER_NAME,
  SEMRESATTRS_K8S_NAMESPACE_NAME,
  SEMRESATTRS_K8S_POD_NAME,
  SEMRESATTRS_K8S_NODE_NAME,
} from '@opentelemetry/semantic-conventions';
import { config } from '../config';

const resource = new Resource({
  [SEMRESATTRS_SERVICE_NAME]: config.SERVICE_NAME,
  [SEMRESATTRS_SERVICE_VERSION]: config.SERVICE_VERSION,
  [SEMRESATTRS_DEPLOYMENT_ENVIRONMENT]: config.NODE_ENV,
  // K8s attributes populated at runtime via Downward API env vars
  [SEMRESATTRS_K8S_CLUSTER_NAME]: process.env.K8S_CLUSTER_NAME ?? 'local',
  [SEMRESATTRS_K8S_NAMESPACE_NAME]: process.env.K8S_NAMESPACE ?? 'local',
  [SEMRESATTRS_K8S_POD_NAME]: process.env.K8S_POD_NAME ?? 'local',
  [SEMRESATTRS_K8S_NODE_NAME]: process.env.K8S_NODE_NAME ?? 'local',
  'platform.region': process.env.AWS_REGION ?? 'local',
});

const traceExporter = new OTLPTraceExporter({
  url: config.OTEL_EXPORTER_OTLP_ENDPOINT,
});

// Prometheus exporter for local scraping by the OTEL Collector DaemonSet.
// Runs on a dedicated port so it doesn't conflict with the app port.
export const prometheusExporter = new PrometheusExporter({
  port: config.PROMETHEUS_PORT,
  endpoint: '/metrics',
});

const sdk = new NodeSDK({
  resource,
  traceExporter,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metricReader: prometheusExporter as any,
  instrumentations: [
    getNodeAutoInstrumentations({
      '@opentelemetry/instrumentation-fs': { enabled: false },
      '@opentelemetry/instrumentation-http': {
        enabled: true,
        // Suppress noisy internal paths from creating spans
        ignoreIncomingRequestHook(req) {
          const url = req.url ?? '';
          return (
            url === '/health/live' ||
            url === '/health/ready' ||
            url === '/health/startup' ||
            url === '/metrics'
          );
        },
      },
      '@opentelemetry/instrumentation-pg': {
        enabled: true,
        enhancedDatabaseReporting: true,
      },
    }),
  ],
});

sdk.start();

process.on('SIGTERM', async () => {
  await sdk.shutdown();
});

export { sdk };
