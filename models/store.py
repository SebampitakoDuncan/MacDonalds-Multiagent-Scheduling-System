"""
Store configuration models.
"""
from dataclasses import dataclass, field
from datetime import time
from enum import Enum
from typing import Dict, List, Optional

from .employee import Station


class StoreType(Enum):
    """Types of store locations."""
    CBD_CORE = "CBD Core Area"
    SUBURBAN = "Suburban Residential"
    HIGHWAY = "Highway"
    SHOPPING_CENTER = "Shopping Center"


@dataclass
class StaffingRequirement:
    """
    Staffing requirement for a specific station and period.
    
    Attributes:
        station: The work station
        normal_count: Staff needed during normal periods
        peak_count: Staff needed during peak periods
    """
    station: Station
    normal_count: int
    peak_count: int
    
    def get_required(self, is_peak: bool) -> int:
        """Get required staff count based on period type."""
        return self.peak_count if is_peak else self.normal_count


@dataclass
class Store:
    """
    Store configuration model.
    
    Attributes:
        id: Store identifier
        name: Store name
        store_type: Type of store location
        opening_time: Daily opening time
        closing_time: Daily closing time
        has_mccafe: Whether store has McCafe
        has_dessert_station: Whether store has dessert station
        staffing_requirements: Staffing requirements by station
        revenue_level: High/Medium/Low
        peak_hours: Description of peak hours
    """
    id: str
    name: str
    store_type: StoreType
    opening_time: time
    closing_time: time
    has_mccafe: bool = False
    has_dessert_station: bool = False
    staffing_requirements: Dict[Station, StaffingRequirement] = field(default_factory=dict)
    revenue_level: str = "Medium"
    peak_hours: str = ""
    avg_daily_customers: tuple = (0, 0)  # (min, max)
    
    def get_operating_hours(self) -> float:
        """Calculate daily operating hours."""
        open_minutes = self.opening_time.hour * 60 + self.opening_time.minute
        close_minutes = self.closing_time.hour * 60 + self.closing_time.minute
        return (close_minutes - open_minutes) / 60
    
    def get_total_staff_required(self, is_peak: bool = False) -> int:
        """Get total staff required across all stations."""
        return sum(
            req.get_required(is_peak) 
            for req in self.staffing_requirements.values()
        )
    
    def get_staff_required_by_station(self, station: Station, 
                                       is_peak: bool = False) -> int:
        """Get staff required for a specific station."""
        if station not in self.staffing_requirements:
            return 0
        return self.staffing_requirements[station].get_required(is_peak)
    
    def get_active_stations(self) -> List[Station]:
        """Get list of active stations for this store."""
        stations = [Station.KITCHEN, Station.COUNTER]
        if self.has_mccafe:
            stations.append(Station.MCCAFE)
        if self.has_dessert_station:
            stations.append(Station.DESSERT)
        return stations
    
    def __str__(self) -> str:
        return (
            f"{self.name} ({self.store_type.value}) | "
            f"Hours: {self.opening_time.strftime('%H:%M')}-{self.closing_time.strftime('%H:%M')} | "
            f"Staff: {self.get_total_staff_required()} normal, {self.get_total_staff_required(True)} peak"
        )


def create_cbd_store() -> Store:
    """Create a CBD Core Area store configuration."""
    store = Store(
        id="Store_1",
        name="Melbourne CBD",
        store_type=StoreType.CBD_CORE,
        opening_time=time(6, 30),
        closing_time=time(23, 0),
        has_mccafe=True,
        has_dessert_station=True,
        revenue_level="High",
        peak_hours="7-9 AM, 12-2 PM",
        avg_daily_customers=(1200, 1800)
    )
    
    # Set staffing requirements based on store_structure_staff_estimate.csv
    store.staffing_requirements = {
        Station.KITCHEN: StaffingRequirement(Station.KITCHEN, normal_count=6, peak_count=8),
        Station.COUNTER: StaffingRequirement(Station.COUNTER, normal_count=5, peak_count=6),
        Station.MCCAFE: StaffingRequirement(Station.MCCAFE, normal_count=3, peak_count=4),
        Station.DESSERT: StaffingRequirement(Station.DESSERT, normal_count=2, peak_count=3),
    }
    
    return store


def create_suburban_store() -> Store:
    """Create a Suburban Residential store configuration."""
    store = Store(
        id="Store_2",
        name="Suburban Melbourne",
        store_type=StoreType.SUBURBAN,
        opening_time=time(7, 0),
        closing_time=time(22, 0),
        has_mccafe=False,
        has_dessert_station=False,
        revenue_level="Medium",
        peak_hours="Dinner time, Weekends",
        avg_daily_customers=(600, 900)
    )
    
    # Set staffing requirements
    store.staffing_requirements = {
        Station.KITCHEN: StaffingRequirement(Station.KITCHEN, normal_count=3, peak_count=4),
        Station.COUNTER: StaffingRequirement(Station.COUNTER, normal_count=3, peak_count=3),
    }
    
    return store

