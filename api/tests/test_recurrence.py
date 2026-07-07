from datetime import date

from life_dashboard.domains.todos.service import _next_due_date


def test_daily_advances_one_day():
    rule = {"frequency": "daily", "interval": 1}
    assert _next_due_date(date(2026, 1, 1), rule) == date(2026, 1, 2)


def test_weekly_interval_two_weeks():
    result = _next_due_date(
        date(2026, 1, 1), {"frequency": "weekly", "interval": 2, "days_of_week": [3]}
    )
    assert (result - date(2026, 1, 1)).days % 7 == 0


def test_monthly_date_clamps_may31_to_june30():
    assert _next_due_date(date(2026, 5, 31), {"frequency": "monthly_date", "interval": 1}) == date(
        2026, 6, 30
    )


def test_yearly_leap_day_feb29_to_mar1():
    rule = {"frequency": "yearly", "interval": 1}
    assert _next_due_date(date(2024, 2, 29), rule) == date(2025, 3, 1)
