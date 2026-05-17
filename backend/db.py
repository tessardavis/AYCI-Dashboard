"""
Shared MongoDB handle.

Single source of truth for the motor client + database. Both server.py
and any module under /app/backend/routes/ import `db` from here.
"""
from __future__ import annotations

import os

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

mongo_url = os.environ["MONGO_URL"]
# Explicitly use the certifi CA bundle. On macOS, Python from python.org doesn't
# trust system roots out of the box, so motor's TLS handshake to Atlas fails with
# "certificate verify failed". This makes it work locally and is harmless in
# production (where the system bundle would also work).
client = AsyncIOMotorClient(mongo_url, tlsCAFile=certifi.where())
db = client[os.environ["DB_NAME"]]
