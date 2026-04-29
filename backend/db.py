"""
Shared MongoDB handle.

Single source of truth for the motor client + database. Both server.py
and any module under /app/backend/routes/ import `db` from here.
"""
from __future__ import annotations

import os

from motor.motor_asyncio import AsyncIOMotorClient

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]
