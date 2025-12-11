"""
Compliance Validator Agent - Validates schedules against Fair Work Act and business rules.
"""
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set
from collections import defaultdict

from .base_agent import BaseAgent
from communication.message import Message, MessageType
from communication.message_bus import MessageBus
from models.employee import Employee, EmployeeType, Station
from models.shift import Shift, TimeSlot, PEAK_PERIODS, SERVICE_PERIODS
from models.schedule import Schedule, Assignment
from models.constraints import (
    Violation, ComplianceResult, ConstraintType,
    HardConstraint, SoftConstraint
)
from models.store import Store


class ComplianceValidatorAgent(BaseAgent):
    """
    Agent responsible for validating schedule compliance.
    
    Responsibilities:
    - Check Fair Work Act compliance
    - Validate working hours limits
    - Ensure minimum rest periods
    - Check station skill requirements
    - Verify minimum staffing levels
    - Report all violations
    """
    
    def __init__(self, message_bus: MessageBus):
        super().__init__("ComplianceValidator", message_bus)
        self.schedule: Optional[Schedule] = None
        self.store: Optional[Store] = None
        self.employees: Dict[str, Employee] = {}
        self.demand_forecast: Dict[date, Dict] = {}
        
        # Compliance parameters
        self.params = {
            "min_rest_hours": 10,
            "max_consecutive_days": 6,
            "min_shift_hours": 3,
            "max_shift_hours": 12,
            "hours_limits": {
                EmployeeType.FULL_TIME: (35, 38),
                EmployeeType.PART_TIME: (20, 32),
                EmployeeType.CASUAL: (8, 24),
            }
        }
    
    def execute(self,
                schedule: Schedule,
                employees: List[Employee],
                store: Store,
                demand_forecast: Dict[date, Dict] = None,
                **kwargs) -> ComplianceResult:
        """
        Validate a schedule for compliance.
        
        Args:
            schedule: The schedule to validate
            employees: List of employees
            store: Store configuration
            demand_forecast: Optional demand data for coverage checks
            
        Returns:
            ComplianceResult with all violations
        """
        self.schedule = schedule
        self.store = store
        self.employees = {e.id: e for e in employees}
        self.demand_forecast = demand_forecast or {}
        
        self.log(f"Validating schedule: {len(schedule.assignments)} assignments")
        
        # Initialize result
        result = ComplianceResult(is_compliant=True)
        
        # Run all compliance checks
        self._check_availability_compliance(result)
        self._check_skill_compliance(result)
        self._check_hours_compliance(result)
        self._check_rest_period_compliance(result)
        self._check_consecutive_days_compliance(result)
        self._check_minimum_staffing(result)
        self._check_peak_coverage(result)
        self._check_fairness(result)  # Soft constraint: workload fairness
        
        # Send results to Coordinator
        self.send(
            MessageType.VALIDATION_RESULT,
            {
                "is_compliant": result.is_compliant,
                "violation_count": len(result.violations),
                "warning_count": len(result.warnings),
                "score": result.score,
                "summary": result.summary(),
            },
            receiver="Coordinator"
        )
        
        # If violations found, also notify Conflict Resolver
        if not result.is_compliant:
            self.send(
                MessageType.VIOLATION,
                {
                    "violations": [self._violation_to_dict(v) for v in result.violations],
                    "warnings": [self._violation_to_dict(v) for v in result.warnings],
                },
                receiver="ConflictResolver"
            )
            self.log(f"Found {len(result.violations)} violations, {len(result.warnings)} warnings", "warning")
        else:
            self.log("Schedule is compliant! ✓", "success")
        
        return result
    
    def _check_availability_compliance(self, result: ComplianceResult) -> None:
        """Check that all assignments respect employee availability."""
        for assignment in self.schedule.assignments:
            employee = self.employees.get(assignment.employee.id)
            if not employee:
                continue
            
            shift_code = assignment.shift.shift_type.value
            target_date = assignment.shift.date
            
            if not employee.is_available(target_date, shift_code):
                violation = Violation(
                    constraint_type=ConstraintType.AVAILABILITY,
                    severity=10,  # Hard constraint - critical
                    description=f"{employee.name} is not available for {shift_code} on {target_date}",
                    affected_entity=employee.id,
                    affected_date=target_date,
                    details={
                        "employee_name": employee.name,
                        "shift_code": shift_code,
                        "available_shifts": employee.get_available_shifts(target_date),
                    },
                    suggestions=[
                        f"Assign a different employee who is available for {shift_code}",
                        f"Change {employee.name} to an available shift code",
                    ]
                )
                result.add_violation(violation)
    
    def _check_skill_compliance(self, result: ComplianceResult) -> None:
        """Check that employees are qualified for their assigned stations."""
        for assignment in self.schedule.assignments:
            employee = self.employees.get(assignment.employee.id)
            if not employee:
                continue
            
            if not employee.can_work_station(assignment.station):
                violation = Violation(
                    constraint_type=ConstraintType.SKILL,
                    severity=9,
                    description=f"{employee.name} is not trained for {assignment.station.value}",
                    affected_entity=employee.id,
                    affected_date=assignment.shift.date,
                    details={
                        "employee_name": employee.name,
                        "assigned_station": assignment.station.value,
                        "qualified_stations": [s.value for s in employee.skills],
                    },
                    suggestions=[
                        f"Assign {employee.name} to their qualified station: {employee.primary_station.value}",
                        f"Find an employee qualified for {assignment.station.value}",
                    ]
                )
                result.add_violation(violation)
    
    def _check_hours_compliance(self, result: ComplianceResult) -> None:
        """Check weekly hours limits for all employees."""
        # Calculate hours per employee per week
        employee_weekly_hours: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        
        for assignment in self.schedule.assignments:
            emp_id = assignment.employee.id
            week_num = self._get_week_number(assignment.shift.date)
            employee_weekly_hours[emp_id][week_num] += assignment.shift.hours
        
        # Check each employee
        for emp_id, weekly_hours in employee_weekly_hours.items():
            employee = self.employees.get(emp_id)
            if not employee:
                continue
            
            min_hours, max_hours = self.params["hours_limits"].get(
                employee.employee_type, (0, 40)
            )
            
            for week_num, hours in weekly_hours.items():
                # Check maximum hours (hard constraint)
                if hours > max_hours:
                    violation = Violation(
                        constraint_type=ConstraintType.HOURS_MAX,
                        severity=9,
                        description=f"{employee.name} exceeds max hours: {hours:.1f}/{max_hours}h in week {week_num + 1}",
                        affected_entity=emp_id,
                        details={
                            "employee_name": employee.name,
                            "employee_type": employee.employee_type.value,
                            "current_hours": hours,
                            "max_hours": max_hours,
                            "week": week_num + 1,
                            "excess_hours": hours - max_hours,
                        },
                        suggestions=[
                            f"Remove {hours - max_hours:.1f} hours from {employee.name}'s schedule",
                            f"Reassign some shifts to other employees",
                        ]
                    )
                    result.add_violation(violation)
                
                # Check minimum hours (soft constraint - warning)
                elif hours < min_hours:
                    warning = Violation(
                        constraint_type=ConstraintType.HOURS_MIN,
                        severity=4,
                        description=f"{employee.name} below target hours: {hours:.1f}/{min_hours}h in week {week_num + 1}",
                        affected_entity=emp_id,
                        details={
                            "employee_name": employee.name,
                            "employee_type": employee.employee_type.value,
                            "current_hours": hours,
                            "min_hours": min_hours,
                            "week": week_num + 1,
                            "shortfall": min_hours - hours,
                        },
                        suggestions=[
                            f"Add {min_hours - hours:.1f} more hours for {employee.name}",
                        ]
                    )
                    result.add_violation(warning)
                
                # Proactive alert: Approaching max hours (Success Criteria 5)
                # Alert when employee is at 85% or more of max hours
                elif hours >= max_hours * 0.85:
                    remaining = max_hours - hours
                    warning = Violation(
                        constraint_type=ConstraintType.HOURS_MAX,
                        severity=2,  # Low severity - just an alert
                        description=f"⚠️ {employee.name} approaching max hours: {hours:.1f}/{max_hours}h ({remaining:.1f}h remaining)",
                        affected_entity=emp_id,
                        details={
                            "employee_name": employee.name,
                            "employee_type": employee.employee_type.value,
                            "current_hours": hours,
                            "max_hours": max_hours,
                            "remaining_hours": remaining,
                            "week": week_num + 1,
                            "utilization_pct": (hours / max_hours) * 100,
                            "alert_type": "approaching_limit",
                        },
                        suggestions=[
                            f"Avoid assigning additional shifts to {employee.name} this week",
                            f"Only {remaining:.1f}h remaining before max limit",
                        ]
                    )
                    result.add_violation(warning)
    
    def _check_rest_period_compliance(self, result: ComplianceResult) -> None:
        """Check minimum 10-hour rest between shifts."""
        # Group assignments by employee
        employee_assignments: Dict[str, List[Assignment]] = defaultdict(list)
        for assignment in self.schedule.assignments:
            employee_assignments[assignment.employee.id].append(assignment)
        
        min_rest = self.params["min_rest_hours"]
        
        for emp_id, assignments in employee_assignments.items():
            employee = self.employees.get(emp_id)
            if not employee:
                continue
            
            # Sort by date and start time
            sorted_assignments = sorted(
                assignments,
                key=lambda a: (a.shift.date, a.shift.start_time)
            )
            
            # Check consecutive assignments
            for i in range(len(sorted_assignments) - 1):
                current = sorted_assignments[i]
                next_shift = sorted_assignments[i + 1]
                
                rest_hours = current.shift.hours_until_next(next_shift.shift)
                
                if rest_hours < min_rest:
                    violation = Violation(
                        constraint_type=ConstraintType.REST_PERIOD,
                        severity=10,  # Legal requirement
                        description=f"{employee.name} has only {rest_hours:.1f}h rest (min: {min_rest}h)",
                        affected_entity=emp_id,
                        affected_date=next_shift.shift.date,
                        details={
                            "employee_name": employee.name,
                            "shift_1": str(current.shift),
                            "shift_2": str(next_shift.shift),
                            "rest_hours": rest_hours,
                            "min_required": min_rest,
                        },
                        suggestions=[
                            f"Change {employee.name}'s shift on {next_shift.shift.date} to a later start time",
                            f"Reassign one of the shifts to another employee",
                        ]
                    )
                    result.add_violation(violation)
    
    def _check_consecutive_days_compliance(self, result: ComplianceResult) -> None:
        """Check maximum consecutive working days."""
        max_consecutive = self.params["max_consecutive_days"]
        
        # Group assignments by employee
        employee_dates: Dict[str, Set[date]] = defaultdict(set)
        for assignment in self.schedule.assignments:
            employee_dates[assignment.employee.id].add(assignment.shift.date)
        
        for emp_id, work_dates in employee_dates.items():
            employee = self.employees.get(emp_id)
            if not employee:
                continue
            
            sorted_dates = sorted(work_dates)
            consecutive = 1
            max_found = 1
            
            for i in range(1, len(sorted_dates)):
                if (sorted_dates[i] - sorted_dates[i-1]).days == 1:
                    consecutive += 1
                    max_found = max(max_found, consecutive)
                else:
                    consecutive = 1
            
            if max_found > max_consecutive:
                violation = Violation(
                    constraint_type=ConstraintType.CONSECUTIVE_DAYS,
                    severity=8,
                    description=f"{employee.name} works {max_found} consecutive days (max: {max_consecutive})",
                    affected_entity=emp_id,
                    details={
                        "employee_name": employee.name,
                        "consecutive_days": max_found,
                        "max_allowed": max_consecutive,
                        "work_dates": [d.isoformat() for d in sorted_dates],
                    },
                    suggestions=[
                        f"Give {employee.name} a day off within the consecutive stretch",
                        f"Reassign one day to another employee",
                    ]
                )
                result.add_violation(violation)
    
    def _check_minimum_staffing(self, result: ComplianceResult) -> None:
        """Check minimum staffing requirements."""
        min_staff = 2  # Minimum staff on duty at all times
        
        # Check each day
        for target_date in self.schedule.get_dates_in_range():
            daily_assignments = self.schedule.get_assignments_by_date(target_date)
            
            # Check overall minimum
            if len(daily_assignments) < min_staff:
                violation = Violation(
                    constraint_type=ConstraintType.MIN_STAFF,
                    severity=10,
                    description=f"Only {len(daily_assignments)} staff on {target_date} (min: {min_staff})",
                    affected_entity="schedule",
                    affected_date=target_date,
                    details={
                        "current_staff": len(daily_assignments),
                        "min_required": min_staff,
                    },
                    suggestions=[
                        f"Add {min_staff - len(daily_assignments)} more staff for {target_date}",
                    ]
                )
                result.add_violation(violation)
            
            # Check station minimums
            for station in self.store.get_active_stations():
                station_count = len([
                    a for a in daily_assignments 
                    if a.station == station
                ])
                
                if station_count < 1:
                    violation = Violation(
                        constraint_type=ConstraintType.MIN_STAFF,
                        severity=8,
                        description=f"No staff assigned to {station.value} on {target_date}",
                        affected_entity="schedule",
                        affected_date=target_date,
                        details={
                            "station": station.value,
                            "current_count": station_count,
                        },
                        suggestions=[
                            f"Assign at least 1 {station.value}-trained employee for {target_date}",
                        ]
                    )
                    result.add_violation(violation)
    
    def _check_peak_coverage(self, result: ComplianceResult) -> None:
        """
        Check coverage during peak periods.
        
        Success Criteria 2 from Challenge Brief:
        - Meets minimum staffing for lunch peak (11:00-14:00)
        - Meets minimum staffing for dinner peak (17:00-21:00)
        - Weekend coverage is 20% higher than off-peak weekdays
        - Opening (06:30) and closing (23:00) have designated staff
        """
        for target_date in self.schedule.get_dates_in_range():
            day_forecast = self.demand_forecast.get(target_date, {})
            
            # Check lunch peak (11:00-14:00)
            lunch_coverage = self.schedule.get_coverage(target_date, PEAK_PERIODS["lunch"])
            required = day_forecast.get("period_requirements", {}).get("lunch", {}).get("total_staff", 0)
            
            if lunch_coverage < required:
                warning = Violation(
                    constraint_type=ConstraintType.COVERAGE,
                    severity=5,
                    description=f"Lunch peak understaffed on {target_date}: {lunch_coverage}/{required}",
                    affected_entity="schedule",
                    affected_date=target_date,
                    details={
                        "period": "lunch",
                        "current_coverage": lunch_coverage,
                        "required_coverage": required,
                        "peak_type": "lunch_peak",
                    },
                    suggestions=[
                        f"Add {required - lunch_coverage} more staff during lunch peak (11:00-14:00)",
                    ]
                )
                result.add_violation(warning)
            
            # Check dinner peak (17:00-21:00)
            dinner_coverage = self.schedule.get_coverage(target_date, PEAK_PERIODS["dinner"])
            required = day_forecast.get("period_requirements", {}).get("dinner", {}).get("total_staff", 0)
            
            if dinner_coverage < required:
                warning = Violation(
                    constraint_type=ConstraintType.COVERAGE,
                    severity=5,
                    description=f"Dinner peak understaffed on {target_date}: {dinner_coverage}/{required}",
                    affected_entity="schedule",
                    affected_date=target_date,
                    details={
                        "period": "dinner",
                        "current_coverage": dinner_coverage,
                        "required_coverage": required,
                        "peak_type": "dinner_peak",
                    },
                    suggestions=[
                        f"Add {required - dinner_coverage} more staff during dinner peak (17:00-21:00)",
                    ]
                )
                result.add_violation(warning)
        
        # Check opening and closing coverage
        self._check_opening_closing_coverage(result)
    
    def _check_opening_closing_coverage(self, result: ComplianceResult) -> None:
        """
        Check that opening (06:30) and closing (23:00) have designated staff.
        
        From Challenge Brief Success Criteria 2:
        "Opening (06:30) and closing (23:00) have designated staff"
        """
        for target_date in self.schedule.get_dates_in_range():
            day_assignments = [
                a for a in self.schedule.assignments 
                if a.shift.date == target_date
            ]
            
            # Check opening coverage (shifts that start early: S, 1F)
            # S = 06:30-15:00, 1F = 06:30-15:30
            opening_shifts = [
                a for a in day_assignments 
                if a.shift.shift_type.value in ["S", "1F"]
            ]
            
            if not opening_shifts:
                warning = Violation(
                    constraint_type=ConstraintType.COVERAGE,
                    severity=6,  # Important but soft
                    description=f"No designated opening staff (06:30) on {target_date}",
                    affected_entity="schedule",
                    affected_date=target_date,
                    details={
                        "period": "opening",
                        "time": "06:30",
                        "coverage_type": "opening",
                    },
                    suggestions=[
                        "Assign crew member to opening shift (S or 1F)",
                        "Ensure manager has opening coverage (check monthly roster)",
                    ]
                )
                result.add_violation(warning)
            
            # Check closing coverage (shifts that end late: 2F)
            # 2F = 14:00-23:00
            closing_shifts = [
                a for a in day_assignments 
                if a.shift.shift_type.value == "2F"
            ]
            
            if not closing_shifts:
                warning = Violation(
                    constraint_type=ConstraintType.COVERAGE,
                    severity=6,  # Important but soft
                    description=f"No designated closing staff (23:00) on {target_date}",
                    affected_entity="schedule",
                    affected_date=target_date,
                    details={
                        "period": "closing",
                        "time": "23:00",
                        "coverage_type": "closing",
                    },
                    suggestions=[
                        "Assign crew member to closing shift (2F)",
                        "Ensure manager has closing coverage (check monthly roster)",
                    ]
                )
                result.add_violation(warning)
    
    def _check_fairness(self, result: ComplianceResult) -> None:
        """
        Check workload fairness across employees.
        
        Uses Gini coefficient to measure inequality in hours distribution.
        - Gini = 0: Perfect equality (everyone has same hours)
        - Gini = 1: Maximum inequality (one person has all hours)
        
        Soft Constraint: Flag if distribution is highly unequal.
        """
        # Calculate total hours per employee
        employee_hours: Dict[str, float] = defaultdict(float)
        
        for assignment in self.schedule.assignments:
            emp_id = assignment.employee.id
            employee_hours[emp_id] += assignment.shift.hours
        
        if len(employee_hours) < 2:
            return  # Need at least 2 employees for fairness comparison
        
        hours_list = list(employee_hours.values())
        
        # Calculate Gini coefficient
        gini = self._calculate_gini(hours_list)
        
        # Calculate additional fairness metrics
        mean_hours = sum(hours_list) / len(hours_list)
        max_hours = max(hours_list)
        min_hours = min(hours_list)
        std_dev = (sum((h - mean_hours) ** 2 for h in hours_list) / len(hours_list)) ** 0.5
        
        # Store fairness metrics in result
        result.fairness_metrics = {
            "gini_coefficient": gini,
            "mean_hours": mean_hours,
            "max_hours": max_hours,
            "min_hours": min_hours,
            "std_dev": std_dev,
            "hour_range": max_hours - min_hours,
            "employees_scheduled": len(employee_hours),
        }
        
        # Add warning if Gini coefficient is too high (> 0.35 indicates significant inequality)
        if gini > 0.35:
            # Find over/under-scheduled employees
            over_scheduled = [
                (eid, hrs) for eid, hrs in employee_hours.items() 
                if hrs > mean_hours * 1.3
            ]
            under_scheduled = [
                (eid, hrs) for eid, hrs in employee_hours.items() 
                if hrs < mean_hours * 0.7
            ]
            
            warning = Violation(
                constraint_type=ConstraintType.FAIRNESS,
                severity=3,  # Soft constraint
                description=f"Workload imbalance detected (Gini: {gini:.2f}). Hours range: {min_hours:.1f}-{max_hours:.1f}h",
                affected_entity="schedule",
                details={
                    "gini_coefficient": gini,
                    "mean_hours": mean_hours,
                    "hour_range": max_hours - min_hours,
                    "over_scheduled_count": len(over_scheduled),
                    "under_scheduled_count": len(under_scheduled),
                    "fairness_type": "workload_imbalance",
                },
                suggestions=[
                    "Redistribute shifts more evenly across employees",
                    f"{len(over_scheduled)} employees have >30% above average hours",
                    f"{len(under_scheduled)} employees have >30% below average hours",
                ]
            )
            result.add_violation(warning)
        
        # Log fairness summary
        self.log(f"Fairness check: Gini={gini:.3f}, Hours range={min_hours:.1f}-{max_hours:.1f}h")
    
    def _calculate_gini(self, values: List[float]) -> float:
        """
        Calculate Gini coefficient for a list of values.
        
        The Gini coefficient measures inequality in a distribution.
        - 0 = perfect equality
        - 1 = perfect inequality
        """
        if not values or len(values) == 0:
            return 0.0
        
        # Sort values
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        # Calculate Gini coefficient using the standard formula
        # G = (2 * sum(i * x_i) / (n * sum(x_i))) - (n + 1) / n
        cumsum = sum((i + 1) * val for i, val in enumerate(sorted_values))
        total = sum(sorted_values)
        
        if total == 0:
            return 0.0
        
        gini = (2 * cumsum) / (n * total) - (n + 1) / n
        return max(0.0, min(1.0, gini))  # Ensure result is between 0 and 1
    
    def _get_week_number(self, target_date: date) -> int:
        """Get week number (0 or 1) for the schedule period."""
        if not self.schedule:
            return 0
        days_from_start = (target_date - self.schedule.start_date).days
        return days_from_start // 7
    
    def _violation_to_dict(self, violation: Violation) -> dict:
        """Convert a Violation to dictionary for messaging."""
        return {
            "type": violation.constraint_type.value,
            "severity": violation.severity,
            "description": violation.description,
            "affected_entity": violation.affected_entity,
            "affected_date": violation.affected_date.isoformat() if violation.affected_date else None,
            "details": violation.details,
            "suggestions": violation.suggestions,
            "is_hard": violation.is_hard_constraint(),
        }
    
    def _on_validation_request(self, message: Message) -> None:
        """Handle validation requests from other agents."""
        content = message.content
        
        if isinstance(content, dict):
            schedule = content.get("schedule")
            employees = content.get("employees", [])
            store = content.get("store")
            
            if schedule and employees and store:
                result = self.execute(schedule, employees, store)
                self.respond(message, result.summary(), MessageType.VALIDATION_RESULT)

