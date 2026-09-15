"""Unit tests for Sales/TS agent filtering (no live Bitrix)."""

from app.bitrix.agents import list_sales_ts_agents


class FakeClient:
    def __init__(self, departments, users):
        self._departments = departments
        self._users = users

    def call(self, method, params=None):
        if method == "department.get":
            return self._departments
        raise AssertionError(method)

    def call_list(self, method, params=None):
        if method == "user.get":
            return self._users
        raise AssertionError(method)


def test_list_sales_ts_agents_filters_by_dept():
    client = FakeClient(
        departments=[
            {"ID": "60", "NAME": "Sales Department"},
            {"ID": "28", "NAME": "Marketing"},
            {"ID": "41", "NAME": "Re-Sale"},
        ],
        users=[
            {
                "ID": "10",
                "NAME": "Sales",
                "LAST_NAME": "Agent",
                "EMAIL": "s@a.com",
                "UF_DEPARTMENT": [60],
            },
            {
                "ID": "11",
                "NAME": "Market",
                "LAST_NAME": "Only",
                "EMAIL": "m@a.com",
                "UF_DEPARTMENT": [28],
            },
            {
                "ID": "12",
                "NAME": "TS",
                "LAST_NAME": "Desk",
                "EMAIL": "t@a.com",
                "UF_DEPARTMENT": ["41"],
            },
        ],
    )
    agents = list_sales_ts_agents(client, [60, 41])
    ids = {a.id for a in agents}
    assert ids == {10, 12}
    assert agents[0].name  # sorted by name
    names = {a.name for a in agents}
    assert "Market Only" not in names


def test_empty_dept_list():
    client = FakeClient(departments=[], users=[{"ID": "1", "NAME": "A", "UF_DEPARTMENT": [60]}])
    assert list_sales_ts_agents(client, []) == []
