"""Fundamental and technical scoring models.

Previously a single 1481-line module. The public surface is unchanged: every
name that ``screener.scoring`` exported is re-exported here, so
``from screener.scoring import StockScorer`` keeps working.

The split follows the direction of dependency, with no cycles:

``constants``      schema tables and point capacities; imports nothing
``points``         per-metric point curves
``fundamental``    generic fundamental scoring, coverage, model selection
``sector_models``  financial-services and real-estate models
``technical``      technical component scores and their coverage shrinkage
``engine``         StockScorer, the cross-sectional orchestrator
"""

from .constants import (
    CANONICAL_DECISION_COLUMNS,
    FINANCIAL_MODEL_NAMES,
    FINANCIAL_SPECIALIZED_FIELDS,
    FUND_KEY_FIELDS,
    FUNDAMENTAL_ABSENCE_IS_ZERO,
    FUNDAMENTAL_COMPONENT_INPUTS,
    FUNDAMENTAL_COMPONENT_MAX,
    GENERIC_FUNDAMENTAL_FIELDS,
    RATING_ORDER,
    SECTOR_RELATIVE_COLUMN_BY_KEY,
    SECTOR_RELATIVE_FIELDS,
    SECTOR_RELATIVE_MINIMUMS,
    TECH_COMPONENT_MAX,
)
from .engine import StockScorer, sort_by_recommendation
from .fundamental import (
    fundamental_anomalies,
    fundamental_component_capacity,
    fundamental_model_for_row,
    fundamental_score_details,
    score_fundamentals,
    sector_relative_fund_scores,
    specialized_quality_gate,
)
from .sector_models import score_financial_services, score_real_estate

__all__ = [
    "CANONICAL_DECISION_COLUMNS",
    "FINANCIAL_MODEL_NAMES",
    "FINANCIAL_SPECIALIZED_FIELDS",
    "FUNDAMENTAL_ABSENCE_IS_ZERO",
    "FUNDAMENTAL_COMPONENT_INPUTS",
    "FUNDAMENTAL_COMPONENT_MAX",
    "FUND_KEY_FIELDS",
    "GENERIC_FUNDAMENTAL_FIELDS",
    "RATING_ORDER",
    "SECTOR_RELATIVE_COLUMN_BY_KEY",
    "SECTOR_RELATIVE_FIELDS",
    "SECTOR_RELATIVE_MINIMUMS",
    "StockScorer",
    "TECH_COMPONENT_MAX",
    "fundamental_anomalies",
    "fundamental_component_capacity",
    "fundamental_model_for_row",
    "fundamental_score_details",
    "score_financial_services",
    "score_fundamentals",
    "score_real_estate",
    "sector_relative_fund_scores",
    "sort_by_recommendation",
    "specialized_quality_gate",
]
