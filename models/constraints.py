"""
Constraint models for the scheduling system.
Defines hard and soft constraints based on Fair Work Act and business rules.
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class ConstraintType(Enum):
    """Categories of constraints."""
    
    # Hard constraints (must satisfy)
    LEGAL = "legal"                    # Fair Work Act compliance
    AVAILABILITY = "availability"       # Employee availability
    SKILL = "skill"                    # Station qualification
    HOURS_MAX = "hours_max"            # Maximum hours limit
    REST_PERIOD = "rest_period"        # Minimum rest between shifts
    CONSECUTIVE_DAYS = "consecutive"   # Max consecutive working days
    MIN_STAFF = "min_staff"            # Minimum staffing requirement
    
    # Soft constraints (should optimize)
    PREFERENCE = "preference"          # Employee preferences
    HOURS_MIN = "hours_min"            # Minimum hours target
    COST = "cost"                      # Labor cost optimization
    COVERAGE = "coverage"              # Peak coverage optimization
    FAIRNESS = "fairness"              # Fair distribution of shifts


@dataclass
class Violation:
    """
    Represents a constraint violation.
    
    Attributes:
        constraint_type: Type of constraint violated
        severity: 1-10, where 10 is most severe
        description: Human-readable description
        affected_entity: ID of the affected employee/shift
        affected_date: Date of the violation
        details: Additional details about the violation
        suggestions: Possible resolution suggestions
    """
    constraint_type: ConstraintType
    severity: int
    description: str
    affected_entity: str
    affected_date: Optional[date] = None
    details: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)
    
    def is_hard_constraint(self) -> bool:
        """Check if this is a hard constraint violation."""
        hard_types = {
            ConstraintType.LEGAL,
            ConstraintType.AVAILABILITY,
            ConstraintType.SKILL,
            ConstraintType.HOURS_MAX,
            ConstraintType.REST_PERIOD,
            ConstraintType.CONSECUTIVE_DAYS,
            ConstraintType.MIN_STAFF,
        }
        return self.constraint_type in hard_types
    
    def __str__(self) -> str:
        severity_emoji = "🔴" if self.severity >= 8 else "🟡" if self.severity >= 5 else "🟢"
        return (
            f"{severity_emoji} [{self.constraint_type.value.upper()}] {self.description}"
        )


@dataclass
class ComplianceResult:
    """
    Result of a compliance check.
    
    Attributes:
        is_compliant: Whether the schedule passes all hard constraints
        violations: List of violations found
        warnings: List of soft constraint violations (warnings)
        pending_approvals: Violations escalated to manager for approval (human-in-the-loop)
        score: Overall compliance score (0-100)
        checked_at: When the check was performed
    """
    is_compliant: bool
    violations: List[Violation] = field(default_factory=list)
    warnings: List[Violation] = field(default_factory=list)
    pending_approvals: List[Violation] = field(default_factory=list)
    score: float = 100.0
    checked_at: datetime = field(default_factory=datetime.now)
    fairness_metrics: Dict[str, Any] = field(default_factory=dict)  # Gini coefficient, hours distribution
    
    def add_violation(self, violation: Violation) -> None:
        """
        Add a violation to the appropriate list with enhanced scoring.
        
        Scoring weights are differentiated by constraint type:
        - Hard constraints: High impact (severity * 2)
        - Soft constraints: Varied impact based on type and importance
        """
        if violation.is_hard_constraint():
            self.violations.append(violation)
            self.is_compliant = False
            # Hard violations reduce score significantly
            self.score = max(0, self.score - violation.severity * 2)
        else:
            self.warnings.append(violation)
            # Enhanced soft constraint scoring based on type
            penalty = self._calculate_soft_penalty(violation)
            self.score = max(0, self.score - penalty)
    
    def _calculate_soft_penalty(self, violation: Violation) -> float:
        """
        Calculate penalty for soft constraint violations.
        
        Scoring Philosophy:
        - Soft constraints are OPTIMIZATION targets, not failures
        - Informational alerts should NOT penalize the score
        - Only actual service-impacting issues reduce score
        - Target: 80%+ score when all hard constraints are met
        
        Categories:
        - Informational (0 penalty): Alerts, proactive warnings
        - Minor (low penalty): Preferences, fairness
        - Moderate (medium penalty): Hours below target
        - Significant (higher penalty): Coverage gaps
        """
        # Check if this is an informational alert (zero penalty)
        if self._is_informational_warning(violation):
            return 0.0
        
        # Base penalty - reduced to allow higher scores
        base_penalty = violation.severity * 0.05  # Reduced from 0.1
        
        # Weight multipliers by constraint type
        weights = {
            ConstraintType.COVERAGE: 0.8,      # Coverage gaps matter but manageable
            ConstraintType.HOURS_MIN: 0.5,     # Below target hours is minor
            ConstraintType.FAIRNESS: 0.3,      # Fairness is aspirational
            ConstraintType.PREFERENCE: 0.2,    # Preferences are nice-to-have
            ConstraintType.COST: 0.4,          # Cost is secondary to coverage
        }
        
        multiplier = weights.get(violation.constraint_type, 0.5)
        
        # Cap the maximum penalty per soft violation
        penalty = base_penalty * multiplier
        return min(penalty, 0.5)  # Max 0.5 points per soft violation
    
    def _is_informational_warning(self, violation: Violation) -> bool:
        """
        Determine if a warning is informational (zero penalty).
        
        Informational warnings exist to inform managers, not to penalize the schedule.
        They represent proactive alerts, not actual problems.
        """
        # Proactive hour limit alerts are informational
        if violation.details.get("alert_type") == "approaching_limit":
            return True
        
        # Fairness observations are informational (Gini < 0.4 is acceptable)
        if violation.constraint_type == ConstraintType.FAIRNESS:
            gini = violation.details.get("gini_coefficient", 0)
            if gini < 0.4:  # Acceptable fairness level
                return True
        
        # Minor understaffing (1 person short) during non-peak is informational
        if violation.constraint_type == ConstraintType.COVERAGE:
            current = violation.details.get("current_coverage", 0)
            required = violation.details.get("required_coverage", 0)
            shortfall = required - current
            if shortfall <= 1 and violation.details.get("peak_type") is None:
                return True
        
        return False
    
    def escalate_to_manager(self, violation: Violation, reason: str) -> None:
        """
        Escalate an unresolvable violation to manager for approval.
        
        This implements the human-in-the-loop pattern:
        - Removes from hard violations list
        - Adds to pending_approvals with context
        - Re-calculates compliance status
        
        Args:
            violation: The violation to escalate
            reason: Explanation of why this needs manager approval
        """
        if violation in self.violations:
            self.violations.remove(violation)
            
            # Add context about why approval is needed
            violation.details["escalation_reason"] = reason
            violation.details["requires_manager_approval"] = True
            violation.suggestions.insert(0, f"⚠️ MANAGER APPROVAL REQUIRED: {reason}")
            
            self.pending_approvals.append(violation)
            
            # Recalculate compliance - pending approvals don't block compliance
            self.is_compliant = len(self.violations) == 0
            
            # Pending approvals have moderate score impact (between hard and soft)
            self.score = min(100, self.score + violation.severity * 2)  # Restore hard penalty
            self.score = max(0, self.score - violation.severity * 0.5)  # Apply softer penalty
    
    def get_critical_violations(self) -> List[Violation]:
        """Get violations with severity >= 8."""
        return [v for v in self.violations if v.severity >= 8]
    
    def get_pending_approval_summary(self) -> List[dict]:
        """Get summary of items needing manager approval."""
        return [
            {
                "type": v.constraint_type.value,
                "description": v.description,
                "date": v.affected_date,
                "reason": v.details.get("escalation_reason", "Unresolvable constraint"),
                "suggestions": v.suggestions
            }
            for v in self.pending_approvals
        ]
    
    def summary(self) -> dict:
        """Get a summary of the compliance result."""
        return {
            "is_compliant": self.is_compliant,
            "hard_violations": len(self.violations),
            "soft_violations": len(self.warnings),
            "pending_approvals": len(self.pending_approvals),
            "score": self.score,
            "critical_count": len(self.get_critical_violations()),
        }
    
    def __str__(self) -> str:
        status = "✅ COMPLIANT" if self.is_compliant else "❌ NON-COMPLIANT"
        pending = f", {len(self.pending_approvals)} pending approval" if self.pending_approvals else ""
        return (
            f"{status} | Score: {self.score:.1f}/100 | "
            f"Violations: {len(self.violations)} hard, {len(self.warnings)} soft{pending}"
        )


@dataclass
class Constraint:
    """
    Base constraint definition.
    
    Attributes:
        name: Constraint name
        constraint_type: Category of constraint
        is_hard: Whether this is a hard constraint
        description: Human-readable description
        parameters: Constraint parameters (e.g., max_hours=38)
    """
    name: str
    constraint_type: ConstraintType
    is_hard: bool
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        hard_soft = "HARD" if self.is_hard else "SOFT"
        return f"[{hard_soft}] {self.name}: {self.description}"


# Pre-defined constraints based on Fair Work Act and business rules
class HardConstraint:
    """Collection of hard constraint definitions."""
    
    MIN_SHIFT_HOURS = Constraint(
        name="min_shift_hours",
        constraint_type=ConstraintType.LEGAL,
        is_hard=True,
        description="Minimum 3-hour shifts for casual employees",
        parameters={"min_hours": 3}
    )
    
    MAX_SHIFT_HOURS = Constraint(
        name="max_shift_hours",
        constraint_type=ConstraintType.LEGAL,
        is_hard=True,
        description="Maximum 12-hour shifts",
        parameters={"max_hours": 12}
    )
    
    REST_BETWEEN_SHIFTS = Constraint(
        name="rest_between_shifts",
        constraint_type=ConstraintType.REST_PERIOD,
        is_hard=True,
        description="Minimum 10-hour rest period between shifts",
        parameters={"min_rest_hours": 10}
    )
    
    MAX_CONSECUTIVE_DAYS = Constraint(
        name="max_consecutive_days",
        constraint_type=ConstraintType.CONSECUTIVE_DAYS,
        is_hard=True,
        description="Maximum 6 consecutive working days",
        parameters={"max_days": 6}
    )
    
    FULL_TIME_MAX_HOURS = Constraint(
        name="full_time_max_hours",
        constraint_type=ConstraintType.HOURS_MAX,
        is_hard=True,
        description="Full-time employees: maximum 38 hours/week",
        parameters={"max_hours": 38, "employee_type": "Full-Time"}
    )
    
    PART_TIME_MAX_HOURS = Constraint(
        name="part_time_max_hours",
        constraint_type=ConstraintType.HOURS_MAX,
        is_hard=True,
        description="Part-time employees: maximum 32 hours/week",
        parameters={"max_hours": 32, "employee_type": "Part-Time"}
    )
    
    CASUAL_MAX_HOURS = Constraint(
        name="casual_max_hours",
        constraint_type=ConstraintType.HOURS_MAX,
        is_hard=True,
        description="Casual employees: maximum 24 hours/week",
        parameters={"max_hours": 24, "employee_type": "Casual"}
    )
    
    SKILL_MATCH = Constraint(
        name="skill_match",
        constraint_type=ConstraintType.SKILL,
        is_hard=True,
        description="Employee must be trained for assigned station",
        parameters={}
    )
    
    AVAILABILITY_MATCH = Constraint(
        name="availability_match",
        constraint_type=ConstraintType.AVAILABILITY,
        is_hard=True,
        description="Employee must be available for assigned shift",
        parameters={}
    )
    
    MIN_STAFF_ON_DUTY = Constraint(
        name="min_staff_on_duty",
        constraint_type=ConstraintType.MIN_STAFF,
        is_hard=True,
        description="Minimum 2 staff on duty at all times",
        parameters={"min_staff": 2}
    )


class SoftConstraint:
    """Collection of soft constraint definitions."""
    
    FULL_TIME_MIN_HOURS = Constraint(
        name="full_time_min_hours",
        constraint_type=ConstraintType.HOURS_MIN,
        is_hard=False,
        description="Full-time employees: target minimum 35 hours/week",
        parameters={"min_hours": 35, "employee_type": "Full-Time"}
    )
    
    PART_TIME_MIN_HOURS = Constraint(
        name="part_time_min_hours",
        constraint_type=ConstraintType.HOURS_MIN,
        is_hard=False,
        description="Part-time employees: target minimum 20 hours/week",
        parameters={"min_hours": 20, "employee_type": "Part-Time"}
    )
    
    CASUAL_MIN_HOURS = Constraint(
        name="casual_min_hours",
        constraint_type=ConstraintType.HOURS_MIN,
        is_hard=False,
        description="Casual employees: target minimum 8 hours/week",
        parameters={"min_hours": 8, "employee_type": "Casual"}
    )
    
    PEAK_COVERAGE = Constraint(
        name="peak_coverage",
        constraint_type=ConstraintType.COVERAGE,
        is_hard=False,
        description="Optimal staffing during peak periods",
        parameters={"peak_multiplier": 1.2}
    )
    
    WEEKEND_COVERAGE = Constraint(
        name="weekend_coverage",
        constraint_type=ConstraintType.COVERAGE,
        is_hard=False,
        description="20% higher coverage on weekends",
        parameters={"weekend_multiplier": 1.2}
    )
    
    EMPLOYEE_PREFERENCE = Constraint(
        name="employee_preference",
        constraint_type=ConstraintType.PREFERENCE,
        is_hard=False,
        description="Respect employee shift preferences",
        parameters={}
    )
    
    FAIR_DISTRIBUTION = Constraint(
        name="fair_distribution",
        constraint_type=ConstraintType.FAIRNESS,
        is_hard=False,
        description="Distribute shifts fairly among employees",
        parameters={}
    )

