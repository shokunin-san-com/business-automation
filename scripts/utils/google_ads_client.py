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
MAX_DAILY_BUDGET = 5000         # Max daily budget in yen for auto-created campaigns
MAX_KEYWORDS_PER_GROUP = 20     # Max keywords per ad group


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


def create_search_campaign(
    name: str,
    daily_budget_yen: int,
    keywords: list[str],
    negative_keywords: list[str] | None = None,
    headlines: list[str] | None = None,
    descriptions: list[str] | None = None,
) -> dict:
    """Create a Google Ads search campaign in PAUSED state.

    Returns dict with campaign_id, ad_group_id, or empty dict on failure.
    Safety: budget capped at MAX_DAILY_BUDGET, keywords capped at MAX_KEYWORDS_PER_GROUP.
    """
    # Safety clamps
    clamped_budget = min(daily_budget_yen, MAX_DAILY_BUDGET)
    if clamped_budget != daily_budget_yen:
        logger.warning(f"Budget clamped: {daily_budget_yen}¥ → {clamped_budget}¥")

    clamped_keywords = keywords[:MAX_KEYWORDS_PER_GROUP]
    if len(clamped_keywords) != len(keywords):
        logger.warning(f"Keywords clamped: {len(keywords)} → {len(clamped_keywords)}")

    client = _get_client()
    if not client:
        return {}

    try:
        budget_micros = clamped_budget * 1_000_000

        # 1. Create campaign budget
        budget_service = client.get_service("CampaignBudgetService")
        budget_op = client.get_type("CampaignBudgetOperation")
        budget_obj = budget_op.create
        budget_obj.name = f"{name}_budget_{datetime.now().strftime('%Y%m%d%H%M')}"
        budget_obj.amount_micros = budget_micros
        budget_obj.delivery_method = client.enums.BudgetDeliveryMethodEnum.STANDARD

        budget_response = budget_service.mutate_campaign_budgets(
            customer_id=CUSTOMER_ID,
            operations=[budget_op],
        )
        budget_resource = budget_response.results[0].resource_name
        logger.info(f"Budget created: {budget_resource}")

        # 2. Create campaign (PAUSED)
        campaign_service = client.get_service("CampaignService")
        campaign_op = client.get_type("CampaignOperation")
        campaign_obj = campaign_op.create
        campaign_obj.name = name
        campaign_obj.status = client.enums.CampaignStatusEnum.PAUSED
        campaign_obj.advertising_channel_type = client.enums.AdvertisingChannelTypeEnum.SEARCH
        campaign_obj.campaign_budget = budget_resource

        # Manual CPC bidding
        campaign_obj.manual_cpc.enhanced_cpc_enabled = False

        # Network settings
        campaign_obj.network_settings.target_google_search = True
        campaign_obj.network_settings.target_search_network = False
        campaign_obj.network_settings.target_content_network = False

        campaign_response = campaign_service.mutate_campaigns(
            customer_id=CUSTOMER_ID,
            operations=[campaign_op],
        )
        campaign_resource = campaign_response.results[0].resource_name
        campaign_id = campaign_resource.split("/")[-1]
        logger.info(f"Campaign created (PAUSED): {campaign_resource}")

        # 3. Create ad group
        ad_group_service = client.get_service("AdGroupService")
        ad_group_op = client.get_type("AdGroupOperation")
        ad_group_obj = ad_group_op.create
        ad_group_obj.name = f"{name}_adgroup"
        ad_group_obj.campaign = campaign_resource
        ad_group_obj.status = client.enums.AdGroupStatusEnum.ENABLED
        ad_group_obj.type_ = client.enums.AdGroupTypeEnum.SEARCH_STANDARD

        # Default CPC bid
        ad_group_obj.cpc_bid_micros = 100 * 1_000_000  # 100 yen default

        ad_group_response = ad_group_service.mutate_ad_groups(
            customer_id=CUSTOMER_ID,
            operations=[ad_group_op],
        )
        ad_group_resource = ad_group_response.results[0].resource_name
        ad_group_id = ad_group_resource.split("/")[-1]
        logger.info(f"Ad group created: {ad_group_resource}")

        # 4. Create Responsive Search Ad (RSA)
        if headlines and descriptions:
            ad_service = client.get_service("AdGroupAdService")
            ad_op = client.get_type("AdGroupAdOperation")
            ad_obj = ad_op.create
            ad_obj.ad_group = ad_group_resource
            ad_obj.status = client.enums.AdGroupAdStatusEnum.ENABLED

            rsa = ad_obj.ad.responsive_search_ad
            for h in headlines[:15]:  # RSA max 15 headlines
                headline_asset = client.get_type("AdTextAsset")
                headline_asset.text = h[:30]  # Max 30 chars per headline
                rsa.headlines.append(headline_asset)

            for d in descriptions[:4]:  # RSA max 4 descriptions
                desc_asset = client.get_type("AdTextAsset")
                desc_asset.text = d[:90]  # Max 90 chars per description
                rsa.descriptions.append(desc_asset)

            ad_obj.ad.final_urls.append(f"https://lp-app-pi.vercel.app")

            ad_service.mutate_ad_group_ads(
                customer_id=CUSTOMER_ID,
                operations=[ad_op],
            )
            logger.info("RSA created")

        # 5. Add keywords
        criterion_service = client.get_service("AdGroupCriterionService")
        keyword_ops = []
        for kw in clamped_keywords:
            kw_op = client.get_type("AdGroupCriterionOperation")
            kw_obj = kw_op.create
            kw_obj.ad_group = ad_group_resource
            kw_obj.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
            kw_obj.keyword.text = kw
            kw_obj.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD
            keyword_ops.append(kw_op)

        if keyword_ops:
            criterion_service.mutate_ad_group_criteria(
                customer_id=CUSTOMER_ID,
                operations=keyword_ops,
            )
            logger.info(f"Added {len(keyword_ops)} keywords")

        # 6. Add negative keywords
        if negative_keywords:
            neg_ops = []
            for nkw in negative_keywords[:20]:
                neg_op = client.get_type("AdGroupCriterionOperation")
                neg_obj = neg_op.create
                neg_obj.ad_group = ad_group_resource
                neg_obj.keyword.text = nkw
                neg_obj.keyword.match_type = client.enums.KeywordMatchTypeEnum.EXACT
                neg_obj.negative = True
                neg_ops.append(neg_op)

            if neg_ops:
                criterion_service.mutate_ad_group_criteria(
                    customer_id=CUSTOMER_ID,
                    operations=neg_ops,
                )
                logger.info(f"Added {len(neg_ops)} negative keywords")

        result = {
            "campaign_id": campaign_id,
            "campaign_resource": campaign_resource,
            "ad_group_id": ad_group_id,
            "budget_resource": budget_resource,
            "status": "PAUSED",
        }
        logger.info(f"Campaign creation complete: {name} (ID: {campaign_id})")
        return result

    except Exception as e:
        logger.error(f"Campaign creation failed: {e}")
        return {}


def activate_campaign(campaign_id: str) -> bool:
    """Enable a previously paused campaign (after human approval)."""
    client = _get_client()
    if not client:
        return False

    try:
        campaign_service = client.get_service("CampaignService")
        resource_name = campaign_service.campaign_path(CUSTOMER_ID, campaign_id)

        operation = client.get_type("CampaignOperation")
        campaign = operation.update
        campaign.resource_name = resource_name
        campaign.status = client.enums.CampaignStatusEnum.ENABLED

        client.copy_from(
            operation.update_mask,
            client.get_type("FieldMask")(paths=["status"]),
        )

        campaign_service.mutate_campaigns(
            customer_id=CUSTOMER_ID,
            operations=[operation],
        )

        logger.info(f"Campaign activated: {campaign_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to activate campaign: {e}")
        return False
