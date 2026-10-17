FROM ghcr.io/sagernet/sing-box:v1.14.3@sha256:80c639ba467885b28511fb7c980565c2d30a8752f778e7bc8abdbc91fbfd95ec AS core
FROM python:3.12-alpine
RUN apk add --no-cache curl ca-certificates && addgroup -g 1000 probe && adduser -D -u 1000 -G probe probe
COPY --from=core /usr/local/bin/sing-box /usr/local/bin/sing-box
COPY probe.py /app/probe.py
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python3", "/app/probe.py"]
