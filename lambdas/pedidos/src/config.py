"""Config — env vars only (no AppConfig, no SSM). This Lambda is in a different VPC."""

import os

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
# SQLSERVER_CONNECTION_STRING is read by shared/db.py
