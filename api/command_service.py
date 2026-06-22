from typing import Any, Dict, List, Optional

from loguru import logger
from surreal_commands import get_command_status, submit_command


class CommandService:
    """Generic service layer for command operations"""

    @staticmethod
    async def submit_command_job(
        module_name: str,  # Actually app_name for surreal-commands
        command_name: str,
        command_args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Submit a generic command job for background processing"""
        try:
            # Ensure command modules are imported before submitting
            # This is needed because submit_command validates against local registry
            try:
                import commands.podcast_commands  # noqa: F401
            except ImportError as import_err:
                logger.error(f"Failed to import command modules: {import_err}")
                raise ValueError("Command modules not available")

            # surreal-commands expects: submit_command(app_name, command_name, args)
            cmd_id = submit_command(
                module_name,  # This is actually the app name (e.g., "open_notebook")
                command_name,  # Command name (e.g., "process_text")
                command_args,  # Input data
            )
            # Convert RecordID to string if needed
            if not cmd_id:
                raise ValueError("Failed to get cmd_id from submit_command")
            cmd_id_str = str(cmd_id)
            logger.info(
                f"Submitted command job: {cmd_id_str} for {module_name}.{command_name}"
            )
            return cmd_id_str

        except Exception as e:
            logger.error(f"Failed to submit command job: {e}")
            raise

    @staticmethod
    async def get_command_status(job_id: str) -> Dict[str, Any]:
        """Get status of any command job"""
        try:
            status = await get_command_status(job_id)
            return {
                "job_id": job_id,
                "status": status.status if status else "unknown",
                "result": status.result if status else None,
                "error_message": getattr(status, "error_message", None)
                if status
                else None,
                "created": str(status.created)
                if status and hasattr(status, "created") and status.created
                else None,
                "updated": str(status.updated)
                if status and hasattr(status, "updated") and status.updated
                else None,
                "progress": getattr(status, "progress", None) if status else None,
            }
        except Exception as e:
            logger.error(f"Failed to get command status: {e}")
            raise

    @staticmethod
    async def list_command_jobs(
        module_filter: Optional[str] = None,
        command_filter: Optional[str] = None,
        status_filter: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List command jobs with optional filtering, newest first."""
        from open_notebook.database.repository import repo_query

        conditions: List[str] = []
        params: Dict[str, Any] = {"limit": limit}

        if module_filter:
            conditions.append("app = $app")
            params["app"] = module_filter
        if command_filter:
            conditions.append("name = $name")
            params["name"] = command_filter
        if status_filter:
            conditions.append("status = $status")
            params["status"] = status_filter

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = (
            f"SELECT id, app, name, status, error_message, created, updated "
            f"FROM command {where} ORDER BY created DESC LIMIT $limit"
        )

        rows = await repo_query(query, params)
        return [
            {
                "job_id": str(r["id"]),
                "app": r.get("app"),
                "command": r.get("name"),
                "status": r.get("status"),
                "error_message": r.get("error_message"),
                "created": str(r["created"]) if r.get("created") else None,
                "updated": str(r["updated"]) if r.get("updated") else None,
            }
            for r in rows
        ]

    @staticmethod
    async def cancel_command_job(job_id: str) -> bool:
        """
        Cancel a queued or running command job.

        Returns True if the job was moved to 'canceled'.
        Returns False if the job is already in a terminal state
        (completed / failed / canceled).

        Note: marking a *running* job as canceled prevents retries but does not
        interrupt the in-progress worker task — the worker may still write a
        final status when it finishes.
        """
        from open_notebook.database.repository import ensure_record_id, repo_query, repo_update

        try:
            record_id = ensure_record_id(job_id)
            records = await repo_query(
                "SELECT status FROM $id", {"id": record_id}
            )
            if not records:
                raise ValueError(f"Command {job_id} not found")

            current_status = records[0].get("status")
            if current_status in ("completed", "failed", "canceled"):
                logger.info(
                    f"Job {job_id} already in terminal state '{current_status}'; nothing to cancel"
                )
                return False

            await repo_update(record_id, {"status": "canceled"})
            logger.info(f"Canceled job {job_id} (was '{current_status}')")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel command job: {e}")
            raise
