# ── Dev stage — hot-reload with ts-node-dev ───────────────────────────────────
FROM node:20-alpine AS dev
WORKDIR /app
COPY package*.json ./
RUN npm ci
# src is volume-mounted at runtime — not copied here
EXPOSE 8080 9464
CMD ["npm", "run", "dev"]

# ── Builder stage — compile TypeScript ────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# ── Production stage ──────────────────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY package*.json ./
RUN npm ci --omit=dev
COPY --from=builder /app/dist ./dist
EXPOSE 8080 9464
USER node
CMD ["node", "dist/server.js"]
