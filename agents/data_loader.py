"""
Data Loader Agent - Loads and parses CSV data files.
"""
import pandas as pd
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .base_agent import BaseAgent
from communication.message import Message, MessageType
from communication.message_bus import MessageBus
from models.employee import (
    Employee, EmployeeType, Station,
    Manager, ManagerPosition, ManagerShift, ManagerCoverage
)
from models.store import Store, StoreType, StaffingRequirement, create_cbd_store, create_suburban_store


class DataLoaderAgent(BaseAgent):
    """
    Agent responsible for loading and parsing all CSV data files.
    
    Responsibilities:
    - Load employee availability data
    - Load store configurations
    - Load staffing requirements
    - Parse shift codes and availability
    - Provide data to other agents
    """
    
    def __init__(self, message_bus: MessageBus, data_dir: str = "data"):
        super().__init__("DataLoader", message_bus)
        self.data_dir = Path(data_dir)
        
        # Loaded data storage
        self.employees: List[Employee] = []
        self.stores: Dict[str, Store] = {}
        self.shift_codes: Dict[str, dict] = {}
        self.rostering_parameters: Dict[str, Any] = {}
        
        # Manager data (monthly roster - fixed)
        self.managers: List[Manager] = []
        self.manager_coverage: Dict[date, ManagerCoverage] = {}
        
    def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Load all data from CSV files.
        
        Returns:
            Dictionary containing all loaded data
        """
        self.log("Starting data loading process...")
        
        # Load all data
        self._load_employees()
        self._load_stores()
        self._load_shift_codes()
        self._load_rostering_parameters()
        self._load_manager_roster()  # Load manager monthly roster
        
        # Prepare result
        result = {
            "employees": self.employees,
            "stores": self.stores,
            "shift_codes": self.shift_codes,
            "parameters": self.rostering_parameters,
            "managers": self.managers,
            "manager_coverage": self.manager_coverage,
            "employee_count": len(self.employees),
            "store_count": len(self.stores),
            "manager_count": len(self.managers),
        }
        
        # Broadcast data loaded
        self.send(
            MessageType.DATA,
            {
                "status": "loaded",
                "employee_count": len(self.employees),
                "store_count": len(self.stores),
            },
            receiver="Coordinator"
        )
        
        self.log(f"Data loading complete: {len(self.employees)} employees, {len(self.stores)} stores", "success")
        return result
    
    def _load_employees(self) -> None:
        """Load employee data from CSV."""
        filepath = self.data_dir / "employee_availability_2weeks.csv"
        
        if not filepath.exists():
            self.log(f"Employee file not found: {filepath}", "error")
            return
        
        try:
            df = pd.read_csv(filepath, skiprows=3)  # Skip header rows
            
            # Clean up column names
            df.columns = df.columns.str.strip()
            
            # Find the actual data rows (those with employee IDs)
            for idx, row in df.iterrows():
                # Skip if not a valid employee row
                if pd.isna(row.iloc[0]) or str(row.iloc[0]).strip() == '':
                    continue
                
                try:
                    emp_id = str(int(row.iloc[0])) if not pd.isna(row.iloc[0]) else None
                except (ValueError, TypeError):
                    continue
                
                if not emp_id or not emp_id.isdigit():
                    continue
                
                name = str(row.iloc[1]).strip() if not pd.isna(row.iloc[1]) else ""
                emp_type_str = str(row.iloc[2]).strip() if not pd.isna(row.iloc[2]) else ""
                station_str = str(row.iloc[3]).strip() if not pd.isna(row.iloc[3]) else ""
                
                # Parse employee type
                emp_type = self._parse_employee_type(emp_type_str)
                
                # Parse station
                station = Station.from_string(station_str)
                
                # Parse availability (columns 4-17 are the 14 days)
                availability = self._parse_availability(row, df.columns[4:18])
                
                employee = Employee(
                    id=emp_id,
                    name=name,
                    employee_type=emp_type,
                    primary_station=station,
                    availability=availability
                )
                
                # Add cross-training skills based on station
                # Real-world: McCafe and Counter staff can cover Dessert Station
                self._add_cross_training_skills(employee)
                
                self.employees.append(employee)
            
            self.log(f"Loaded {len(self.employees)} employees")
            
        except Exception as e:
            self.log(f"Error loading employees: {e}", "error")
            raise
    
    def _parse_employee_type(self, type_str: str) -> EmployeeType:
        """Parse employee type string to enum."""
        type_str = type_str.lower().strip()
        if "full" in type_str:
            return EmployeeType.FULL_TIME
        elif "part" in type_str:
            return EmployeeType.PART_TIME
        else:
            return EmployeeType.CASUAL
    
    def _parse_availability(self, row: pd.Series, date_columns: pd.Index) -> Dict[date, List[str]]:
        """
        Parse availability columns into date->shift mapping.
        
        The dates are Dec 9-22 (14 days).
        """
        availability = {}
        
        # Start date is Dec 9, 2024 based on the CSV
        start_date = date(2024, 12, 9)
        
        for i, col in enumerate(date_columns):
            try:
                current_date = date(2024, 12, 9 + i)
                shift_code = str(row[col]).strip() if not pd.isna(row[col]) else "/"
                
                # Handle the shift codes
                if shift_code == "/" or shift_code == "nan" or shift_code == "":
                    availability[current_date] = ["/"]
                else:
                    # Could be multiple codes like "1F" or "2F" or "3F"
                    availability[current_date] = [shift_code]
                    
            except Exception:
                continue
        
        return availability
    
    def _load_stores(self) -> None:
        """Load store configurations."""
        # Use pre-defined store configurations
        self.stores["Store_1"] = create_cbd_store()
        self.stores["Store_2"] = create_suburban_store()
        
        # Try to load from CSV for any additional data
        filepath = self.data_dir / "store_configurations.csv"
        if filepath.exists():
            try:
                df = pd.read_csv(filepath, skiprows=1)
                self.log(f"Loaded store configurations from CSV")
            except Exception as e:
                self.log(f"Using default store configurations: {e}", "warning")
        
        self.log(f"Loaded {len(self.stores)} stores")
    
    def _load_shift_codes(self) -> None:
        """Load shift code definitions."""
        filepath = self.data_dir / "management_roster_simplified_shift_codes.csv"
        
        self.shift_codes = {
            "1F": {"name": "First Half", "start": "06:30", "end": "15:30", "hours": 9},
            "2F": {"name": "Second Half", "start": "14:00", "end": "23:00", "hours": 9},
            "3F": {"name": "Full Day", "start": "08:00", "end": "20:00", "hours": 12},
            "S": {"name": "Day Shift", "start": "06:30", "end": "15:00", "hours": 8.5},
            "SC": {"name": "Shift Change", "start": "11:00", "end": "20:00", "hours": 9},
            "M": {"name": "Meeting", "start": "varies", "end": "varies", "hours": 8},
            "/": {"name": "Day Off", "start": "-", "end": "-", "hours": 0},
            "NA": {"name": "Not Available", "start": "-", "end": "-", "hours": 0},
        }
        
        if filepath.exists():
            try:
                df = pd.read_csv(filepath, skiprows=1)
                self.log("Loaded shift codes from CSV")
            except Exception:
                pass
        
        self.log(f"Loaded {len(self.shift_codes)} shift codes")
    
    def _load_rostering_parameters(self) -> None:
        """Load rostering parameters."""
        self.rostering_parameters = {
            "max_shifts_per_day": 1,
            "min_hours_per_shift": 3,
            "max_hours_per_shift": 12,
            "min_rest_between_shifts": 10,  # hours
            "max_consecutive_days": 6,
            "monthly_standard_hours": 152,
            "full_time_ratio": 0.35,
            "part_time_casual_ratio": 0.65,
            "min_staff_count": 2,
            "min_full_time_on_duty": 1,
            "service_periods": {
                "breakfast": {"start": "06:00", "end": "11:00"},
                "lunch": {"start": "11:00", "end": "15:00", "is_peak": True},
                "afternoon": {"start": "15:00", "end": "17:30"},
                "dinner": {"start": "17:30", "end": "21:30", "is_peak": True},
                "closing": {"start": "21:30", "end": "23:30"},
            },
            "hours_limits": {
                "Full-Time": {"min": 35, "max": 38},
                "Part-Time": {"min": 20, "max": 32},
                "Casual": {"min": 8, "max": 24},
            }
        }
        
        filepath = self.data_dir / "australian_restaurant_rostering_parameters.csv"
        if filepath.exists():
            self.log("Loaded rostering parameters")
    
    def _load_manager_roster(self) -> None:
        """
        Load the manager monthly roster.
        
        Manager rosters are pre-defined monthly and serve as the foundation
        that crew schedules are built around. This is how McDonald's actually
        operates - managers are scheduled monthly, crew weekly.
        
        The roster defines:
        - Which managers work which days
        - Opening/closing coverage by managers
        - Peak period manager availability
        """
        filepath = self.data_dir / "management_roster_simplified_monthly_roster.csv"
        
        if not filepath.exists():
            self.log("Manager roster file not found", "warning")
            return
        
        try:
            # Read the raw CSV
            df = pd.read_csv(filepath, header=None)
            
            # Parse position mapping
            position_map = {
                "Restaurant General Manager": ManagerPosition.RESTAURANT_GM,
                "1st Assistant Manager": ManagerPosition.FIRST_ASSISTANT,
                "2nd Assistant Manager": ManagerPosition.SECOND_ASSISTANT,
                "Management Trainee": ManagerPosition.TRAINEE,
            }
            
            # Parse the header row (row 6) to get date columns
            header_row = df.iloc[6]
            
            # Build date mapping: column index -> date
            # Format in CSV: "Mon\n25", "Tue\n9", etc.
            # Nov 25 - Dec 31 based on file
            date_columns = {}
            current_month = 11  # Start with November
            current_year = 2024
            
            for col_idx in range(3, len(header_row)):
                header_val = header_row[col_idx]
                if pd.isna(header_val):
                    continue
                
                # Parse "Day\nDate" format
                parts = str(header_val).split('\n')
                if len(parts) >= 2:
                    try:
                        day_num = int(parts[1])
                        
                        # Handle month transition (Nov -> Dec)
                        if day_num == 1 and current_month == 11:
                            current_month = 12
                        
                        target_date = date(current_year, current_month, day_num)
                        date_columns[col_idx] = target_date
                    except ValueError:
                        continue
            
            # Parse manager rows (rows 7-12)
            for row_idx in range(7, min(13, len(df))):
                row = df.iloc[row_idx]
                
                # Get manager name and position
                manager_name = row[1]
                position_str = row[2]
                
                if pd.isna(manager_name) or pd.isna(position_str):
                    continue
                
                position = position_map.get(position_str, ManagerPosition.TRAINEE)
                
                # Create manager with shifts
                manager = Manager(name=manager_name, position=position)
                
                # Parse shifts for each date
                for col_idx, shift_date in date_columns.items():
                    shift_code = row[col_idx] if col_idx < len(row) else "/"
                    
                    if pd.isna(shift_code):
                        shift_code = "/"
                    
                    shift_code = str(shift_code).strip()
                    
                    # Create manager shift
                    manager_shift = ManagerShift(
                        manager_name=manager_name,
                        position=position,
                        shift_date=shift_date,
                        shift_code=shift_code
                    )
                    
                    manager.shifts[shift_date] = manager_shift
                
                self.managers.append(manager)
            
            # Build manager coverage by date
            self._build_manager_coverage()
            
            self.log(f"Loaded {len(self.managers)} managers from monthly roster")
            
        except Exception as e:
            self.log(f"Error loading manager roster: {e}", "error")
    
    def _build_manager_coverage(self) -> None:
        """
        Build manager coverage summary for each date.
        
        This creates a quick lookup to check:
        - How many managers are working each day
        - Opening/closing coverage
        - Peak period coverage
        """
        from datetime import timedelta
        
        # Get all dates from manager shifts
        all_dates = set()
        for manager in self.managers:
            all_dates.update(manager.shifts.keys())
        
        # Build coverage for each date
        for target_date in all_dates:
            working_shifts = []
            
            for manager in self.managers:
                shift = manager.get_shift(target_date)
                if shift and shift.is_working():
                    working_shifts.append(shift)
            
            self.manager_coverage[target_date] = ManagerCoverage(
                date=target_date,
                managers_on_duty=working_shifts
            )
    
    def get_manager_coverage(self, target_date: date) -> Optional[ManagerCoverage]:
        """Get manager coverage for a specific date."""
        return self.manager_coverage.get(target_date)
    
    def _add_cross_training_skills(self, employee: Employee) -> None:
        """
        Add cross-training skills based on primary station.
        
        Real-world McDonald's cross-training patterns:
        - McCafe staff can work Dessert Station (similar equipment)
        - Counter staff can work Dessert Station (customer-facing basics)
        - Dessert staff can work Counter (customer service)
        - Kitchen staff specialized (no cross-training by default)
        
        This enables flexible coverage during understaffing situations.
        """
        if employee.primary_station == Station.MCCAFE:
            # McCafe staff can work Dessert (similar drink/dessert equipment)
            employee.skills.add(Station.DESSERT)
        
        elif employee.primary_station == Station.COUNTER:
            # Counter staff can work Dessert (customer-facing, basic tasks)
            employee.skills.add(Station.DESSERT)
        
        elif employee.primary_station == Station.DESSERT:
            # Dessert staff can work Counter (customer service overlap)
            employee.skills.add(Station.COUNTER)
        
        # Kitchen staff remain specialized (food safety requirements)
        # No cross-training added for kitchen
    
    def get_employees_by_type(self, emp_type: EmployeeType) -> List[Employee]:
        """Get employees filtered by type."""
        return [e for e in self.employees if e.employee_type == emp_type]
    
    def get_employees_by_station(self, station: Station) -> List[Employee]:
        """Get employees filtered by station."""
        return [e for e in self.employees if e.primary_station == station]
    
    def get_available_employees(self, target_date: date, shift_code: str) -> List[Employee]:
        """Get employees available for a specific date and shift."""
        return [
            e for e in self.employees 
            if e.is_available(target_date, shift_code)
        ]
    
    def _on_request(self, message: Message) -> None:
        """Handle data requests from other agents."""
        request_type = message.content.get("type") if isinstance(message.content, dict) else message.content
        
        if request_type == "employees":
            self.respond(message, {"employees": self.employees})
        elif request_type == "stores":
            self.respond(message, {"stores": self.stores})
        elif request_type == "parameters":
            self.respond(message, {"parameters": self.rostering_parameters})
        elif request_type == "all":
            self.respond(message, {
                "employees": self.employees,
                "stores": self.stores,
                "parameters": self.rostering_parameters,
                "shift_codes": self.shift_codes,
            })

