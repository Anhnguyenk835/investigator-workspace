# The gateway with its routes baked in, for hosts that cannot mount a file (Railway).
# Local development and Cloud Run keep using the stock image with config.yaml mounted.
FROM ghcr.io/berriai/litellm-database:v1.99.0
COPY config.yaml /app/config/config.yaml
CMD ["--config", "/app/config/config.yaml", "--host", "0.0.0.0", "--port", "4000", "--telemetry", "False"]
