"""
Shift and time slot models.
"""
from dataclasses import dataclass, field
from datetime import date, time, datetime, timedelta
from enum import Enum
from typing import Optional, List


class ShiftType(Enum):
    """Types of shifts available."""
    FIRST_HALF = "1F"      # 06:30 - 15:30 (9 hours)
    SECOND_HALF = "2F"     # 14:00 - 23:00 (9 hours)
    FULL_DAY = "3F"        # 08:00 - 20:00 (12 hours)
    DAY_SHIFT = "S"        # 06:30 - 15:00 (8.5 hours) - Management
    SHIFT_CHANGE = "SC"    # 11:00 - 20:00 (9 hours) - Management
    MEETING = "M"          # Varies (8 hours) - Management
    
    @classmethod
    def from_code(cls, code: str) -> Optional["ShiftType"]:
        """Convert shift code to ShiftType."""
        mapping = {
            "1F": cls.FIRST_HALF,
            "2F": cls.SECOND_HALF,
            "3F": cls.FULL_DAY,
            "S": cls.DAY_SHIFT,
            "SC": cls.SHIFT_CHANGE,
            "M": cls.MEETING,
        }
        return mapping.get(code.upper().strip())


@dataclass
class TimeSlot:
    """
    Represents a time window within a day.
    
    Attributes:
        start: Start time
        end: End time
        is_peak: Whether this is a peak period
        name: Human-readable name (e.g., "Lunch Peak")
    """
    start: time
    end: time
    is_peak: bool = False
    name: str = ""
    
    def duration_hours(self) -> float:
        """Calculate duration in hours."""
        start_minutes = self.start.hour * 60 + self.start.minute
        end_minutes = self.end.hour * 60 + self.end.minute
        return (end_minutes - start_minutes) / 60
    
    def overlaps(self, other: "TimeSlot") -> bool:
        """Check if this time slot overlaps with another."""
        return self.start < other.end and other.start < self.end
    
    def contains_time(self, t: time) -> bool:
        """Check if a time falls within this slot."""
        return self.start <= t < self.end


@dataclass
class Shift:
    """
    Represents a work shift.
    
    Attributes:
        shift_type: The type of shift
        date: The date of the shift
        start_time: When the shift starts
        end_time: When the shift ends
        hours: Total hours for this shift
        break_minutes: Break time in minutes
    """
    shift_type: ShiftType
    date: date
    start_time: time
    end_time: time
    hours: float
    break_minutes: int = 30  # 30 min unpaid break for shifts > 5 hours
    
    @classmethod
    def from_code(cls, code: str, shift_date: date) -> Optional["Shift"]:
        """
        Create a Shift from a shift code and date.
        
        Args:
            code: Shift code (1F, 2F, 3F, etc.)
            shift_date: The date for this shift
            
        Returns:
            Shift instance or None if code is invalid/unavailable
        """
        if code in ["/", "NA", ""]:
            return None
            
        shift_configs = {
            "1F": (time(6, 30), time(15, 30), 9.0),
            "2F": (time(14, 0), time(23, 0), 9.0),
            "3F": (time(8, 0), time(20, 0), 12.0),
            "S": (time(6, 30), time(15, 0), 8.5),
            "SC": (time(11, 0), time(20, 0), 9.0),
            "M": (time(9, 0), time(17, 0), 8.0),
        }
        
        config = shift_configs.get(code.upper().strip())
        if not config:
            return None
            
        start_time, end_time, hours = config
        shift_type = ShiftType.from_code(code)
        
        if not shift_type:
            return None
            
        return cls(
            shift_type=shift_type,
            date=shift_date,
            start_time=start_time,
            end_time=end_time,
            hours=hours,
            break_minutes=30 if hours > 5 else 0
        )
    
    def get_end_datetime(self) -> datetime:
        """Get the datetime when this shift ends."""
        return datetime.combine(self.date, self.end_time)
    
    def get_start_datetime(self) -> datetime:
        """Get the datetime when this shift starts."""
        return datetime.combine(self.date, self.start_time)
    
    def hours_until_next(self, next_shift: "Shift") -> float:
        """Calculate rest hours between this shift and the next."""
        this_end = self.get_end_datetime()
        next_start = next_shift.get_start_datetime()
        
        delta = next_start - this_end
        return delta.total_seconds() / 3600
    
    def covers_time_slot(self, slot: TimeSlot) -> bool:
        """Check if this shift covers a time slot."""
        return self.start_time <= slot.start and self.end_time >= slot.end
    
    def overlaps_time_slot(self, slot: TimeSlot) -> bool:
        """Check if this shift overlaps with a time slot."""
        return self.start_time < slot.end and slot.start < self.end_time
    
    def __str__(self) -> str:
        return (
            f"{self.shift_type.value} on {self.date.strftime('%a %d/%m')}: "
            f"{self.start_time.strftime('%H:%M')}-{self.end_time.strftime('%H:%M')} "
            f"({self.hours}h)"
        )


# Pre-defined peak time slots
PEAK_PERIODS = {
    "breakfast": TimeSlot(time(6, 30), time(9, 30), is_peak=True, name="Breakfast Peak"),
    "lunch": TimeSlot(time(11, 0), time(14, 0), is_peak=True, name="Lunch Peak"),
    "dinner": TimeSlot(time(17, 0), time(21, 0), is_peak=True, name="Dinner Peak"),
}

SERVICE_PERIODS = {
    "opening": TimeSlot(time(6, 0), time(11, 0), name="Opening/Breakfast"),
    "lunch": TimeSlot(time(11, 0), time(15, 0), is_peak=True, name="Lunch"),
    "afternoon": TimeSlot(time(15, 0), time(17, 30), name="Afternoon"),
    "dinner": TimeSlot(time(17, 30), time(21, 30), is_peak=True, name="Dinner"),
    "closing": TimeSlot(time(21, 30), time(23, 30), name="Closing"),
}

