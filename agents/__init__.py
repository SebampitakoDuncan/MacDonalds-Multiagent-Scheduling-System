"""
Multi-Agent System for McDonald's Workforce Scheduling.

This module contains all agent implementations for the scheduling system.
"""
from .base_agent import BaseAgent
from .coordinator import CoordinatorAgent
from .data_loader import DataLoaderAgent
from .demand_forecaster import DemandForecasterAgent
from .staff_matcher import StaffMatcherAgent
from .compliance_validator import ComplianceValidatorAgent
from .conflict_resolver import ConflictResolverAgent
from .explainer import ExplainerAgent
from .roster_generator import RosterGeneratorAgent

__all__ = [
    "BaseAgent",
    "CoordinatorAgent",
    "DataLoaderAgent",
    "DemandForecasterAgent",
    "StaffMatcherAgent",
    "ComplianceValidatorAgent",
    "ConflictResolverAgent",
    "ExplainerAgent",
    "RosterGeneratorAgent",
]

