"""
Demand Forecaster Agent - Calculates staffing requirements by time slot.
"""
from datetime import date, time, timedelta
from typing import Any, Dict, List, Optional

from .base_agent import BaseAgent
from communication.message import Message, MessageType
from communication.message_bus import MessageBus
from models.store import Store
from models.shift import TimeSlot, PEAK_PERIODS, SERVICE_PERIODS
from models.employee import Station


class DemandForecasterAgent(BaseAgent):
    """
    Agent responsible for forecasting staffing demand.
    
    Responsibilities:
    - Calculate required staff per time slot
    - Identify peak vs off-peak periods
    - Account for weekday vs weekend differences
    - Generate staffing requirements for each day
    """
    
    def __init__(self, message_bus: MessageBus):
        super().__init__("DemandForecaster", message_bus)
        self.store: Optional[Store] = None
        self.demand_forecast: Dict[date, Dict[str, Any]] = {}
        
    def execute(self, store: Store, start_date: date, end_date: date, **kwargs) -> Dict[date, Dict[str, Any]]:
        """
        Generate demand forecast for a date range.
        
        Args:
            store: Store configuration
            start_date: First day of schedule
            end_date: Last day of schedule
            
        Returns:
            Dictionary mapping dates to staffing requirements
        """
        self.store = store
        self.log(f"Generating demand forecast for {store.name}: {start_date} to {end_date}")
        
        # Generate forecast for each day
        current_date = start_date
        while current_date <= end_date:
            self.demand_forecast[current_date] = self._forecast_day(current_date)
            current_date += timedelta(days=1)
        
        # Send forecast to Coordinator
        self.send(
            MessageType.DATA,
            {
                "type": "demand_forecast",
                "forecast": self.demand_forecast,
                "store_id": store.id,
                "date_range": f"{start_date} to {end_date}",
            },
            receiver="Coordinator"
        )
        
        self.log(f"Forecast complete: {len(self.demand_forecast)} days", "success")
        return self.demand_forecast
    
    def _forecast_day(self, target_date: date) -> Dict[str, Any]:
        """
        Generate staffing requirements for a single day.
        
        Args:
            target_date: The date to forecast
            
        Returns:
            Dictionary with staffing requirements by period and station
        """
        is_weekend = target_date.weekday() >= 5  # Saturday = 5, Sunday = 6
        day_name = target_date.strftime("%A")
        
        # Base requirements from store configuration
        base_requirements = self._get_base_requirements()
        
        # Apply weekend multiplier (20% increase per challenge requirements)
        weekend_multiplier = 1.2 if is_weekend else 1.0
        
        # Generate requirements by service period
        period_requirements = {}
        for period_name, time_slot in SERVICE_PERIODS.items():
            is_peak = time_slot.is_peak
            
            # Get station requirements
            station_reqs = {}
            for station in self.store.get_active_stations():
                base = self.store.get_staff_required_by_station(station, is_peak)
                adjusted = int(base * weekend_multiplier)
                station_reqs[station.value] = adjusted
            
            period_requirements[period_name] = {
                "time_slot": {
                    "start": time_slot.start.strftime("%H:%M"),
                    "end": time_slot.end.strftime("%H:%M"),
                },
                "is_peak": is_peak,
                "station_requirements": station_reqs,
                "total_staff": sum(station_reqs.values()),
            }
        
        # Calculate shift-based requirements
        shift_requirements = self._calculate_shift_requirements(
            period_requirements, is_weekend
        )
        
        return {
            "date": target_date.isoformat(),
            "day_name": day_name,
            "is_weekend": is_weekend,
            "period_requirements": period_requirements,
            "shift_requirements": shift_requirements,
            "total_staff_needed": self._calculate_total_unique_staff(shift_requirements),
            "notes": self._generate_notes(target_date, is_weekend),
        }
    
    def _get_base_requirements(self) -> Dict[Station, int]:
        """Get base staffing requirements from store config."""
        return {
            station: self.store.get_staff_required_by_station(station, False)
            for station in self.store.get_active_stations()
        }
    
    def _calculate_shift_requirements(self, period_reqs: Dict, 
                                       is_weekend: bool) -> Dict[str, Dict]:
        """
        Calculate how many of each shift type needed.
        
        Args:
            period_reqs: Requirements by service period
            is_weekend: Whether it's a weekend
            
        Returns:
            Dictionary with shift requirements by shift type and station
        
        Strategy:
        - Prioritize 1F and 2F shifts (most employees are available for these)
        - Use 3F sparingly (few employees have 3F availability)
        - Ensure coverage overlaps during lunch (both 1F and 2F present)
        """
        shift_requirements = {
            "1F": {},
            "2F": {},
            "3F": {},
        }
        
        for station in self.store.get_active_stations():
            station_name = station.value
            
            # Get peak requirements for this station
            lunch_peak = period_reqs.get("lunch", {}).get("station_requirements", {}).get(station_name, 0)
            dinner_peak = period_reqs.get("dinner", {}).get("station_requirements", {}).get(station_name, 0)
            
            # Calculate shift needs - prioritize 1F and 2F
            # 1F (06:30-15:30) covers morning/lunch
            # Most employees available for 1F, so use it heavily
            shift_requirements["1F"][station_name] = max(1, (lunch_peak + 1) // 2)
            
            # 2F (14:00-23:00) covers afternoon/dinner/closing  
            # Also commonly available
            shift_requirements["2F"][station_name] = max(1, (dinner_peak + 1) // 2)
            
            # 3F (08:00-20:00) all-day - use minimally since few have availability
            # Only on weekends or for high-demand stations
            if is_weekend and lunch_peak >= 3:
                shift_requirements["3F"][station_name] = 1
            else:
                shift_requirements["3F"][station_name] = 0
        
        # Add totals
        for shift_type in shift_requirements:
            shift_requirements[shift_type]["total"] = sum(
                v for k, v in shift_requirements[shift_type].items() 
                if k != "total"
            )
        
        return shift_requirements
    
    def _calculate_total_unique_staff(self, shift_reqs: Dict) -> int:
        """Calculate total unique staff needed for a day."""
        return sum(
            shift_reqs[shift_type].get("total", 0)
            for shift_type in ["1F", "2F", "3F"]
        )
    
    def _generate_notes(self, target_date: date, is_weekend: bool) -> List[str]:
        """Generate notes about staffing for this day."""
        notes = []
        
        if is_weekend:
            notes.append("Weekend: 20% higher staffing required")
        
        day_name = target_date.strftime("%A")
        if day_name == "Friday":
            notes.append("Friday: Expect higher evening traffic")
        elif day_name == "Monday":
            notes.append("Monday: Typically higher breakfast/lunch demand")
        
        # Check for special dates (Christmas period)
        if target_date.month == 12 and target_date.day >= 20:
            notes.append("Christmas period: Higher than usual demand expected")
        
        return notes
    
    def get_required_coverage(self, target_date: date, 
                               time_slot: TimeSlot,
                               station: Optional[Station] = None) -> int:
        """
        Get required staff coverage for a specific time slot.
        
        Args:
            target_date: The date to check
            time_slot: The time window
            station: Optional station filter
            
        Returns:
            Required number of staff
        """
        if target_date not in self.demand_forecast:
            return 0
        
        day_forecast = self.demand_forecast[target_date]
        
        # Find matching period
        for period_name, period_data in day_forecast["period_requirements"].items():
            period_slot = SERVICE_PERIODS.get(period_name)
            if period_slot and period_slot.overlaps(time_slot):
                if station:
                    return period_data["station_requirements"].get(station.value, 0)
                return period_data["total_staff"]
        
        return 0
    
    def _on_request(self, message: Message) -> None:
        """Handle requests for demand data."""
        content = message.content
        
        if isinstance(content, dict):
            if content.get("type") == "get_forecast":
                target_date = content.get("date")
                if target_date and target_date in self.demand_forecast:
                    self.respond(message, self.demand_forecast[target_date])
                else:
                    self.respond(message, {"error": "Date not found in forecast"})
            elif content.get("type") == "get_all_forecasts":
                self.respond(message, {"forecast": self.demand_forecast})

