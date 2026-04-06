// Silent stub — prevents OTEL NodeSDK from starting in tests.
export const sdk = { start: () => {}, shutdown: async () => {} };
export const prometheusExporter = {};
