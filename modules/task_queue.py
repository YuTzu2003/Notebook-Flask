import json
import logging
import time

from modules.db import execute_query


def enqueue_task(task_id, task_type, user_id, payload):
    sql = """INSERT INTO BackgroundTasks (TaskID, TaskType, UserID, Status, PayloadJson)
             VALUES (?, ?, ?, 'QUEUED', ?)"""
    return execute_query(sql, (task_id, task_type, user_id, json.dumps(payload, ensure_ascii=False)))


def get_active_task_ids(user_id):
    sql = """SELECT TaskID, TaskType FROM BackgroundTasks
             WHERE UserID = ? AND Status IN ('QUEUED', 'PROCESSING')"""
    tasks = execute_query(sql, (user_id,))
    return {
        "mapping": [task["TaskID"] for task in tasks if task["TaskType"] == "mapping"],
        "notes": [task["TaskID"] for task in tasks if task["TaskType"] == "migration"],
    }


def claim_next_task():
    sql = """;WITH next_task AS (
                    SELECT TOP 1 *
                    FROM BackgroundTasks WITH (UPDLOCK, READPAST, ROWLOCK)
                    WHERE Status = 'QUEUED'
                    ORDER BY CreatedAt, TaskID
                )
                UPDATE next_task
                SET Status = 'PROCESSING', StartedAt = SYSDATETIMEOFFSET(), Attempts = Attempts + 1
                OUTPUT inserted.TaskID, inserted.TaskType, inserted.PayloadJson"""
    tasks = execute_query(sql)
    return tasks[0] if tasks else None


def complete_task(task_id):
    return execute_query(
        "UPDATE BackgroundTasks SET Status = 'SUCCESS', FinishedAt = SYSDATETIMEOFFSET(), ErrorMessage = NULL WHERE TaskID = ?",
        (task_id,),
    )


def fail_task(task_id, error):
    return execute_query(
        "UPDATE BackgroundTasks SET Status = 'ERROR', FinishedAt = SYSDATETIMEOFFSET(), ErrorMessage = ? WHERE TaskID = ?",
        (str(error)[:4000], task_id),
    )


def recover_interrupted_tasks():
    return execute_query(
        "UPDATE BackgroundTasks SET Status = 'QUEUED', StartedAt = NULL WHERE Status = 'PROCESSING'"
    )


def run_worker(app, poll_seconds=2):
    recover_interrupted_tasks()
    logging.info("Background task worker started")
    while True:
        task = claim_next_task()
        if task is None:
            time.sleep(poll_seconds)
            continue

        try:
            payload = json.loads(task["PayloadJson"])
            if task["TaskType"] == "mapping":
                from service.bp_mapping import run_mapping_background

                success = run_mapping_background(app, **payload)
            elif task["TaskType"] == "migration":
                from service.bp_notes import run_migrate_background

                success = run_migrate_background(app, **payload)
            else:
                raise ValueError(f"Unsupported task type: {task['TaskType']}")

            if success:
                complete_task(task["TaskID"])
            else:
                fail_task(task["TaskID"], "PDF processing did not complete successfully")
        except Exception as error:
            logging.exception("Background task failed: %s", task["TaskID"])
            fail_task(task["TaskID"], error)


def main():
    from app import app

    run_worker(app)


if __name__ == "__main__":
    main()
