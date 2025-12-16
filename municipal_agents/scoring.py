# -*- coding: utf-8 -*-
"""
Composite Value-Score Engine for Municipal System v2.

Implements the scoring formula from SPECIFICATION_v1.md:
- Tiered scoring for safety and mandate
- Continuous benefit score with Bayesian normalization
- Exponential urgency decay with floor
- Hybrid feasibility (agent + human override)
- Equity multiplier based on district service ratio
"""

import math
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass

from .config import (
    SCORING_WEIGHTS,
    TIER_VALUES,
    URGENCY_CONFIG,
    BOOTSTRAP_CONFIG,
    EQUITY_CONFIG,
    CITY_PROFILE,
)
from .models import IssueWithSignal, ScoreComponents, SafetyTier, MandateTier


@dataclass
class BenefitNormalizer:
    """
    Bayesian benefit score normalizer with bootstrap and shrinkage.
    
    Implements two-phase normalization:
    - Phase 0: Synthetic prior from city profile
    - Phase 1: Quarterly recalibration with empirical data
    """
    prior_median: float
    prior_strength: int
    empirical_median: Optional[float] = None
    n_projects: int = 0
    
    @classmethod
    def from_config(cls, avg_project_count: int = 50) -> "BenefitNormalizer":
        """Initialize with bootstrap prior from city profile."""
        city_pop = CITY_PROFILE["population"]
        quarterly_budget = CITY_PROFILE["quarterly_budget"]
        
        # Prior: population / (budget / avg projects) = pop per dollar of typical project
        avg_project_cost = quarterly_budget / avg_project_count
        prior_median = city_pop / avg_project_cost
        
        return cls(
            prior_median=prior_median,
            prior_strength=BOOTSTRAP_CONFIG["prior_strength"],
        )
    
    def update_empirical(self, benefit_ratios: List[float]) -> None:
        """Update with empirical data from completed projects."""
        if not benefit_ratios:
            return
        
        # Winsorize to remove outliers
        p_low, p_high = BOOTSTRAP_CONFIG["winsorize_percentiles"]
        sorted_ratios = sorted(benefit_ratios)
        n = len(sorted_ratios)
        low_idx = int(n * p_low)
        high_idx = int(n * p_high) - 1
        winsorized = sorted_ratios[low_idx:high_idx + 1]
        
        if winsorized:
            self.empirical_median = sorted(winsorized)[len(winsorized) // 2]
            self.n_projects = n
    
    @property
    def blended_median(self) -> float:
        """Get blended median using Bayesian shrinkage."""
        if self.empirical_median is None or self.n_projects == 0:
            return self.prior_median
        
        # Shrinkage weight: more data → trust empirical more
        shrinkage = self.n_projects / (self.n_projects + self.prior_strength)
        return shrinkage * self.empirical_median + (1 - shrinkage) * self.prior_median


class CompositeScorer:
    """
    Computes composite value-scores for municipal projects.
    
    Formula:
        composite = (
            w_safety × safety_score
          + w_mandate × mandate_score
          + w_benefit × benefit_score
          + w_urgency × urgency_score
          + w_feasibility × feasibility_score
        ) × equity_multiplier
    """
    
    def __init__(
        self,
        benefit_normalizer: Optional[BenefitNormalizer] = None,
        district_service_ratios: Optional[Dict[int, float]] = None,
    ):
        """
        Initialize scorer.
        
        Args:
            benefit_normalizer: Normalizer for benefit scores (default: bootstrap)
            district_service_ratios: Pre-computed service ratios by district ID
        """
        self.normalizer = benefit_normalizer or BenefitNormalizer.from_config()
        self.district_ratios = district_service_ratios or {}
        self.weights = SCORING_WEIGHTS
    
    def score_safety(self, tier: SafetyTier) -> float:
        """Convert safety tier to score [0, 1]."""
        return TIER_VALUES["safety"].get(tier, 0.0)
    
    def score_mandate(self, tier: MandateTier) -> float:
        """Convert mandate tier to score [0, 1]."""
        return TIER_VALUES["mandate"].get(tier, 0.0)
    
    def score_benefit(self, population_affected: int, estimated_cost: float) -> float:
        """
        Compute benefit score (citizens served per dollar, normalized).
        
        Returns value in [0, 1], capped at 1.0.
        """
        if estimated_cost <= 0:
            return 0.0
        
        raw_ratio = population_affected / estimated_cost
        normalized = raw_ratio / self.normalizer.blended_median
        return min(1.0, max(0.0, normalized))
    
    def score_urgency(self, days_remaining: int) -> float:
        """
        Compute urgency score with exponential decay.
        
        Formula: max(floor, e^(-λ × days))
        
        Reference values (λ=0.02, floor=0.1):
            7 days  → 0.87
            30 days → 0.55
            90 days → 0.17
            180 days → 0.10 (floor)
        """
        lam = URGENCY_CONFIG["lambda"]
        floor = URGENCY_CONFIG["floor"]
        
        decay = math.exp(-lam * days_remaining)
        return max(floor, decay)
    
    def compute_equity_multiplier(self, district_id: Optional[int]) -> Tuple[float, str]:
        """
        Compute equity multiplier based on district service ratio.
        
        Returns:
            (multiplier, tier) where multiplier is in [0.875, 1.125]
        """
        if district_id is None or district_id not in self.district_ratios:
            return 1.0, "average"
        
        service_ratio = self.district_ratios[district_id]
        
        # Determine tier
        if service_ratio < EQUITY_CONFIG["underserved_threshold"]:
            tier = "underserved"
        elif service_ratio > EQUITY_CONFIG["overserved_threshold"]:
            tier = "well_served"
        else:
            tier = "average"
        
        # Compute continuous equity score
        equity_score = 1 - service_ratio
        clamp_low, clamp_high = EQUITY_CONFIG["clamp_bounds"]
        equity_score = max(clamp_low, min(clamp_high, equity_score))
        
        # Apply multiplier strength
        multiplier = 1 + EQUITY_CONFIG["multiplier_strength"] * equity_score
        
        return multiplier, tier
    
    def compute_composite(
        self,
        signal: IssueWithSignal,
        feasibility: float = 1.0,
        district_id: Optional[int] = None,
    ) -> ScoreComponents:
        """
        Compute full composite score for an issue.
        
        Args:
            signal: Issue with signal data
            feasibility: Feasibility score [0, 1]
            district_id: District ID for equity calculation
        
        Returns:
            ScoreComponents with all sub-scores and composite
        """
        # Individual scores
        safety = self.score_safety(signal.safety_tier)
        mandate = self.score_mandate(signal.mandate_tier)
        benefit = self.score_benefit(signal.population_affected, signal.estimated_cost)
        urgency = self.score_urgency(signal.urgency_days)
        
        # Equity multiplier
        equity_mult, equity_tier = self.compute_equity_multiplier(district_id)
        
        # Weighted sum
        base_score = (
            self.weights["safety"] * safety
            + self.weights["mandate"] * mandate
            + self.weights["benefit"] * benefit
            + self.weights["urgency"] * urgency
            + self.weights["feasibility"] * feasibility
        )
        
        # Apply equity multiplier
        composite = base_score * equity_mult
        
        return ScoreComponents(
            safety_score=safety,
            mandate_score=mandate,
            benefit_score=benefit,
            urgency_score=urgency,
            feasibility_score=feasibility,
            equity_multiplier=equity_mult,
            composite_score=composite,
        )
    
    def explain_score(self, components: ScoreComponents) -> str:
        """Generate human-readable explanation of score breakdown."""
        lines = [
            "Composite Score Breakdown:",
            f"  Safety:      {components.safety_score:.2f} × {self.weights['safety']:.0%} = {components.safety_score * self.weights['safety']:.3f}",
            f"  Mandate:     {components.mandate_score:.2f} × {self.weights['mandate']:.0%} = {components.mandate_score * self.weights['mandate']:.3f}",
            f"  Benefit:     {components.benefit_score:.2f} × {self.weights['benefit']:.0%} = {components.benefit_score * self.weights['benefit']:.3f}",
            f"  Urgency:     {components.urgency_score:.2f} × {self.weights['urgency']:.0%} = {components.urgency_score * self.weights['urgency']:.3f}",
            f"  Feasibility: {components.feasibility_score:.2f} × {self.weights['feasibility']:.0%} = {components.feasibility_score * self.weights['feasibility']:.3f}",
            f"  ─────────────────────────",
            f"  Base Score:  {components.composite_score / components.equity_multiplier:.3f}",
            f"  Equity ×:    {components.equity_multiplier:.3f}",
            f"  ═════════════════════════",
            f"  COMPOSITE:   {components.composite_score:.3f}",
        ]
        return "\n".join(lines)


def compute_district_service_ratios(
    district_allocations: List[Dict],
    city_population: int,
    city_projects: int,
) -> Dict[int, float]:
    """
    Compute service ratios for all districts.
    
    service_ratio = (projects_d / pop_d) / (projects_city / pop_city)
    
    Args:
        district_allocations: List of {district_id, population, project_count}
        city_population: Total city population
        city_projects: Total projects city-wide
    
    Returns:
        Dict mapping district_id to service_ratio
    """
    if city_population <= 0 or city_projects <= 0:
        return {}
    
    city_rate = city_projects / city_population
    
    ratios = {}
    for alloc in district_allocations:
        district_id = alloc["district_id"]
        pop = alloc.get("population", 0)
        projects = alloc.get("project_count", 0)
        
        if pop > 0:
            district_rate = projects / pop
            ratios[district_id] = district_rate / city_rate if city_rate > 0 else 1.0
        else:
            ratios[district_id] = 1.0
    
    return ratios
