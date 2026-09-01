import json
import unittest
from unittest.mock import patch

from modules import task_queue


class TaskQueueTest(unittest.TestCase):
    @patch.object(task_queue, "execute_query", return_value=True)
    def test_enqueue_task_writes_a_queued_job(self, execute_query):
        task_queue.enqueue_task("map123", "mapping", "user-uuid", {"record_id": "map123"})

        sql, params = execute_query.call_args.args
        self.assertIn("BackgroundTasks", sql)
        self.assertEqual(params[:3], ("map123", "mapping", "user-uuid"))
        self.assertEqual(json.loads(params[3]), {"record_id": "map123"})

    @patch.object(
        task_queue,
        "execute_query",
        return_value=[
            {"TaskID": "map123", "TaskType": "mapping"},
            {"TaskID": "note456", "TaskType": "migration"},
        ],
    )
    def test_active_tasks_are_grouped_for_the_current_user(self, execute_query):
        tasks = task_queue.get_active_task_ids("user-uuid")

        self.assertEqual(tasks, {"mapping": ["map123"], "notes": ["note456"]})
        self.assertEqual(execute_query.call_args.args[1], ("user-uuid",))


if __name__ == "__main__":
    unittest.main()
