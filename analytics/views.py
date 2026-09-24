from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.utils import timezone
from django.views.generic import TemplateView

from . import stats
from .models import DailyCount

PERIODS = (7, 30, 90, 365)
DEFAULT_PERIOD = 30
# Above this many days the chart shows one bar per week instead of per day.
MAX_DAILY_BARS = 90


def _chart_bars(series: list[dict]) -> list[dict]:
    """Bucket the daily series into bars with heights relative to the peak."""
    if len(series) > MAX_DAILY_BARS:
        # Group into weeks ending today, so any partial week is the oldest bar
        # rather than a misleadingly short bar at the end.
        remainder = len(series) % 7
        head = [series[:remainder]] if remainder else []
        buckets = head + [series[i : i + 7] for i in range(remainder, len(series), 7)]
    else:
        buckets = [[day] for day in series]

    peak = max((sum(day["views"] for day in bucket) for bucket in buckets), default=0)
    bars = []
    for bucket in buckets:
        first, last = bucket[0]["date"], bucket[-1]["date"]
        if first == last:
            label = first.strftime("%a %d %b")
        else:
            label = f"{first.strftime('%d %b')} – {last.strftime('%d %b')}"
        views = sum(day["views"] for day in bucket)
        bars.append(
            {
                "label": label,
                "views": views,
                "visitors": sum(day["visitors"] for day in bucket),
                "height": round(views / peak * 100, 1) if peak else 0,
            }
        )
    return bars


class StatsDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    """Staff-only overview of the cookieless analytics counters."""

    template_name = "analytics/dashboard.html"

    def test_func(self):
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        try:
            days = int(self.request.GET.get("days", DEFAULT_PERIOD))
        except ValueError:
            days = DEFAULT_PERIOD
        if days not in PERIODS:
            days = DEFAULT_PERIOD

        start, end = stats.date_range(days, timezone.localdate())
        series = stats.daily_series(start, end)
        bars = _chart_bars(series)
        peak = max(bars, key=lambda bar: bar["views"], default=None)
        totals = stats.totals(start, end)

        ctx.update(
            {
                "days": days,
                "periods": PERIODS,
                "start": start,
                "end": end,
                "totals": totals,
                "avg_visitors": totals[DailyCount.VISITORS] / days,
                "bars": bars,
                "bar_gap": 2 if len(bars) <= 31 else 1,
                "peak": peak if peak and peak["views"] else None,
                "weekly_bars": len(series) > MAX_DAILY_BARS,
                "series": list(reversed(series)),
                "top_pages": stats.top_pages(start, end, limit=15),
                "top_referrers": stats.top_referrers(start, end),
                "top_searches": stats.top_searches(start, end),
                "top_filters": stats.top_filters(start, end),
                "top_calendar": stats.top_pages(
                    start, end, limit=10, kind=DailyCount.CALENDAR
                ),
            }
        )
        return ctx
