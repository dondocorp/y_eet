/**
 * Structured logger that injects OTEL trace context into every log record.
 * Import this instead of using fastify.log directly for service-layer logs.
 */
import pino from 'pino';
import { context, trace, isSpanContextValid } from '@opentelemetry/api';
import { config } from '../config';

function getTraceContext(): { trace_id?: string; span_id?: string } {
  const span = trace.getSpan(context.active());
  if (!span) return {};
  const ctx = span.spanContext();
  if (!isSpanContextValid(ctx)) return {};
  return {
    trace_id: ctx.traceId,
    span_id: ctx.spanId,
  };
}

const baseLogger = pino({
  level: config.LOG_LEVEL,
  formatters: {
    level(label) {
      return { level: label };
    },
  },
  timestamp: pino.stdTimeFunctions.isoTime,
  mixin() {
    return {
      service: config.SERVICE_NAME,
      version: config.SERVICE_VERSION,
      environment: config.NODE_ENV,
      ...getTraceContext(),
    };
  },
});

export const logger = baseLogger;

export function childLogger(bindings: Record<string, unknown>) {
  return baseLogger.child(bindings);
}
