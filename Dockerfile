FROM python:3.13-slim

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

EXPOSE 8999

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8999", "deriva.web.groups.wsgi:application"]
