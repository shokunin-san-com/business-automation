"""
Google Analytics 4 Data API wrapper.

Uses service account authentication to fetch page-level metrics.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import GA_TRACKING_ID, CREDENTIALS_DIR, get_logger

logger = get_logger(__name__)

_client = None


def _get_client():
    """Get or create the GA4 BetaAnalyticsDataClient."""
    global _client
    if _client is not None:
        return _client

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        import os

        sa_path = CREDENTIALS_DIR / "service_account.json"
        if sa_path.exists():
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_path)

        _client = BetaAnalyticsDataClient()
        logger.info("GA4 client initialized")
        return _client
    except Exception as e:
        logger.error(f"Failed to initialize GA4 client: {e}")
        return None


def _extract_property_id() -> str:
    """Extract GA4 property ID from tracking ID or env.

    GA_TRACKING_ID is like G-XXXXXXXXXX. The numeric property ID
    must be set separately or looked up. For now, use an env var.
    """
    import os
    prop_id = os.getenv("GA4_PROPERTY_ID", "")
    if not prop_id:
        logger.warning(
            "GA4_PROPERTY_ID not set in .env. "
            "Set it to your GA4 property numeric ID (e.g., 123456789)"
        )
    return prop_id


def fetch_page_metrics(
    page_path: str,
    days: int = 7,
) -> dict | None:
    """Fetch metrics for a specific page path over the last N days.

    Returns dict with pageviews, sessions, bounce_rate, avg_time, conversions.
    """
    client = _get_client()
    if not client:
        return None

    property_id = _extract_property_id()
    if not property_id:
        return None

    from google.analytics.data_v1beta.types import (
        RunReportRequest,
        DateRange,
        Dimension,
        Metric,
        FilterExpression,
        Filter,
    )

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    try:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name="pagePath")],
            metrics=[
                Metric(name="screenPageViews"),
                Metric(name="sessions"),
                Metric(name="bounceRate"),
                Metric(name="averageSessionDuration"),
                Metric(name="conversions"),
            ],
            date_ranges=[
                DateRange(
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                )
            ],
            dimension_filter=FilterExpression(
                filter=Filter(
                    field_name="pagePath",
                    string_filter=Filter.StringFilter(
                        value=page_path,
                        match_type=Filter.StringFilter.MatchType.CONTAINS,
                    ),
                )
            ),
        )

        response = client.run_report(request)

        if not response.rows:
            logger.info(f"No GA4 data for {page_path}")
            return {
                "pageviews": 0,
                "sessions": 0,
                "bounce_rate": 0.0,
                "avg_time": 0.0,
                "conversions": 0,
            }

        row = response.rows[0]
        result = {
            "pageviews": int(row.metric_values[0].value),
            "sessions": int(row.metric_values[1].value),
            "bounce_rate": float(row.metric_values[2].value),
            "avg_time": float(row.metric_values[3].value),
            "conversions": int(row.metric_values[4].value),
        }
        logger.info(f"GA4 data for {page_path}: {result}")
        return result

    except Exception as e:
        logger.error(f"GA4 query failed for {page_path}: {e}")
        return None


def fetch_all_lp_metrics(days: int = 7) -> list[dict]:
    """Fetch metrics for all LP pages (/lp/ prefix)."""
    client = _get_client()
    if not client:
        return []

    property_id = _extract_property_id()
    if not property_id:
        return []

    from google.analytics.data_v1beta.types import (
        RunReportRequest,
        DateRange,
        Dimension,
        Metric,
        FilterExpression,
        Filter,
    )

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    try:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name="pagePath")],
            metrics=[
                Metric(name="screenPageViews"),
                Metric(name="sessions"),
                Metric(name="bounceRate"),
                Metric(name="averageSessionDuration"),
                Metric(name="conversions"),
            ],
            date_ranges=[
                DateRange(
                    start_date=start_date.strftime("%Y-%m-%d"),
                    end_date=end_date.strftime("%Y-%m-%d"),
                )
            ],
            dimension_filter=FilterExpression(
                filter=Filter(
                    field_name="pagePath",
                    string_filter=Filter.StringFilter(
                        value="/lp/",
                        match_type=Filter.StringFilter.MatchType.CONTAINS,
                    ),
                )
            ),
        )

        response = client.run_report(request)
        results = []

        for row in response.rows:
            page_path = row.dimension_values[0].value
            # Extract business_id from /lp/{business_id}
            parts = page_path.strip("/").split("/")
            business_id = parts[-1] if len(parts) >= 2 else page_path

            results.append({
                "business_id": business_id,
                "page_path": page_path,
                "pageviews": int(row.metric_values[0].value),
                "sessions": int(row.metric_values[1].value),
                "bounce_rate": float(row.metric_values[2].value),
                "avg_time": float(row.metric_values[3].value),
                "conversions": int(row.metric_values[4].value),
            })

        logger.info(f"Fetched GA4 data for {len(results)} LP pages")
        return results

    except Exception as e:
        logger.error(f"GA4 bulk query failed: {e}")
        return []
