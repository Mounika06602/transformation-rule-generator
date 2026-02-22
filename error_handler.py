# error_handler.py
import logging
from typing import Optional
from datetime import datetime
import asyncpg

class ErrorHandler:
    def __init__(self, db_pool: asyncpg.Pool):
        self.db_pool = db_pool
        self.logger = logging.getLogger(__name__)

    async def log_error(self, workflow_id: int, error_type: str, log_message: str) -> None:
        """Log an error to the database"""
        try:
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO error_logs (workflow_id, error_type, log_message, timestamp) VALUES ($1, $2, $3, $4)",
                    workflow_id,
                    error_type,
                    log_message,
                    datetime.now()
                )
            self.logger.info(f"Logged error for workflow {workflow_id}: {error_type}")
        except Exception as e:
            self.logger.error(f"Failed to log error to database: {str(e)}")

    async def get_recent_errors(self, workflow_id: int, limit: int = 10) -> list:
        """Get recent errors for a workflow"""
        try:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT log_id, error_type, log_message, timestamp FROM error_logs WHERE workflow_id = $1 ORDER BY timestamp DESC LIMIT $2",
                    workflow_id,
                    limit
                )
                return [dict(row) for row in rows]
        except Exception as e:
            self.logger.error(f"Failed to fetch errors from database: {str(e)}")
            return []

    async def clear_old_logs(self, days_old: int = 30) -> int:
        """Clear logs older than specified days and return count of deleted logs"""
        try:
            async with self.db_pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM error_logs WHERE timestamp < NOW() - INTERVAL '$1 days'",
                    days_old
                )
                # Extract the number of deleted rows from the result string
                if "DELETE" in result:
                    deleted_count = int(result.split()[-1])
                    self.logger.info(f"Cleared {deleted_count} old error logs")
                    return deleted_count
                return 0
        except Exception as e:
            self.logger.error(f"Failed to clear old logs: {str(e)}")
            return 0