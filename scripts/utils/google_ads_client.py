"""
Google Ads API wrapper — data retrieval, bid adjustment, budget monitoring.

Requires:
  - google-ads Python library (pip install google-ads)
  - .env: GOOGLE_ADS_CUSTOMER_ID, GOOGLE_ADS_DEVELOPER_TOKEN
  - credentials/google_ads.yaml (OAuth config)

Setup guide:
  1. Create a Google Ads Developer Token
  2. Create OAuth2 credentials for Google Ads API
  3. Set up google_ads.yaml in credentials/
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CREDENTIALS_DIR, get_logger
import os

logger = get_logger(__name__)

# Environment variables
CUSTOMER_ID = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "").replace("-", "")
DEVELOPER_TOKEN = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "")
ADS_YAML_PATH = CREDENTIALS_DIR / "google_ads.yaml"

# Safety limits
MAX_BID_ADJUSTMENT_PERCENT = 15  # ±15% max per adjustment
BUDGET_ALERT_THRESHOLD = 0.80   # Alert at 80% budget consumed


def _get_client():
    """Initialize and return Google Ads client."""
    try:
        from google.ads.googleads.client import GoogleAdsClient
        if not ADS_YAML_PATH.exists():
            logger.error(f"Google Ads config not found: {ADS_YAML_PATH}")
            return None
        return GoogleAdsClient.load_from_storage(str(ADS_YAML_PATH))
    except ImportError:
        logger.warning("google-ads library not installed. Run: pip install google-ads")
        return None
    except Exception as e:
        logger.error(f"Failed to init Google Ads client: {e}")
        return None


def fetch_campaign_metrics(days: int = 1) -> list[dict]:
    """Fetch campaign-level performance metrics.

    Returns list of {campaign_id, campaign_name, impressions, clicks,
    cost, conversions, ctr, cpc, cpa}.
    """
    client = _get_client()
    if not client:
        return []

    ga_service = client.get_service("GoogleAdsService")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    query = f"""
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign_budget.amount_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.average_cpc,
            metrics.ctr
        FROM campaign
        WHERE segments.date BETWEEN '{start_date.strftime("%Y-%m-%d")}'
            AND '{end_date.strftime("%Y-%m-%d")}'
            AND campaign.status = 'ENABLED'
        ORDER BY metrics.cost_micros DESC
    """

    try:
        response = ga_service.search(customer_id=CUSTOMER_ID, query=query)
        results = []
        for row in response:
            cost = row.metrics.cost_micros / 1_000_000
            clicks = row.metrics.clicks
            conversions = row.metrics.conversions
            results.append({
                "campaign_id": str(row.campaign.id),
                "campaign_name": row.campaign.name,
                "impressions": row.metrics.impressions,
                "clicks": clicks,
                "cost": round(cost, 2),
                "conversions": round(conversions, 2),
                "ctr": round(row.metrics.ctr * 100, 2),
                "cpc": round(row.metrics.average_cpc / 1_000_000, 2),
                "cpa": round(cost / conversions, 2) if conversions > 0 else 0,
                "budget_micros": row.campaign_budget.amount_micros,
            })

        logger.info(f"Fetched metrics for {len(results)} campaigns")
        return results
    except Exception as e:
        logger.error(f"Failed to fetch campaign metrics: {e}")
        return []


def fetch_keyword_metrics(campaign_id: str, days: int = 7) -> list[dict]:
    """Fetch keyword-level performance for a campaign."""
    client = _get_client()
    if not client:
        return []

    ga_service = client.get_service("GoogleAdsService")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    query = f"""
        SELECT
            ad_group_criterion.keyword.text,
            ad_group_criterion.keyword.match_type,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.average_cpc
        FROM keyword_view
        WHERE campaign.id = {campaign_id}
            AND segments.date BETWEEN '{start_date.strftime("%Y-%m-%d")}'
                AND '{end_date.strftime("%Y-%m-%d")}'
        ORDER BY metrics.cost_micros DESC
        LIMIT 50
    """

    try:
        response = ga_service.search(customer_id=CUSTOMER_ID, query=query)
        results = []
        for row in response:
            results.append({
                "keyword": row.ad_group_criterion.keyword.text,
                "match_type": row.ad_group_criterion.keyword.match_type.name,
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "cost": round(row.metrics.cost_micros / 1_000_000, 2),
                "conversions": round(row.metrics.conversions, 2),
                "cpc": round(row.metrics.average_cpc / 1_000_000, 2),
            })
        return results
    except Exception as e:
        logger.error(f"Failed to fetch keyword metrics: {e}")
        return []


def adjust_bid(
    campaign_id: str,
    ad_group_id: str,
    criterion_id: str,
    adjustment_percent: float,
) -> bool:
    """Adjust bid for a keyword by a percentage.

    Safety: Clamped to ±MAX_BID_ADJUSTMENT_PERCENT.
    """
    # Safety clamp
    clamped = max(-MAX_BID_ADJUSTMENT_PERCENT, min(MAX_BID_ADJUSTMENT_PERCENT, adjustment_percent))
    if clamped != adjustment_percent:
        logger.warning(f"Bid adjustment clamped: {adjustment_percent}% → {clamped}%")

    client = _get_client()
    if not client:
        return False

    try:
        ad_group_criterion_service = client.get_service("AdGroupCriterionService")

        resource_name = ad_group_criterion_service.ad_group_criterion_path(
            CUSTOMER_ID, ad_group_id, criterion_id
        )

        # Get current bid
        ga_service = client.get_service("GoogleAdsService")
        query = f"""
            SELECT ad_group_criterion.cpc_bid_micros
            FROM ad_group_criterion
            WHERE ad_group_criterion.resource_name = '{resource_name}'
        """
        response = ga_service.search(customer_id=CUSTOMER_ID, query=query)
        current_bid = None
        for row in response:
            current_bid = row.ad_group_criterion.cpc_bid_micros
            break

        if current_bid is None:
            logger.error("Could not find current bid")
            return False

        new_bid = int(current_bid * (1 + clamped / 100))

        # Update bid
        operation = client.get_type("AdGroupCriterionOperation")
        criterion = operation.update
        criterion.resource_name = resource_name
        criterion.cpc_bid_micros = new_bid

        client.copy_from(
            operation.update_mask,
            client.get_type("FieldMask")(paths=["cpc_bid_micros"]),
        )

        ad_group_criterion_service.mutate_ad_group_criteria(
            customer_id=CUSTOMER_ID,
            operations=[operation],
        )

        logger.info(
            f"Bid adjusted: {resource_name} "
            f"{current_bid/1_000_000:.2f}¥ → {new_bid/1_000_000:.2f}¥ ({clamped:+.1f}%)"
        )
        return True
    except Exception as e:
        logger.error(f"Bid adjustment failed: {e}")
        return False


def check_budget_status() -> list[dict]:
    """Check budget consumption for all active campaigns.

    Returns list of campaigns exceeding alert threshold.
    """
    client = _get_client()
    if not client:
        return []

    ga_service = client.get_service("GoogleAdsService")
    today = datetime.now().strftime("%Y-%m-%d")

    query = f"""
        SELECT
            campaign.id,
            campaign.name,
            campaign_budget.amount_micros,
            metrics.cost_micros
        FROM campaign
        WHERE segments.date = '{today}'
            AND campaign.status = 'ENABLED'
    """

    try:
        response = ga_service.search(customer_id=CUSTOMER_ID, query=query)
        alerts = []
        for row in response:
            budget = row.campaign_budget.amount_micros / 1_000_000
            spent = row.metrics.cost_micros / 1_000_000
            if budget > 0:
                ratio = spent / budget
                if ratio >= BUDGET_ALERT_THRESHOLD:
                    alerts.append({
                        "campaign_id": str(row.campaign.id),
                        "campaign_name": row.campaign.name,
                        "budget": round(budget, 0),
                        "spent": round(spent, 0),
                        "ratio": round(ratio * 100, 1),
                    })

        if alerts:
            logger.warning(f"Budget alerts for {len(alerts)} campaigns")
        return alerts
    except Exception as e:
        logger.error(f"Budget check failed: {e}")
        return []


def pause_campaign(campaign_id: str) -> bool:
    """Emergency pause a campaign."""
    client = _get_client()
    if not client:
        return False

    try:
        campaign_service = client.get_service("CampaignService")
        resource_name = campaign_service.campaign_path(CUSTOMER_ID, campaign_id)

        operation = client.get_type("CampaignOperation")
        campaign = operation.update
        campaign.resource_name = resource_name
        campaign.status = client.enums.CampaignStatusEnum.PAUSED

        client.copy_from(
            operation.update_mask,
            client.get_type("FieldMask")(paths=["status"]),
        )

        campaign_service.mutate_campaigns(
            customer_id=CUSTOMER_ID,
            operations=[operation],
        )

        logger.info(f"Campaign paused: {campaign_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to pause campaign: {e}")
        return False
