"""
Conflict Resolver Agent - Detects conflicts and proposes resolutions.
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from .base_agent import BaseAgent
from communication.message import Message, MessageType
from communication.message_bus import MessageBus
from models.employee import Employee, EmployeeType, Station
from models.shift import Shift
from models.schedule import Schedule, Assignment
from models.constraints import Violation, ConstraintType, ComplianceResult
from models.store import Store


@dataclass
class Resolution:
    """
    Represents a proposed resolution to a conflict.
    
    Attributes:
        description: Human-readable description
        action: Action to take (swap, remove, add, modify)
        impact_score: Lower is better (0-100)
        changes: List of changes to make
        risk_level: low, medium, high
    """
    description: str
    action: str
    impact_score: float
    changes: List[Dict[str, Any]] = field(default_factory=list)
    risk_level: str = "low"
    requires_approval: bool = False
    
    def __str__(self) -> str:
        return f"[{self.action.upper()}] {self.description} (Impact: {self.impact_score:.1f})"


@dataclass
class NegotiationRound:
    """
    Represents a round of negotiation between agents.
    
    The negotiation protocol enables emergent collaborative behavior:
    1. ConflictResolver proposes a resolution
    2. StaffMatcher evaluates and may counter-propose
    3. Agents negotiate until consensus or max rounds
    """
    round_number: int
    proposer: str
    proposal: Resolution
    response: Optional[str] = None  # accept, reject, counter
    counter_proposal: Optional[Resolution] = None
    
    def __str__(self) -> str:
        status = self.response or "pending"
        return f"Round {self.round_number}: {self.proposer} → {status}"


class ConflictResolverAgent(BaseAgent):
    """
    Agent responsible for detecting and resolving scheduling conflicts.
    
    Responsibilities:
    - Analyze violations from ComplianceValidator
    - Generate ranked resolution options
    - NEGOTIATE with StaffMatcher for best solutions
    - Apply automatic resolutions for clear-cut cases
    - Flag complex conflicts for human review
    - Track resolution and negotiation history
    
    Negotiation Protocol:
    1. ConflictResolver proposes resolution (NEGOTIATE_PROPOSE)
    2. StaffMatcher evaluates: accept, reject, or counter
    3. If counter-proposal, ConflictResolver evaluates
    4. Continue until consensus or max rounds (3)
    """
    
    MAX_NEGOTIATION_ROUNDS = 3
    
    def __init__(self, message_bus: MessageBus):
        super().__init__("ConflictResolver", message_bus)
        self.schedule: Optional[Schedule] = None
        self.employees: Dict[str, Employee] = {}
        self.store: Optional[Store] = None
        self.violations: List[Violation] = []
        self.resolution_history: List[Dict] = []
        self.negotiation_history: List[NegotiationRound] = []  # Track negotiations
        self.max_iterations = 10  # Prevent infinite loops
        
    def execute(self,
                schedule: Schedule,
                employees: List[Employee],
                store: Store,
                compliance_result: ComplianceResult,
                **kwargs) -> Tuple[Schedule, List[Resolution]]:
        """
        Resolve conflicts in the schedule.
        
        Args:
            schedule: Current schedule
            employees: List of employees
            store: Store configuration
            compliance_result: Results from ComplianceValidator
            
        Returns:
            Tuple of (updated_schedule, list_of_applied_resolutions)
        """
        self.schedule = schedule
        self.employees = {e.id: e for e in employees}
        self.store = store
        self.violations = compliance_result.violations.copy()
        
        self.log(f"Starting conflict resolution: {len(self.violations)} violations to resolve")
        
        applied_resolutions: List[Resolution] = []
        iteration = 0
        
        while self.violations and iteration < self.max_iterations:
            iteration += 1
            self.log(f"Resolution iteration {iteration}: {len(self.violations)} violations remaining")
            
            # Process violations in priority order (highest severity first)
            self.violations.sort(key=lambda v: v.severity, reverse=True)
            
            for violation in self.violations[:]:  # Copy to allow modification
                resolutions = self._generate_resolutions(violation)
                
                if resolutions:
                    # Apply the best resolution (lowest impact score)
                    best_resolution = min(resolutions, key=lambda r: r.impact_score)
                    
                    if best_resolution.requires_approval:
                        # Send for approval
                        self._request_approval(violation, best_resolution)
                    else:
                        # Auto-apply
                        success = self._apply_resolution(best_resolution)
                        if success:
                            applied_resolutions.append(best_resolution)
                            self.violations.remove(violation)
                            
                            # Log the resolution
                            self.send(
                                MessageType.RESOLUTION_SELECTED,
                                {
                                    "violation": violation.description,
                                    "resolution": str(best_resolution),
                                    "auto_applied": True,
                                },
                                receiver="Coordinator"
                            )
                else:
                    self.log(f"No resolution found for: {violation.description}", "warning")
        
        # Report final status
        remaining_violations = len(self.violations)
        self.send(
            MessageType.COMPLETE,
            {
                "resolutions_applied": len(applied_resolutions),
                "violations_remaining": remaining_violations,
                "iterations": iteration,
                "success": remaining_violations == 0,
            },
            receiver="Coordinator"
        )
        
        if remaining_violations > 0:
            self.log(f"Could not resolve {remaining_violations} violations", "warning")
        else:
            self.log(f"All conflicts resolved in {iteration} iterations!", "success")
        
        return self.schedule, applied_resolutions
    
    def negotiate_resolution(self, violation: Violation, 
                            staff_matcher_agent: Any) -> Optional[Resolution]:
        """
        Negotiate a resolution with the StaffMatcher agent.
        
        This implements a multi-round negotiation protocol:
        1. ConflictResolver proposes initial resolution
        2. StaffMatcher evaluates based on scheduling constraints
        3. If rejected, StaffMatcher counter-proposes
        4. ConflictResolver evaluates counter-proposal
        5. Continue until consensus or max rounds
        
        Args:
            violation: The violation to resolve
            staff_matcher_agent: Reference to StaffMatcher for negotiation
            
        Returns:
            Agreed-upon resolution, or None if negotiation fails
        """
        self.log(f"🤝 Starting negotiation for: {violation.description}")
        
        # Generate initial proposals
        proposals = self._generate_resolutions(violation)
        if not proposals:
            self.log("No proposals to negotiate", "warning")
            return None
        
        # Start with best proposal
        current_proposal = min(proposals, key=lambda r: r.impact_score)
        
        for round_num in range(1, self.MAX_NEGOTIATION_ROUNDS + 1):
            # Send proposal to StaffMatcher
            self.send(
                MessageType.NEGOTIATE_PROPOSE,
                {
                    "round": round_num,
                    "proposal": {
                        "description": current_proposal.description,
                        "action": current_proposal.action,
                        "impact_score": current_proposal.impact_score,
                        "changes": current_proposal.changes,
                    },
                    "violation": violation.description,
                },
                receiver="StaffMatcher"
            )
            
            # Record negotiation round
            neg_round = NegotiationRound(
                round_number=round_num,
                proposer=self.name,
                proposal=current_proposal
            )
            
            # Evaluate proposal (simulated StaffMatcher response)
            evaluation = self._evaluate_proposal_feasibility(current_proposal)
            
            if evaluation["feasible"]:
                # Proposal accepted
                neg_round.response = "accept"
                self.negotiation_history.append(neg_round)
                
                self.send(
                    MessageType.NEGOTIATE_ACCEPT,
                    {"round": round_num, "proposal": current_proposal.description},
                    receiver="StaffMatcher"
                )
                
                self.log(f"✅ Negotiation successful (round {round_num}): {current_proposal.description}")
                return current_proposal
            
            elif evaluation.get("counter_proposal"):
                # Counter-proposal received
                neg_round.response = "counter"
                neg_round.counter_proposal = evaluation["counter_proposal"]
                self.negotiation_history.append(neg_round)
                
                # Evaluate counter-proposal
                counter = evaluation["counter_proposal"]
                if counter.impact_score <= current_proposal.impact_score * 1.2:
                    # Accept counter if not too much worse
                    self.log(f"📝 Accepting counter-proposal (round {round_num})")
                    return counter
                else:
                    # Try next proposal
                    remaining_proposals = [p for p in proposals if p != current_proposal]
                    if remaining_proposals:
                        current_proposal = min(remaining_proposals, key=lambda r: r.impact_score)
                    else:
                        break
            else:
                # Rejected, try next proposal
                neg_round.response = "reject"
                self.negotiation_history.append(neg_round)
                
                remaining_proposals = [p for p in proposals if p != current_proposal]
                if remaining_proposals:
                    current_proposal = min(remaining_proposals, key=lambda r: r.impact_score)
                else:
                    break
        
        self.log(f"❌ Negotiation failed after {self.MAX_NEGOTIATION_ROUNDS} rounds", "warning")
        return None
    
    def _evaluate_proposal_feasibility(self, proposal: Resolution) -> Dict[str, Any]:
        """
        Evaluate if a proposal is feasible from a scheduling perspective.
        
        This simulates the StaffMatcher's evaluation of a proposed resolution.
        In a full implementation, this would be a message exchange.
        """
        # Check if the proposed changes are feasible
        for change in proposal.changes:
            if change.get("type") == "add":
                employee = change.get("employee")
                target_date = change.get("date")
                shift_code = change.get("shift_code")
                
                if employee and target_date and shift_code:
                    # Check if employee is actually available
                    if not employee.is_available(target_date, shift_code):
                        return {
                            "feasible": False,
                            "reason": f"{employee.name} not available for {shift_code} on {target_date}"
                        }
        
        # Proposal is feasible
        return {"feasible": True}
    
    def get_negotiation_summary(self) -> Dict[str, Any]:
        """Get summary of all negotiations conducted."""
        total_rounds = sum(1 for n in self.negotiation_history)
        successful = sum(1 for n in self.negotiation_history if n.response == "accept")
        countered = sum(1 for n in self.negotiation_history if n.response == "counter")
        rejected = sum(1 for n in self.negotiation_history if n.response == "reject")
        
        return {
            "total_negotiation_rounds": total_rounds,
            "successful_agreements": successful,
            "counter_proposals": countered,
            "rejected_proposals": rejected,
            "success_rate": (successful / total_rounds * 100) if total_rounds > 0 else 0,
        }
    
    def _generate_resolutions(self, violation: Violation) -> List[Resolution]:
        """
        Generate possible resolutions for a violation.
        
        Args:
            violation: The violation to resolve
            
        Returns:
            List of possible resolutions, ranked by impact
        """
        resolutions = []
        
        # Route to appropriate resolution generator
        if violation.constraint_type == ConstraintType.HOURS_MAX:
            resolutions = self._resolve_hours_violation(violation)
        elif violation.constraint_type == ConstraintType.REST_PERIOD:
            resolutions = self._resolve_rest_period_violation(violation)
        elif violation.constraint_type == ConstraintType.AVAILABILITY:
            resolutions = self._resolve_availability_violation(violation)
        elif violation.constraint_type == ConstraintType.SKILL:
            resolutions = self._resolve_skill_violation(violation)
        elif violation.constraint_type == ConstraintType.CONSECUTIVE_DAYS:
            resolutions = self._resolve_consecutive_days_violation(violation)
        elif violation.constraint_type == ConstraintType.MIN_STAFF:
            resolutions = self._resolve_understaffing(violation)
        elif violation.constraint_type == ConstraintType.COVERAGE:
            resolutions = self._resolve_coverage_violation(violation)
        
        return resolutions
    
    def _resolve_hours_violation(self, violation: Violation) -> List[Resolution]:
        """Generate resolutions for exceeding max hours."""
        resolutions = []
        emp_id = violation.affected_entity
        employee = self.employees.get(emp_id)
        if not employee:
            return resolutions
        
        excess_hours = violation.details.get("excess_hours", 0)
        assignments = self.schedule.get_assignments_by_employee(emp_id)
        
        # Sort assignments by ease of reassignment
        for assignment in assignments:
            # Find potential replacements
            replacements = self._find_replacement_employees(assignment)
            
            for replacement in replacements[:3]:  # Top 3 replacements
                resolution = Resolution(
                    description=f"Reassign {employee.name}'s {assignment.shift.shift_type.value} shift on {assignment.shift.date} to {replacement.name}",
                    action="swap",
                    impact_score=self._calculate_swap_impact(assignment, replacement),
                    changes=[{
                        "type": "swap",
                        "assignment": assignment,
                        "new_employee": replacement,
                    }]
                )
                resolutions.append(resolution)
        
        # Option to remove a shift entirely (higher impact)
        if assignments:
            shortest_shift = min(assignments, key=lambda a: a.shift.hours)
            resolution = Resolution(
                description=f"Remove {employee.name}'s shortest shift ({shortest_shift.shift.shift_type.value} on {shortest_shift.shift.date})",
                action="remove",
                impact_score=50 + shortest_shift.shift.hours * 5,
                changes=[{
                    "type": "remove",
                    "assignment": shortest_shift,
                }]
            )
            resolutions.append(resolution)
        
        return resolutions
    
    def _resolve_rest_period_violation(self, violation: Violation) -> List[Resolution]:
        """Generate resolutions for insufficient rest between shifts."""
        resolutions = []
        emp_id = violation.affected_entity
        employee = self.employees.get(emp_id)
        if not employee:
            return resolutions
        
        # Get the two conflicting shifts
        shift_1_str = violation.details.get("shift_1", "")
        shift_2_str = violation.details.get("shift_2", "")
        
        # Find the later shift and try to reassign it
        assignments = self.schedule.get_assignments_by_employee(emp_id)
        affected_date = violation.affected_date
        
        affected_assignment = None
        for a in assignments:
            if a.shift.date == affected_date:
                affected_assignment = a
                break
        
        if affected_assignment:
            replacements = self._find_replacement_employees(affected_assignment)
            
            for replacement in replacements[:3]:
                resolution = Resolution(
                    description=f"Reassign {employee.name}'s shift on {affected_date} to {replacement.name} (rest period violation)",
                    action="swap",
                    impact_score=self._calculate_swap_impact(affected_assignment, replacement) + 10,
                    changes=[{
                        "type": "swap",
                        "assignment": affected_assignment,
                        "new_employee": replacement,
                    }]
                )
                resolutions.append(resolution)
        
        return resolutions
    
    def _resolve_availability_violation(self, violation: Violation) -> List[Resolution]:
        """Generate resolutions for availability conflicts."""
        resolutions = []
        emp_id = violation.affected_entity
        employee = self.employees.get(emp_id)
        affected_date = violation.affected_date
        
        if not employee or not affected_date:
            return resolutions
        
        # Find the problematic assignment
        assignments = self.schedule.get_assignments_by_employee(emp_id)
        affected_assignment = None
        for a in assignments:
            if a.shift.date == affected_date:
                affected_assignment = a
                break
        
        if not affected_assignment:
            return resolutions
        
        # Find replacements
        replacements = self._find_replacement_employees(affected_assignment)
        
        for replacement in replacements[:5]:
            resolution = Resolution(
                description=f"Replace {employee.name} with {replacement.name} for {affected_assignment.shift.shift_type.value} on {affected_date}",
                action="swap",
                impact_score=self._calculate_swap_impact(affected_assignment, replacement),
                changes=[{
                    "type": "swap",
                    "assignment": affected_assignment,
                    "new_employee": replacement,
                }]
            )
            resolutions.append(resolution)
        
        return resolutions
    
    def _resolve_skill_violation(self, violation: Violation) -> List[Resolution]:
        """Generate resolutions for skill mismatch."""
        resolutions = []
        emp_id = violation.affected_entity
        employee = self.employees.get(emp_id)
        affected_date = violation.affected_date
        
        if not employee:
            return resolutions
        
        # Find the assignment with skill mismatch
        assignments = self.schedule.get_assignments_by_employee(emp_id)
        for assignment in assignments:
            if assignment.shift.date == affected_date:
                # Option 1: Find someone qualified for this station
                replacements = self._find_replacement_employees(
                    assignment, 
                    station_filter=assignment.station
                )
                
                for replacement in replacements[:3]:
                    resolution = Resolution(
                        description=f"Replace {employee.name} with {replacement.name} (qualified for {assignment.station.value})",
                        action="swap",
                        impact_score=self._calculate_swap_impact(assignment, replacement),
                        changes=[{
                            "type": "swap",
                            "assignment": assignment,
                            "new_employee": replacement,
                        }]
                    )
                    resolutions.append(resolution)
                
                # Option 2: Move employee to their qualified station
                qualified_station = employee.primary_station
                resolution = Resolution(
                    description=f"Move {employee.name} to {qualified_station.value} instead of {assignment.station.value}",
                    action="modify",
                    impact_score=20,
                    changes=[{
                        "type": "modify_station",
                        "assignment": assignment,
                        "new_station": qualified_station,
                    }]
                )
                resolutions.append(resolution)
        
        return resolutions
    
    def _resolve_consecutive_days_violation(self, violation: Violation) -> List[Resolution]:
        """Generate resolutions for too many consecutive working days."""
        resolutions = []
        emp_id = violation.affected_entity
        employee = self.employees.get(emp_id)
        
        if not employee:
            return resolutions
        
        work_dates = violation.details.get("work_dates", [])
        if not work_dates:
            return resolutions
        
        # Find the middle day(s) to give off
        assignments = self.schedule.get_assignments_by_employee(emp_id)
        sorted_assignments = sorted(
            [a for a in assignments if a.shift.date.isoformat() in work_dates],
            key=lambda a: a.shift.date
        )
        
        if len(sorted_assignments) < 2:
            return resolutions
        
        # Try giving a day off in the middle
        mid_idx = len(sorted_assignments) // 2
        mid_assignment = sorted_assignments[mid_idx]
        
        replacements = self._find_replacement_employees(mid_assignment)
        
        for replacement in replacements[:3]:
            resolution = Resolution(
                description=f"Give {employee.name} day off on {mid_assignment.shift.date} by assigning to {replacement.name}",
                action="swap",
                impact_score=self._calculate_swap_impact(mid_assignment, replacement) + 5,
                changes=[{
                    "type": "swap",
                    "assignment": mid_assignment,
                    "new_employee": replacement,
                }]
            )
            resolutions.append(resolution)
        
        return resolutions
    
    def _resolve_understaffing(self, violation: Violation) -> List[Resolution]:
        """Generate resolutions for understaffing issues."""
        resolutions = []
        affected_date = violation.affected_date
        station_name = violation.details.get("station")
        
        if not affected_date:
            return resolutions
        
        # Find available employees for this date
        station = None
        for s in Station:
            if s.value == station_name:
                station = s
                break
        
        for emp_id, employee in self.employees.items():
            # Check if employee can work this day
            if station and not employee.can_work_station(station):
                continue
            
            # Check availability for any shift
            for shift_code in ["1F", "2F", "3F"]:
                if employee.is_available(affected_date, shift_code):
                    # Check if not already assigned
                    if not self.schedule.is_employee_assigned(emp_id, affected_date):
                        # Check rest period compliance BEFORE proposing
                        shift = Shift.from_code(shift_code, affected_date)
                        if shift and self._check_rest_period_for_new_shift(employee, shift):
                            resolution = Resolution(
                                description=f"Add {employee.name} ({shift_code}) to {station_name or 'schedule'} on {affected_date}",
                                action="add",
                                impact_score=30,
                                changes=[{
                                    "type": "add",
                                    "employee": employee,
                                    "date": affected_date,
                                    "shift_code": shift_code,
                                    "station": station or employee.primary_station,
                                }]
                            )
                            resolutions.append(resolution)
                            break
        
        return resolutions[:5]  # Limit options
    
    def _check_rest_period_for_new_shift(self, employee: Employee, new_shift: Shift) -> bool:
        """
        Check if adding a new shift would violate the 10-hour rest period.
        
        Args:
            employee: The employee to check
            new_shift: The proposed new shift
            
        Returns:
            True if rest period is sufficient, False otherwise
        """
        MIN_REST_HOURS = 10
        
        # Get employee's existing assignments
        assignments = self.schedule.get_assignments_by_employee(employee.id)
        if not assignments:
            return True
        
        new_start = new_shift.get_start_datetime()
        new_end = new_shift.get_end_datetime()
        
        for assignment in assignments:
            existing_shift = assignment.shift
            existing_start = existing_shift.get_start_datetime()
            existing_end = existing_shift.get_end_datetime()
            
            # Check rest before new shift (existing shift ends, new shift starts)
            hours_after_existing = (new_start - existing_end).total_seconds() / 3600
            if 0 < hours_after_existing < MIN_REST_HOURS:
                return False
            
            # Check rest after new shift (new shift ends, existing shift starts)
            hours_before_existing = (existing_start - new_end).total_seconds() / 3600
            if 0 < hours_before_existing < MIN_REST_HOURS:
                return False
        
        return True
    
    def _resolve_coverage_violation(self, violation: Violation) -> List[Resolution]:
        """Generate resolutions for peak coverage issues."""
        # Similar to understaffing but with peak period focus
        return self._resolve_understaffing(violation)
    
    def _find_replacement_employees(self, assignment: Assignment,
                                     station_filter: Optional[Station] = None) -> List[Employee]:
        """
        Find employees who can replace an assignment.
        
        Args:
            assignment: The assignment to find replacements for
            station_filter: Optional - only consider employees qualified for this station
            
        Returns:
            List of suitable replacement employees
        """
        candidates = []
        target_date = assignment.shift.date
        shift_code = assignment.shift.shift_type.value
        station = station_filter or assignment.station
        
        for emp_id, employee in self.employees.items():
            # Skip the current assignee
            if emp_id == assignment.employee.id:
                continue
            
            # Check station qualification
            if not employee.can_work_station(station):
                continue
            
            # Check availability
            if not employee.is_available(target_date, shift_code):
                continue
            
            # Check if not already assigned that day
            if self.schedule.is_employee_assigned(emp_id, target_date):
                continue
            
            # Check hours capacity
            week_num = (target_date - self.schedule.start_date).days // 7
            current_hours = sum(
                a.shift.hours for a in self.schedule.get_assignments_by_employee(emp_id)
                if (a.shift.date - self.schedule.start_date).days // 7 == week_num
            )
            _, max_hours = employee.weekly_hours_target
            
            if (current_hours + assignment.shift.hours) > max_hours:
                continue
            
            # Check rest period compliance
            if not self._check_rest_period_for_new_shift(employee, assignment.shift):
                continue
            
            candidates.append(employee)
        
        # Sort by suitability
        candidates.sort(
            key=lambda e: (
                e.primary_station == station,  # Primary station match
                e.employee_type == EmployeeType.FULL_TIME,  # Full-time preferred
            ),
            reverse=True
        )
        
        return candidates
    
    def _calculate_swap_impact(self, assignment: Assignment, 
                                new_employee: Employee) -> float:
        """
        Calculate the impact score of swapping an assignment.
        Lower is better.
        """
        score = 0.0
        
        # Station mismatch penalty
        if new_employee.primary_station != assignment.station:
            score += 20
        
        # Employee type consideration
        type_scores = {
            EmployeeType.FULL_TIME: 0,
            EmployeeType.PART_TIME: 10,
            EmployeeType.CASUAL: 20,
        }
        score += type_scores.get(new_employee.employee_type, 15)
        
        # Hours impact
        week_num = (assignment.shift.date - self.schedule.start_date).days // 7
        current_hours = sum(
            a.shift.hours for a in self.schedule.get_assignments_by_employee(new_employee.id)
            if (a.shift.date - self.schedule.start_date).days // 7 == week_num
        )
        min_hours, _ = new_employee.weekly_hours_target
        
        # Bonus if it helps meet minimum hours
        if current_hours < min_hours:
            score -= 10
        
        return max(0, score)
    
    def _apply_resolution(self, resolution: Resolution) -> bool:
        """
        Apply a resolution to the schedule.
        
        Args:
            resolution: The resolution to apply
            
        Returns:
            True if successful
        """
        try:
            for change in resolution.changes:
                change_type = change.get("type")
                
                if change_type == "swap":
                    assignment = change.get("assignment")
                    new_employee = change.get("new_employee")
                    
                    if assignment and new_employee:
                        # Remove old assignment
                        self.schedule.remove_assignment(assignment)
                        
                        # Create new assignment
                        new_assignment = Assignment(
                            employee=new_employee,
                            shift=assignment.shift,
                            station=assignment.station
                        )
                        self.schedule.add_assignment(new_assignment)
                
                elif change_type == "remove":
                    assignment = change.get("assignment")
                    if assignment:
                        self.schedule.remove_assignment(assignment)
                
                elif change_type == "add":
                    employee = change.get("employee")
                    target_date = change.get("date")
                    shift_code = change.get("shift_code")
                    station = change.get("station")
                    
                    if all([employee, target_date, shift_code, station]):
                        shift = Shift.from_code(shift_code, target_date)
                        if shift:
                            new_assignment = Assignment(
                                employee=employee,
                                shift=shift,
                                station=station
                            )
                            self.schedule.add_assignment(new_assignment)
                
                elif change_type == "modify_station":
                    assignment = change.get("assignment")
                    new_station = change.get("new_station")
                    
                    if assignment and new_station:
                        # Remove and re-add with new station
                        self.schedule.remove_assignment(assignment)
                        new_assignment = Assignment(
                            employee=assignment.employee,
                            shift=assignment.shift,
                            station=new_station
                        )
                        self.schedule.add_assignment(new_assignment)
            
            # Record in history
            self.resolution_history.append({
                "resolution": str(resolution),
                "changes": len(resolution.changes),
            })
            
            return True
            
        except Exception as e:
            self.log(f"Failed to apply resolution: {e}", "error")
            return False
    
    def _request_approval(self, violation: Violation, resolution: Resolution) -> None:
        """Request human approval for a resolution."""
        self.send(
            MessageType.APPROVAL_REQUEST,
            {
                "violation": violation.description,
                "proposed_resolution": str(resolution),
                "impact_score": resolution.impact_score,
                "risk_level": resolution.risk_level,
                "changes": [str(c) for c in resolution.changes],
            },
            receiver="ApprovalAgent"
        )
    
    def _on_request(self, message: Message) -> None:
        """Handle requests from other agents."""
        content = message.content
        
        if isinstance(content, dict):
            if content.get("type") == "get_resolutions":
                violation_dict = content.get("violation")
                if violation_dict:
                    # Reconstruct violation and generate resolutions
                    # This is simplified - in production, would need full deserialization
                    pass

