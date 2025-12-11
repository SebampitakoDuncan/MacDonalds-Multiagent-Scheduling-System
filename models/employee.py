"""
Employee data model.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set


class EmployeeType(Enum):
    """Employee employment type."""
    FULL_TIME = "Full-Time"
    PART_TIME = "Part-Time"
    CASUAL = "Casual"


class Station(Enum):
    """Work stations in the restaurant."""
    KITCHEN = "Kitchen"
    COUNTER = "Counter"
    MCCAFE = "Multi-Station McCafe"
    DESSERT = "Dessert Station"
    
    @classmethod
    def from_string(cls, value: str) -> "Station":
        """Convert string to Station enum."""
        mapping = {
            "kitchen": cls.KITCHEN,
            "counter": cls.COUNTER,
            "multi-station mccafe": cls.MCCAFE,
            "mccafe": cls.MCCAFE,
            "dessert station": cls.DESSERT,
            "dessert": cls.DESSERT,
        }
        return mapping.get(value.lower().strip(), cls.COUNTER)


@dataclass
class Employee:
    """
    Employee model representing a staff member.
    
    Attributes:
        id: Unique employee identifier
        name: Full name
        employee_type: Full-time, Part-time, or Casual
        primary_station: Main work station
        availability: Dict mapping date to list of available shift codes
        skills: Set of stations the employee is trained for
        weekly_hours_target: Target hours based on employment type
        current_week_hours: Hours assigned in current week
    """
    id: str
    name: str
    employee_type: EmployeeType
    primary_station: Station
    availability: Dict[date, List[str]] = field(default_factory=dict)
    skills: Set[Station] = field(default_factory=set)
    weekly_hours_target: tuple = field(default=(0, 0))  # (min, max)
    current_week_hours: float = 0.0
    
    def __post_init__(self):
        """Set up derived attributes."""
        # Add primary station to skills
        self.skills.add(self.primary_station)
        
        # Set weekly hours targets based on employee type
        if self.weekly_hours_target == (0, 0):
            self.weekly_hours_target = self._get_hours_target()
    
    def _get_hours_target(self) -> tuple:
        """Get min/max weekly hours based on employee type."""
        targets = {
            EmployeeType.FULL_TIME: (35, 38),
            EmployeeType.PART_TIME: (20, 32),
            EmployeeType.CASUAL: (8, 24),
        }
        return targets.get(self.employee_type, (0, 40))
    
    def is_available(self, target_date: date, shift_code: str) -> bool:
        """
        Check if employee is available for a specific shift on a date.
        
        Args:
            target_date: The date to check
            shift_code: The shift code (1F, 2F, 3F)
            
        Returns:
            True if available, False otherwise
        """
        if target_date not in self.availability:
            return False
        
        available_shifts = self.availability[target_date]
        
        # "/" means not available
        if "/" in available_shifts or not available_shifts:
            return False
        
        # Check if the specific shift is available
        return shift_code in available_shifts
    
    def get_available_shifts(self, target_date: date) -> List[str]:
        """Get list of available shift codes for a date."""
        if target_date not in self.availability:
            return []
        
        shifts = self.availability[target_date]
        if "/" in shifts:
            return []
        return [s for s in shifts if s != "/"]
    
    def can_work_station(self, station: Station) -> bool:
        """Check if employee is trained for a station."""
        return station in self.skills
    
    def hours_remaining(self) -> float:
        """Get remaining hours until max for the week."""
        return max(0, self.weekly_hours_target[1] - self.current_week_hours)
    
    def needs_more_hours(self) -> bool:
        """Check if employee needs more hours to meet minimum."""
        return self.current_week_hours < self.weekly_hours_target[0]
    
    def can_add_hours(self, hours: float) -> bool:
        """Check if adding hours would exceed maximum."""
        return (self.current_week_hours + hours) <= self.weekly_hours_target[1]
    
    def __str__(self) -> str:
        return f"{self.name} ({self.employee_type.value}, {self.primary_station.value})"
    
    def __hash__(self):
        return hash(self.id)
    
    def __eq__(self, other):
        if isinstance(other, Employee):
            return self.id == other.id
        return False


# =============================================================================
# MANAGER MODEL
# =============================================================================

class ManagerPosition(Enum):
    """Manager position levels."""
    RESTAURANT_GM = "Restaurant General Manager"
    FIRST_ASSISTANT = "1st Assistant Manager"
    SECOND_ASSISTANT = "2nd Assistant Manager"
    TRAINEE = "Management Trainee"


@dataclass
class ManagerShift:
    """
    A single manager shift assignment.
    
    Manager shifts are pre-defined monthly and serve as the foundation
    that crew schedules are built around.
    """
    manager_name: str
    position: ManagerPosition
    shift_date: date
    shift_code: str  # S, 1F, 2F, 3F, SC, M, /, NA
    
    # Shift time details (derived from shift code)
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    hours: float = 0.0
    
    def __post_init__(self):
        """Set shift times based on code."""
        shift_times = {
            "S": ("06:30", "15:00", 8.5),    # Day/Opening shift
            "1F": ("06:30", "15:30", 9.0),   # First half - morning
            "2F": ("14:00", "23:00", 9.0),   # Second half - afternoon/closing
            "3F": ("08:00", "20:00", 12.0),  # Full day
            "SC": ("11:00", "20:00", 9.0),   # Shift change - peak overlap
            "M": ("09:00", "17:00", 8.0),    # Meeting/training
            "/": (None, None, 0.0),          # Day off
            "NA": (None, None, 0.0),         # Not available
        }
        
        if self.shift_code in shift_times:
            self.start_time, self.end_time, self.hours = shift_times[self.shift_code]
    
    def is_working(self) -> bool:
        """Check if this is an actual working shift (not off/NA)."""
        return self.shift_code not in ["/", "NA"]
    
    def covers_opening(self) -> bool:
        """Check if shift covers opening (06:30)."""
        return self.shift_code in ["S", "1F"]
    
    def covers_closing(self) -> bool:
        """Check if shift covers closing (23:00)."""
        return self.shift_code == "2F"
    
    def covers_lunch_peak(self) -> bool:
        """Check if shift covers lunch peak (11:00-14:00)."""
        return self.shift_code in ["S", "1F", "3F", "SC"]
    
    def covers_dinner_peak(self) -> bool:
        """Check if shift covers dinner peak (17:00-21:00)."""
        return self.shift_code in ["2F", "3F", "SC"]
    
    def __str__(self) -> str:
        if self.is_working():
            return f"{self.manager_name} ({self.shift_code}: {self.start_time}-{self.end_time})"
        return f"{self.manager_name} (OFF)"


@dataclass
class Manager:
    """
    Manager model with pre-defined monthly roster.
    
    Unlike crew members, managers have fixed monthly schedules
    that are planned in advance.
    """
    name: str
    position: ManagerPosition
    shifts: Dict[date, ManagerShift] = field(default_factory=dict)
    
    def get_shift(self, target_date: date) -> Optional[ManagerShift]:
        """Get the manager's shift for a specific date."""
        return self.shifts.get(target_date)
    
    def is_working(self, target_date: date) -> bool:
        """Check if manager is working on a specific date."""
        shift = self.get_shift(target_date)
        return shift is not None and shift.is_working()
    
    def get_weekly_hours(self, week_start: date) -> float:
        """Calculate total hours for a week starting from week_start."""
        total = 0.0
        for i in range(7):
            day = week_start + timedelta(days=i)
            shift = self.get_shift(day)
            if shift and shift.is_working():
                total += shift.hours
        return total
    
    def __str__(self) -> str:
        return f"{self.name} ({self.position.value})"


@dataclass
class ManagerCoverage:
    """
    Manager coverage summary for a specific date.
    
    Used to ensure crew scheduling complements manager availability.
    """
    date: date
    managers_on_duty: List[ManagerShift] = field(default_factory=list)
    
    @property
    def has_opening_coverage(self) -> bool:
        """At least one manager covers opening."""
        return any(m.covers_opening() for m in self.managers_on_duty)
    
    @property
    def has_closing_coverage(self) -> bool:
        """At least one manager covers closing."""
        return any(m.covers_closing() for m in self.managers_on_duty)
    
    @property
    def has_lunch_peak_coverage(self) -> bool:
        """At least one manager covers lunch peak."""
        return any(m.covers_lunch_peak() for m in self.managers_on_duty)
    
    @property
    def has_dinner_peak_coverage(self) -> bool:
        """At least one manager covers dinner peak."""
        return any(m.covers_dinner_peak() for m in self.managers_on_duty)
    
    @property
    def manager_count(self) -> int:
        """Number of managers working."""
        return len([m for m in self.managers_on_duty if m.is_working()])
    
    @property
    def total_manager_hours(self) -> float:
        """Total manager hours for the day."""
        return sum(m.hours for m in self.managers_on_duty if m.is_working())
    
    def get_coverage_gaps(self) -> List[str]:
        """Identify any coverage gaps."""
        gaps = []
        if not self.has_opening_coverage:
            gaps.append("Opening (06:30)")
        if not self.has_closing_coverage:
            gaps.append("Closing (23:00)")
        if not self.has_lunch_peak_coverage:
            gaps.append("Lunch Peak (11:00-14:00)")
        if not self.has_dinner_peak_coverage:
            gaps.append("Dinner Peak (17:00-21:00)")
        return gaps

