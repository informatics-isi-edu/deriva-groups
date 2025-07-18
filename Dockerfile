FROM python:3.13-slim AS core

# For compose healthchecks
RUN apt-get update && apt-get install -y curl && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /deriva-groups

# Copy Python dependencies and install
COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools build \
 && pip install --no-cache-dir gunicorn .

# Copy backend code
COPY deriva ./deriva

# Environment configuration
ENV PYTHONPATH=/deriva
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8999", "deriva.web.groups.wsgi:application"]


# Stage 2: Full image with rsyslog
FROM core AS full

# Install rsyslog
RUN apt-get update && apt-get install -y \
    rsyslog libsystemd0 --no-install-recommends \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# Add rsyslog configuration
COPY config/rsyslog.conf /etc/rsyslog.conf

COPY bin/docker-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8999", "deriva.web.groups.wsgi:application"]