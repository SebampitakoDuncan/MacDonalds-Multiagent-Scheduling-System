"""
Staff Matcher Agent - Assigns employees to shifts based on availability and skills.

This agent implements a BIDDING/AUCTION mechanism for shift assignments.
Employees "bid" for shifts based on their qualifications, needs, and preferences.
The highest bidder wins the shift, creating emergent fairness behavior.
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict
from dataclasses import dataclass
import random
import sys
from pathlib import Path

from .base_agent import BaseAgent
from communication.message import Message, MessageType
from communication.message_bus import MessageBus
from models.employee import Employee, EmployeeType, Station
from models.shift import Shift, ShiftType
from models.schedule import Schedule, Assignment
from models.store import Store

# Import profiling
sys.path.insert(0, str(Path(__file__).parent.parent))
from benchmark import profile_function


@dataclass
class EmployeeBid:
    """
    Represents an employee's bid for a shift in the auction mechanism.
    
    The bidding system enables:
    - Fair distribution of shifts based on need
    - Skill-appropriate assignments
    - Employee preference consideration
    - Emergent collaborative behavior
    """
    employee_id: str
    employee_name: str
    shift_date: date
    shift_code: str
    station: Station
    
    # Bid components (higher = stronger bid)
    skill_bid: float       # How qualified for this station
    hours_bid: float       # How much they need the hours
    fairness_bid: float    # Boost for under-scheduled
    preference_bid: float  # Shift timing preference
    
    # Total score (sum of all components)
    total_score: float
    
    def __str__(self) -> str:
        return (
            f"Bid({self.employee_name}: {self.total_score:.1f} = "
            f"skill:{self.skill_bid:.0f} + hours:{self.hours_bid:.0f} + "
            f"fair:{self.fairness_bid:.0f} + pref:{self.preference_bid:.0f})"
        )


class StaffMatcherAgent(BaseAgent):
    """
    Agent responsible for matching employees to shifts.
    
    Responsibilities:
    - Assign employees based on availability
    - Match skills to station requirements
    - Balance workload across employees
    - Prioritize full-time employees for core shifts
    - Fill gaps with part-time and casual staff
    """
    
    def __init__(self, message_bus: MessageBus):
        super().__init__("StaffMatcher", message_bus)
        self.schedule: Optional[Schedule] = None
        self.employees: List[Employee] = []
        self.store: Optional[Store] = None
        self.demand_forecast: Dict[date, Dict] = {}
        self.manager_coverage: Dict = {}  # Manager coverage from monthly roster
        
        # Track assignments during matching
        self._employee_hours: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        self._daily_assignments: Dict[date, List[Assignment]] = defaultdict(list)
        
    @profile_function
    def execute(self, 
                employees: List[Employee],
                store: Store,
                demand_forecast: Dict[date, Dict],
                start_date: date,
                end_date: date,
                manager_coverage: Optional[Dict] = None,
                **kwargs) -> Schedule:
        """
        Create initial schedule by matching employees to shifts.
        
        Manager-First Scheduling:
        Managers are scheduled monthly (fixed), crew is scheduled weekly.
        This method schedules crew around the pre-defined manager coverage.
        
        Args:
            employees: List of available employees (crew members)
            store: Store configuration
            demand_forecast: Staffing requirements by date
            start_date: First day of schedule
            end_date: Last day of schedule
            manager_coverage: Pre-defined manager shifts (from monthly roster)
            
        Returns:
            Schedule with initial crew assignments
        """
        self.employees = employees
        self.store = store
        self.demand_forecast = demand_forecast
        self.manager_coverage = manager_coverage or {}
        
        # Initialize schedule
        self.schedule = Schedule(start_date=start_date, end_date=end_date, store_id=store.id)
        
        # Reset tracking
        self._employee_hours = defaultdict(lambda: defaultdict(float))
        self._daily_assignments = defaultdict(list)
        
        self.log(f"Starting staff matching for {len(employees)} employees, {store.name}")
        if self.manager_coverage:
            self.log(f"Manager coverage loaded for {len(self.manager_coverage)} days")
        
        # Match employees to shifts for each day
        current_date = start_date
        while current_date <= end_date:
            self._match_day(current_date)
            current_date += timedelta(days=1)
        
        # Report results
        summary = self.schedule.summary()
        self.send(
            MessageType.SCHEDULE,
            {
                "status": "initial_schedule_created",
                "schedule_summary": summary,
                "assignments_count": len(self.schedule.assignments),
            },
            receiver="Coordinator"
        )
        
        self.log(f"Initial matching complete: {summary['total_assignments']} assignments", "success")
        return self.schedule
    
    def _match_day(self, target_date: date) -> None:
        """
        Match employees to shifts for a single day.
        
        Args:
            target_date: The date to schedule
        """
        day_forecast = self.demand_forecast.get(target_date, {})
        shift_requirements = day_forecast.get("shift_requirements", {})
        
        # Get active stations for this store
        active_stations = self.store.get_active_stations()
        
        # Process each shift type in order of priority
        shift_priority = ["1F", "3F", "2F"]  # Morning first, then full day, then evening
        
        for shift_code in shift_priority:
            shift_reqs = shift_requirements.get(shift_code, {})
            
            for station in active_stations:
                station_name = station.value
                required_count = shift_reqs.get(station_name, 0)
                
                if required_count > 0:
                    self._fill_station_shift(
                        target_date, 
                        shift_code, 
                        station, 
                        required_count
                    )
    
    def _fill_station_shift(self, target_date: date, shift_code: str,
                            station: Station, required_count: int) -> int:
        """
        Fill a specific station/shift combination with employees.
        
        Args:
            target_date: Date of the shift
            shift_code: Shift code (1F, 2F, 3F)
            station: Station to staff
            required_count: Number of staff needed
            
        Returns:
            Number of positions filled
        """
        filled = 0
        
        # Get candidates in priority order
        candidates = self._get_ranked_candidates(target_date, shift_code, station)
        
        for employee in candidates:
            if filled >= required_count:
                break
            
            # Try to assign
            if self._can_assign(employee, target_date, shift_code):
                assignment = self._create_assignment(employee, target_date, shift_code, station)
                if assignment:
                    self.schedule.add_assignment(assignment)
                    self._record_assignment(employee, target_date, assignment)
                    filled += 1
        
        if filled < required_count:
            self.log(
                f"Understaffed: {station.value} on {target_date} {shift_code} "
                f"({filled}/{required_count})",
                "warning"
            )
        
        return filled
    
    def _get_ranked_candidates(self, target_date: date, shift_code: str,
                                station: Station) -> List[Employee]:
        """
        Get employees ranked by suitability for a shift.
        
        Ranking criteria:
        1. Primary station match
        2. Employee type (Full-time > Part-time > Casual)
        3. Hours needed to meet minimum
        4. Availability
        
        Args:
            target_date: Date of shift
            shift_code: Shift code
            station: Target station
            
        Returns:
            Sorted list of candidate employees
        """
        candidates = []
        
        for employee in self.employees:
            # Check basic availability
            if not employee.is_available(target_date, shift_code):
                continue
            
            # Check if already assigned this day
            if self.schedule.is_employee_assigned(employee.id, target_date):
                continue
            
            # Check station qualification
            if not employee.can_work_station(station):
                continue
            
            # Calculate priority score
            score = self._calculate_candidate_score(employee, target_date, shift_code, station)
            candidates.append((score, employee))
        
        # Sort by score (higher is better)
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        return [emp for _, emp in candidates]
    
    def _calculate_candidate_score(self, employee: Employee, target_date: date,
                                    shift_code: str, station: Station) -> float:
        """
        Calculate a priority score for assigning an employee using BIDDING MECHANISM.
        
        This implements an auction-style allocation where employees "bid" for shifts.
        The bid is calculated based on multiple factors that represent the employee's
        "desire" and "suitability" for the shift.
        
        Bidding Factors:
        - Skill Match Bid: How well qualified they are
        - Availability Bid: How available they are
        - Hours Need Bid: How much they need the hours
        - Fairness Bid: Boost for under-scheduled employees
        - Preference Bid: Shift timing preference simulation
        
        Higher bid = better candidate (wins the "auction")
        """
        bid = self._generate_employee_bid(employee, target_date, shift_code, station)
        return bid.total_score
    
    def _generate_employee_bid(self, employee: Employee, target_date: date,
                               shift_code: str, station: Station) -> 'EmployeeBid':
        """
        Generate a bid for an employee competing for a shift.
        
        This simulates an auction mechanism where employees compete based on
        various factors. The system then selects the highest bidder.
        """
        # Initialize bid components
        skill_bid = 0.0
        hours_bid = 0.0
        fairness_bid = 0.0
        preference_bid = 0.0
        
        # === SKILL MATCH BID ===
        # Primary station match gets highest bid
        if employee.primary_station == station:
            skill_bid = 100.0
        elif station in employee.skills:
            skill_bid = 60.0  # Cross-trained
        
        # === EMPLOYEE TYPE BID ===
        # Full-time employees bid higher (they need guaranteed hours)
        type_bids = {
            EmployeeType.FULL_TIME: 50.0,
            EmployeeType.PART_TIME: 30.0,
            EmployeeType.CASUAL: 15.0,
        }
        hours_bid += type_bids.get(employee.employee_type, 0)
        
        # === HOURS NEED BID ===
        # Employees who need hours bid more aggressively
        week_num = self._get_week_number(target_date)
        current_hours = self._employee_hours[employee.id][week_num]
        min_hours, max_hours = employee.weekly_hours_target
        
        if current_hours < min_hours:
            # Below minimum - high bid
            hours_shortfall = min_hours - current_hours
            hours_bid += min(30.0, hours_shortfall * 2)  # Up to +30
        elif current_hours < max_hours:
            # Has capacity - moderate bid
            hours_bid += 10.0
        
        # === FAIRNESS BID ===
        # Under-scheduled employees get a fairness boost
        avg_hours = self._get_average_hours_this_week(week_num)
        if current_hours < avg_hours * 0.7:
            fairness_bid = 25.0  # Significant boost for fairness
        elif current_hours < avg_hours:
            fairness_bid = 10.0
        
        # === PREFERENCE BID ===
        # Simulate employee preference for shift timing
        is_weekend = target_date.weekday() >= 5
        if shift_code == "1F":  # Morning shift
            preference_bid = 5.0  # Slight preference
        elif shift_code == "2F" and not is_weekend:
            preference_bid = 3.0  # Evening weekday
        elif is_weekend:
            preference_bid = -5.0  # Weekend penalty (unless needed)
            if current_hours < min_hours:
                preference_bid = 10.0  # But bid high if need hours
        
        # === RANDOMIZATION ===
        # Small random factor to break ties and add variety
        random_factor = random.uniform(0, 5)
        
        # Create and return the bid
        total = skill_bid + hours_bid + fairness_bid + preference_bid + random_factor
        
        return EmployeeBid(
            employee_id=employee.id,
            employee_name=employee.name,
            shift_date=target_date,
            shift_code=shift_code,
            station=station,
            skill_bid=skill_bid,
            hours_bid=hours_bid,
            fairness_bid=fairness_bid,
            preference_bid=preference_bid,
            total_score=total
        )
    
    def _get_average_hours_this_week(self, week_num: int) -> float:
        """Calculate average hours assigned this week across all employees."""
        all_hours = [
            self._employee_hours[emp.id][week_num] 
            for emp in self.employees
        ]
        if not all_hours:
            return 0.0
        return sum(all_hours) / len(all_hours)
    
    def _can_assign(self, employee: Employee, target_date: date, shift_code: str) -> bool:
        """
        Check if an employee can be assigned to a shift.
        
        Checks:
        - Availability
        - Not already assigned that day
        - Weekly hours limit not exceeded
        - Rest period between shifts (10 hours minimum)
        """
        # Check availability
        if not employee.is_available(target_date, shift_code):
            return False
        
        # Check not already assigned
        if self.schedule.is_employee_assigned(employee.id, target_date):
            return False
        
        # Check weekly hours
        shift = Shift.from_code(shift_code, target_date)
        if not shift:
            return False
        
        week_num = self._get_week_number(target_date)
        current_hours = self._employee_hours[employee.id][week_num]
        _, max_hours = employee.weekly_hours_target
        
        if (current_hours + shift.hours) > max_hours:
            return False
        
        # Check rest period (10 hours minimum between shifts)
        if not self._check_rest_period(employee, shift):
            return False
        
        return True
    
    def _check_rest_period(self, employee: Employee, new_shift: Shift) -> bool:
        """
        Check if there's at least 10 hours rest between shifts.
        
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
    
    def _create_assignment(self, employee: Employee, target_date: date,
                           shift_code: str, station: Station) -> Optional[Assignment]:
        """Create an assignment for an employee."""
        shift = Shift.from_code(shift_code, target_date)
        if not shift:
            return None
        
        return Assignment(
            employee=employee,
            shift=shift,
            station=station
        )
    
    def _record_assignment(self, employee: Employee, target_date: date,
                           assignment: Assignment) -> None:
        """Record an assignment for tracking purposes."""
        week_num = self._get_week_number(target_date)
        self._employee_hours[employee.id][week_num] += assignment.shift.hours
        self._daily_assignments[target_date].append(assignment)
    
    def _get_week_number(self, target_date: date) -> int:
        """Get week number (0 or 1) for the schedule period."""
        if not self.schedule:
            return 0
        days_from_start = (target_date - self.schedule.start_date).days
        return days_from_start // 7
    
    def update_assignment(self, old_assignment: Assignment, 
                          new_employee: Employee) -> Optional[Assignment]:
        """
        Update an assignment with a new employee.
        Called by Conflict Resolver when fixing issues.
        
        Args:
            old_assignment: The assignment to update
            new_employee: The new employee to assign
            
        Returns:
            New assignment or None if failed
        """
        if old_assignment.is_locked:
            return None
        
        # Remove old assignment
        self.schedule.remove_assignment(old_assignment)
        
        # Reverse the hours tracking
        week_num = self._get_week_number(old_assignment.shift.date)
        self._employee_hours[old_assignment.employee.id][week_num] -= old_assignment.shift.hours
        
        # Create new assignment
        new_assignment = Assignment(
            employee=new_employee,
            shift=old_assignment.shift,
            station=old_assignment.station
        )
        
        self.schedule.add_assignment(new_assignment)
        self._record_assignment(new_employee, new_assignment.shift.date, new_assignment)
        
        # Notify about the change
        self.send(
            MessageType.DATA,
            {
                "type": "assignment_updated",
                "old_employee": old_assignment.employee.name,
                "new_employee": new_employee.name,
                "shift": str(old_assignment.shift),
                "station": old_assignment.station.value,
            },
            receiver="Coordinator"
        )
        
        return new_assignment
    
    def add_assignment(self, employee: Employee, target_date: date,
                       shift_code: str, station: Station) -> Optional[Assignment]:
        """
        Add a new assignment to the schedule.
        
        Args:
            employee: Employee to assign
            target_date: Date of shift
            shift_code: Shift code
            station: Station to work
            
        Returns:
            New assignment or None if failed
        """
        if not self._can_assign(employee, target_date, shift_code):
            return None
        
        assignment = self._create_assignment(employee, target_date, shift_code, station)
        if assignment:
            self.schedule.add_assignment(assignment)
            self._record_assignment(employee, target_date, assignment)
        
        return assignment
    
    def _on_request(self, message: Message) -> None:
        """Handle requests from other agents."""
        content = message.content
        
        if isinstance(content, dict):
            request_type = content.get("type")
            
            if request_type == "get_schedule":
                self.respond(message, {"schedule": self.schedule})
            
            elif request_type == "update_assignment":
                old_assignment = content.get("old_assignment")
                new_employee = content.get("new_employee")
                result = self.update_assignment(old_assignment, new_employee)
                self.respond(message, {"success": result is not None, "assignment": result})
            
            elif request_type == "add_assignment":
                result = self.add_assignment(
                    content.get("employee"),
                    content.get("date"),
                    content.get("shift_code"),
                    content.get("station")
                )
                self.respond(message, {"success": result is not None, "assignment": result})
            
            elif request_type == "get_employee_hours":
                emp_id = content.get("employee_id")
                week_num = content.get("week", 0)
                hours = self._employee_hours.get(emp_id, {}).get(week_num, 0)
                self.respond(message, {"hours": hours})

