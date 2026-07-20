"""
Seed the 15 userN@teste.com test accounts (user1..user15) in SurrealDB with a
shared bcrypt-hashed password, so they can log in via /auth/login/local.

These pair with the matching userN@teste.com entries in users.json (m10006..
m10020), which carry the navy ACL profile (departments/clearance_level) used
by open_notebook/access_control.py. This script only creates the DB-side
login credentials; it does not touch users.json.

Usage:
    python -m scripts.seed_test_users [--password PASSWORD] [--count 15]
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger

from open_notebook.domain.user import User

DEFAULT_PASSWORD = "123456"


async def seed_test_users(count: int, password: str) -> None:
    for i in range(1, count + 1):
        email = f"user{i}@teste.com"
        existing = await User.get_by_email(email)
        if existing:
            logger.info(f"Test user already exists: {email} — updating password hash")
            existing.set_password(password)
            await existing.save()
        else:
            user = User(
                email=email,
                name=f"Test User {i}",
                roles=["user"],
                provider="local",
                is_active=True,
            )
            user.set_password(password)
            await user.save()
            logger.info(f"Test user created: {email}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed userN@teste.com test accounts")
    parser.add_argument("--count", type=int, default=15, help="Number of test users (default: 15)")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Shared password for all test users")
    args = parser.parse_args()

    asyncio.run(seed_test_users(args.count, args.password))
    logger.info(f"Done. All test users share password: {args.password}")


if __name__ == "__main__":
    main()
