"""
Schedule and Assignment models.
"""
from dataclasses import dataclass, field
from datetime import date, time, datetime
from typing import Dict, List, Optional, Set, Tuple
from collections import defaultdict

from .employee import Employee, Station
from .shift import Shift, ShiftType, TimeSlot, PEAK_PERIODS


@dataclass
class Assignment:
    """
    Represents an employee assignment to a shift.
    
    Attributes:
        employee: The assigned employee
        shift: The shift they're assigned to
        station: The station they'll work
        is_locked: Whether this assignment is locked (cannot be changed)
        notes: Any notes about this assignment
    """
    employee: Employee
    shift: Shift
    station: Station
    is_locked: bool = False
    notes: str = ""
    
    def __str__(self) -> str:
        return (
            f"{self.employee.name} → {self.shift.shift_type.value} "
            f"on {self.shift.date.strftime('%a %d/%m')} at {self.station.value}"
        )
    
    def __hash__(self):
        return hash((self.employee.id, self.shift.date, self.shift.shift_type))


@dataclass
class Schedule:
    """
    Complete schedule containing all assignments.
    
    Attributes:
        start_date: First day of the schedule period
        end_date: Last day of the schedule period
        assignments: List of all assignments
        store_id: Store identifier
    """
    start_date: date
    end_date: date
    assignments: List[Assignment] = field(default_factory=list)
    store_id: str = "Store_1"
    
    # Indexes for fast lookup
    _by_date: Dict[date, List[Assignment]] = field(default_factory=lambda: defaultdict(list))
    _by_employee: Dict[str, List[Assignment]] = field(default_factory=lambda: defaultdict(list))
    _by_station: Dict[Station, List[Assignment]] = field(default_factory=lambda: defaultdict(list))
    
    def add_assignment(self, assignment: Assignment) -> None:
        """Add an assignment to the schedule."""
        self.assignments.append(assignment)
        self._by_date[assignment.shift.date].append(assignment)
        self._by_employee[assignment.employee.id].append(assignment)
        self._by_station[assignment.station].append(assignment)
    
    def remove_assignment(self, assignment: Assignment) -> bool:
        """Remove an assignment from the schedule."""
        if assignment.is_locked:
            return False
        
        if assignment in self.assignments:
            self.assignments.remove(assignment)
            self._by_date[assignment.shift.date].remove(assignment)
            self._by_employee[assignment.employee.id].remove(assignment)
            self._by_station[assignment.station].remove(assignment)
            return True
        return False
    
    def get_assignments_by_date(self, target_date: date) -> List[Assignment]:
        """Get all assignments for a specific date."""
        return self._by_date.get(target_date, [])
    
    def get_assignments_by_employee(self, employee_id: str) -> List[Assignment]:
        """Get all assignments for a specific employee."""
        return self._by_employee.get(employee_id, [])
    
    def get_assignments_by_station(self, station: Station) -> List[Assignment]:
        """Get all assignments for a specific station."""
        return self._by_station.get(station, [])
    
    def get_employee_hours(self, employee_id: str, 
                           week_start: Optional[date] = None) -> float:
        """Calculate total hours for an employee, optionally for a specific week."""
        assignments = self.get_assignments_by_employee(employee_id)
        
        if week_start:
            week_end = week_start + timedelta(days=6)
            assignments = [a for a in assignments 
                          if week_start <= a.shift.date <= week_end]
        
        return sum(a.shift.hours for a in assignments)
    
    def get_coverage(self, target_date: date, 
                     time_slot: TimeSlot,
                     station: Optional[Station] = None) -> int:
        """
        Get staff coverage count for a date and time slot.
        
        Args:
            target_date: The date to check
            time_slot: The time window to check
            station: Optional - filter by station
            
        Returns:
            Number of staff covering the time slot
        """
        assignments = self.get_assignments_by_date(target_date)
        
        if station:
            assignments = [a for a in assignments if a.station == station]
        
        # Count assignments that overlap with the time slot
        return sum(1 for a in assignments if a.shift.overlaps_time_slot(time_slot))
    
    def get_coverage_by_station(self, target_date: date, 
                                 time_slot: TimeSlot) -> Dict[Station, int]:
        """Get coverage breakdown by station for a date and time slot."""
        coverage = {}
        for station in Station:
            coverage[station] = self.get_coverage(target_date, time_slot, station)
        return coverage
    
    def get_peak_coverage(self, target_date: date) -> Dict[str, int]:
        """Get coverage for all peak periods on a date."""
        return {
            name: self.get_coverage(target_date, slot)
            for name, slot in PEAK_PERIODS.items()
        }
    
    def get_dates_in_range(self) -> List[date]:
        """Get all dates in the schedule range."""
        dates = []
        current = self.start_date
        while current <= self.end_date:
            dates.append(current)
            current += timedelta(days=1)
        return dates
    
    def is_employee_assigned(self, employee_id: str, target_date: date) -> bool:
        """Check if employee is already assigned on a date."""
        return any(
            a.shift.date == target_date 
            for a in self.get_assignments_by_employee(employee_id)
        )
    
    def get_last_shift_end(self, employee_id: str, 
                           before_date: date) -> Optional[datetime]:
        """Get the end time of employee's last shift before a date."""
        assignments = self.get_assignments_by_employee(employee_id)
        prior_assignments = [
            a for a in assignments 
            if a.shift.date < before_date
        ]
        
        if not prior_assignments:
            return None
        
        last_assignment = max(prior_assignments, key=lambda a: a.shift.get_end_datetime())
        return last_assignment.shift.get_end_datetime()
    
    def get_consecutive_days(self, employee_id: str, 
                             as_of_date: date) -> int:
        """Count consecutive working days for an employee up to a date."""
        assignments = self.get_assignments_by_employee(employee_id)
        work_dates = {a.shift.date for a in assignments}
        
        consecutive = 0
        check_date = as_of_date
        
        while check_date in work_dates:
            consecutive += 1
            check_date -= timedelta(days=1)
        
        return consecutive
    
    def summary(self) -> dict:
        """Get a summary of the schedule."""
        total_hours = sum(a.shift.hours for a in self.assignments)
        unique_employees = len(set(a.employee.id for a in self.assignments))
        
        return {
            "total_assignments": len(self.assignments),
            "unique_employees": unique_employees,
            "total_hours": total_hours,
            "date_range": f"{self.start_date} to {self.end_date}",
            "days": (self.end_date - self.start_date).days + 1,
        }
    
    def __str__(self) -> str:
        summary = self.summary()
        return (
            f"Schedule: {summary['date_range']} | "
            f"{summary['total_assignments']} assignments | "
            f"{summary['unique_employees']} employees | "
            f"{summary['total_hours']:.1f} hours"
        )


# Import timedelta for use in this module
from datetime import timedelta

