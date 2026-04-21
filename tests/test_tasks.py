import pytest
from models.task import Task, TaskStore, TASK_STATUS_LABELS, PRIORITY_LABELS


class TestTask:
    def test_task_defaults(self):
        t = Task(title="test task")
        assert t.title == "test task"
        assert t.status == "pending"
        assert t.priority == "medium"
        assert len(t.id) == 8

    def test_task_id_unique(self):
        t1 = Task(title="a")
        t2 = Task(title="b")
        assert t1.id != t2.id


class TestTaskStore:
    def test_create_and_get(self):
        store = TaskStore()
        t = store.create(Task(title="build auth"))
        assert store.get(t.id).title == "build auth"

    def test_update(self):
        store = TaskStore()
        t = store.create(Task(title="build auth"))
        t.status = "in_progress"
        updated = store.update(t)
        assert store.get(t.id).status == "in_progress"
        assert updated.updated_at != updated.created_at

    def test_list_all_sorted(self):
        store = TaskStore()
        t1 = store.create(Task(title="first"))
        t2 = store.create(Task(title="second"))
        all_tasks = store.list_all()
        assert all_tasks == [t1, t2]

    def test_delete(self):
        store = TaskStore()
        t = store.create(Task(title="temp"))
        assert store.delete(t.id) is True
        assert store.get(t.id) is None
        assert store.delete(t.id) is False

    def test_labels(self):
        assert TASK_STATUS_LABELS["done"] == "✅ Done"
        assert PRIORITY_LABELS["critical"] == "🆘 Critical"
