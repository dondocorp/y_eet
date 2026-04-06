/**
 * OTEL SDK must be initialized before any other imports.
 * This file is imported first in server.ts.
 */
import { NodeSDK } from '@opentelemetry/sdk-node';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-grpc';
import { PrometheusExporter } from '@opentelemetry/exporter-prometheus';
import { Resource } from '@opentelemetry/resources';
import { SEMRESATTRS_SERVICE_NAME, SEMRESATTRS_SERVICE_VERSION } from '@opentelemetry/semantic-conventions';
import { config } from '../config';

const resource = new Resource({
  [SEMRESATTRS_SERVICE_NAME]: config.SERVICE_NAME,
  [SEMRESATTRS_SERVICE_VERSION]: config.SERVICE_VERSION,
  'deployment.environment': config.NODE_ENV,
});

const traceExporter = new OTLPTraceExporter({
  url: config.OTEL_EXPORTER_OTLP_ENDPOINT,
});

// Prometheus exporter runs on its own port — started independently to avoid
// SDK version conflicts between @opentelemetry/exporter-prometheus and sdk-node
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
      '@opentelemetry/instrumentation-http': { enabled: true },
      '@opentelemetry/instrumentation-pg': { enabled: true },
    }),
  ],
});

sdk.start();

process.on('SIGTERM', async () => {
  await sdk.shutdown();
});

export { sdk };
