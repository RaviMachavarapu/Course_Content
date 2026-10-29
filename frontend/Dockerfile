# syntax=docker/dockerfile:1

# ---- build ----
FROM node:20.20.2-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
# Lockfile only: drift between package.json and package-lock.json fails the build.
RUN npm ci
COPY . .
RUN npm run build

# ---- serve ----
FROM nginx:1.27.5-alpine AS serve
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
