"""
Benchmark and Profiling Module for McDonald's Scheduling System.

Provides:
- Performance benchmarking with statistical analysis
- Function-level profiling with decorators
- Memory usage tracking
- Execution time measurement

Usage:
    # Run benchmarks
    python benchmark.py
    
    # Use profiling decorator
    @profile_function
    def my_function():
        pass
"""
import time
import statistics
import functools
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field


# =============================================================================
# PROFILING DECORATOR
# =============================================================================

@dataclass
class ProfileResult:
    """Result of profiling a function call."""
    function_name: str
    execution_time: float
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error: Optional[str] = None


# Global profiling data store
_profile_data: Dict[str, List[ProfileResult]] = {}


def profile_function(func: Callable) -> Callable:
    """
    Decorator to profile function execution time.
    
    Usage:
        @profile_function
        def my_function():
            ...
    
    Results are stored in _profile_data and can be retrieved via get_profile_summary()
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        start_time = time.perf_counter()
        error_msg = None
        success = True
        
        try:
            result = func(*args, **kwargs)
            return result
        except Exception as e:
            success = False
            error_msg = str(e)
            raise
        finally:
            execution_time = time.perf_counter() - start_time
            
            # Store profiling data
            func_name = func.__qualname__
            if func_name not in _profile_data:
                _profile_data[func_name] = []
            
            _profile_data[func_name].append(ProfileResult(
                function_name=func_name,
                execution_time=execution_time,
                success=success,
                error=error_msg
            ))
    
    return wrapper


def get_profile_summary() -> Dict[str, Dict[str, Any]]:
    """
    Get summary of all profiled functions.
    
    Returns:
        Dictionary with function names as keys and stats as values
    """
    summary = {}
    
    for func_name, results in _profile_data.items():
        times = [r.execution_time for r in results]
        successes = [r for r in results if r.success]
        
        summary[func_name] = {
            "call_count": len(results),
            "success_count": len(successes),
            "failure_count": len(results) - len(successes),
            "total_time": sum(times),
            "avg_time": statistics.mean(times) if times else 0,
            "min_time": min(times) if times else 0,
            "max_time": max(times) if times else 0,
            "std_dev": statistics.stdev(times) if len(times) > 1 else 0,
        }
    
    return summary


def clear_profile_data() -> None:
    """Clear all profiling data."""
    global _profile_data
    _profile_data = {}


def print_profile_report() -> None:
    """Print a formatted profiling report."""
    summary = get_profile_summary()
    
    if not summary:
        print("No profiling data collected.")
        return
    
    print("\n" + "=" * 80)
    print("PROFILING REPORT")
    print("=" * 80)
    
    # Sort by total time (descending)
    sorted_funcs = sorted(
        summary.items(), 
        key=lambda x: x[1]['total_time'], 
        reverse=True
    )
    
    for func_name, stats in sorted_funcs:
        print(f"\n📊 {func_name}")
        print(f"   Calls: {stats['call_count']} ({stats['success_count']} success, {stats['failure_count']} failed)")
        print(f"   Total: {stats['total_time']:.3f}s | Avg: {stats['avg_time']:.3f}s")
        print(f"   Range: {stats['min_time']:.3f}s - {stats['max_time']:.3f}s")
        if stats['std_dev'] > 0:
            print(f"   Std Dev: {stats['std_dev']:.3f}s")
    
    print("\n" + "=" * 80)


# =============================================================================
# BENCHMARK RUNNER
# =============================================================================

@dataclass
class BenchmarkResult:
    """Result of a benchmark run."""
    name: str
    iterations: int
    times: List[float]
    timestamp: datetime = field(default_factory=datetime.now)
    
    @property
    def mean(self) -> float:
        return statistics.mean(self.times) if self.times else 0
    
    @property
    def median(self) -> float:
        return statistics.median(self.times) if self.times else 0
    
    @property
    def std_dev(self) -> float:
        return statistics.stdev(self.times) if len(self.times) > 1 else 0
    
    @property
    def min_time(self) -> float:
        return min(self.times) if self.times else 0
    
    @property
    def max_time(self) -> float:
        return max(self.times) if self.times else 0
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "mean": self.mean,
            "median": self.median,
            "std_dev": self.std_dev,
            "min": self.min_time,
            "max": self.max_time,
            "timestamp": self.timestamp.isoformat(),
        }


class Benchmark:
    """
    Benchmark runner for performance testing.
    
    Usage:
        bench = Benchmark()
        bench.add("My Test", my_function, iterations=10)
        bench.run()
        bench.print_report()
    """
    
    def __init__(self):
        self.benchmarks: List[Dict] = []
        self.results: List[BenchmarkResult] = []
    
    def add(self, name: str, func: Callable, iterations: int = 5, 
            args: tuple = (), kwargs: dict = None) -> "Benchmark":
        """Add a benchmark test."""
        self.benchmarks.append({
            "name": name,
            "func": func,
            "iterations": iterations,
            "args": args,
            "kwargs": kwargs or {}
        })
        return self
    
    def run(self) -> List[BenchmarkResult]:
        """Run all benchmarks and return results."""
        self.results = []
        
        for bench in self.benchmarks:
            print(f"Running benchmark: {bench['name']}...")
            times = []
            
            for i in range(bench['iterations']):
                start = time.perf_counter()
                try:
                    bench['func'](*bench['args'], **bench['kwargs'])
                except Exception as e:
                    print(f"  Iteration {i+1} failed: {e}")
                    continue
                end = time.perf_counter()
                times.append(end - start)
                print(f"  Iteration {i+1}: {times[-1]:.3f}s")
            
            result = BenchmarkResult(
                name=bench['name'],
                iterations=bench['iterations'],
                times=times
            )
            self.results.append(result)
        
        return self.results
    
    def print_report(self) -> None:
        """Print benchmark results."""
        if not self.results:
            print("No benchmark results. Run benchmarks first.")
            return
        
        print("\n" + "=" * 80)
        print("BENCHMARK REPORT")
        print("=" * 80)
        
        for result in self.results:
            print(f"\n🏃 {result.name}")
            print(f"   Iterations: {result.iterations} (successful: {len(result.times)})")
            print(f"   Mean: {result.mean:.3f}s | Median: {result.median:.3f}s")
            print(f"   Range: {result.min_time:.3f}s - {result.max_time:.3f}s")
            print(f"   Std Dev: {result.std_dev:.3f}s")
            
            # Performance indicator
            if result.mean < 3:
                print("   Status: ✅ EXCELLENT")
            elif result.mean < 10:
                print("   Status: ✅ GOOD")
            elif result.mean < 30:
                print("   Status: ⚠️ ACCEPTABLE")
            else:
                print("   Status: ❌ NEEDS IMPROVEMENT")
        
        print("\n" + "=" * 80)
    
    def get_results_dict(self) -> List[dict]:
        """Get results as list of dictionaries."""
        return [r.to_dict() for r in self.results]


# =============================================================================
# SYSTEM BENCHMARK (MAIN)
# =============================================================================

def run_system_benchmark():
    """
    Run comprehensive benchmarks on the scheduling system.
    """
    import sys
    from pathlib import Path
    
    # Add parent directory to path
    sys.path.insert(0, str(Path(__file__).parent))
    
    from communication.message_bus import MessageBus
    from agents.data_loader import DataLoaderAgent
    from agents.demand_forecaster import DemandForecasterAgent
    from agents.staff_matcher import StaffMatcherAgent
    from agents.compliance_validator import ComplianceValidatorAgent
    from models.store import create_cbd_store
    from datetime import date, timedelta
    
    print("=" * 80)
    print("McDONALD'S SCHEDULING SYSTEM - BENCHMARK SUITE")
    print("=" * 80)
    print(f"Started at: {datetime.now().isoformat()}")
    print()
    print("Note: This is a standalone performance testing tool.")
    print("      Warnings about 'Coordinator not found' are expected in benchmark mode.")
    print()
    
    # Setup with non-verbose message bus (suppresses agent registration messages)
    message_bus = MessageBus(verbose=False)
    data_loader = DataLoaderAgent(message_bus)
    
    def benchmark_data_loading():
        """Benchmark data loading performance."""
        return data_loader.execute()
    
    def benchmark_demand_forecasting():
        """Benchmark demand forecasting."""
        store = create_cbd_store()  # Use helper function to create proper store
        forecaster = DemandForecasterAgent(message_bus)
        start_date = date(2024, 12, 16)
        end_date = start_date + timedelta(days=13)
        return forecaster.execute(store=store, start_date=start_date, end_date=end_date)
    
    # Run benchmarks
    bench = Benchmark()
    
    bench.add(
        "Data Loading (CSV parsing)",
        benchmark_data_loading,
        iterations=3
    )
    
    bench.add(
        "Demand Forecasting (2 weeks)",
        benchmark_demand_forecasting,
        iterations=3
    )
    
    bench.run()
    bench.print_report()
    
    # Also print profiling data if any
    print_profile_report()
    
    return bench.get_results_dict()


if __name__ == "__main__":
    run_system_benchmark()

