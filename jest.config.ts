import type { Config } from 'jest';

const config: Config = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.test.ts'],
  setupFiles: ['<rootDir>/tests/setup.ts'],

  collectCoverageFrom: [
    'src/**/*.ts',
    '!src/server.ts',
    '!src/db/migrate.ts',
    '!src/db/pool.ts',        // requires real postgres — integration-test territory
    '!src/telemetry/tracer.ts',
    '!src/types/**',
    // Repositories are thin SQL wrappers that require a live DB to test properly.
    // They are covered by integration tests; exclude from unit-test thresholds.
    '!src/repositories/BetRepository.ts',
    '!src/repositories/ConfigRepository.ts',
    '!src/repositories/GameSessionRepository.ts',
    '!src/repositories/IdempotencyRepository.ts',
    '!src/repositories/RiskRepository.ts',
    '!src/repositories/UserRepository.ts',
  ],
  coverageDirectory: 'coverage',
  coverageReporters: ['text', 'lcov', 'html', 'json-summary', 'json'],
  coverageThreshold: {
    global: {
      branches: 65,
      functions: 75,
      lines: 75,
      statements: 75,
    },
  },

  // Remap telemetry imports to silent mocks so OTEL SDK never initialises in tests
  moduleNameMapper: {
    '^.*/telemetry/metrics$': '<rootDir>/tests/mocks/metrics.ts',
    '^.*/telemetry/tracer$':  '<rootDir>/tests/mocks/tracer.ts',
  },

  transform: {
    '^.+\\.ts$': ['ts-jest', { tsconfig: { strict: false } }],
  },

  clearMocks: true,
  restoreMocks: true,
};

export default config;
