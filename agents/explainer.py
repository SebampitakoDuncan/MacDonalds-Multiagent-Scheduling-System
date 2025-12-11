"""
Explainer Agent - Generates human-readable explanations using LLM.
Uses OpenRouter API with free models (Mistral, Gemma, etc.)
"""
import os
import time
from datetime import date
from typing import Any, Dict, List, Optional
import requests

from .base_agent import BaseAgent
from communication.message import Message, MessageType
from communication.message_bus import MessageBus
from models.schedule import Schedule, Assignment
from models.constraints import ComplianceResult, Violation
from models.employee import Employee, EmployeeType, Station
from models.store import Store

# Import config
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import config, get_api_key, llm_rate_limiter, retry_with_backoff


class OpenRouterClient:
    """
    Simple client for OpenRouter API with rate limiting and retry.
    Compatible with free models like Mistral and Gemma.
    
    Features:
    - Rate limiting to prevent API cost explosion
    - Exponential backoff retry for transient failures
    - Graceful degradation when API unavailable
    """
    
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1"):
        self.api_key = api_key
        self.base_url = base_url
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/yep-ai-challenge",
            "X-Title": "McDonald's Scheduling System"
        }
        self._call_count = 0
    
    @retry_with_backoff(
        max_retries=3,
        base_delay=1.0,
        max_delay=10.0,
        exceptions=(requests.RequestException, requests.Timeout)
    )
    def _make_request(self, payload: dict) -> requests.Response:
        """Make API request with retry logic."""
        return requests.post(
            f"{self.base_url}/chat/completions",
            headers=self.headers,
            json=payload,
            timeout=30
        )
    
    def chat_completion(self, 
                        messages: List[Dict[str, str]], 
                        model: str,
                        max_tokens: int = 300,
                        temperature: float = 0.7) -> Optional[str]:
        """
        Send a chat completion request to OpenRouter with rate limiting.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model identifier (e.g., "mistralai/mistral-7b-instruct:free")
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            
        Returns:
            Generated text or None if failed/rate limited
        """
        # Check rate limit before making call
        if not llm_rate_limiter.acquire():
            # Rate limited - return None to trigger fallback
            return None
        
        try:
            self._call_count += 1
            
            response = self._make_request({
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            })
            
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            elif response.status_code == 429:
                # Rate limited by API - wait and return None
                return None
            else:
                return None
                
        except Exception as e:
            return None
    
    @property
    def call_count(self) -> int:
        """Get total API calls made."""
        return self._call_count


class ExplainerAgent(BaseAgent):
    """
    Agent responsible for generating human-readable explanations.
    
    Uses OpenRouter API with free models for:
    - Explaining scheduling decisions
    - Summarizing conflicts and resolutions
    - Generating manager-friendly reports
    - Creating approval request narratives
    
    Falls back to template-based explanations if LLM unavailable.
    """
    
    def __init__(self, message_bus: MessageBus, use_llm: bool = True):
        super().__init__("Explainer", message_bus)
        self.use_llm = use_llm
        self.llm_client: Optional[OpenRouterClient] = None
        self.explanations: List[str] = []
        
        # Model configuration from config
        self.primary_model = config.llm.primary_model
        self.fallback_model = config.llm.fallback_model
        self.max_tokens = config.llm.max_tokens
        self.temperature = config.llm.temperature
        
        # Try to initialize LLM client
        if use_llm:
            self._init_llm_client()
    
    def _init_llm_client(self) -> None:
        """Initialize OpenRouter client if API key is available."""
        # Use the centralized API key getter
        api_key = get_api_key()
        
        if api_key:
            self.llm_client = OpenRouterClient(
                api_key=api_key,
                base_url=config.llm.base_url
            )
            self.log(f"OpenRouter client initialized (model: {self.primary_model})")
        else:
            self.log("No OpenRouter API key found - using template-based explanations", "warning")
            self.log("Set OPENROUTER_API_KEY in config.py or environment variable", "warning")
            self.use_llm = False
    
    def _call_llm(self, prompt: str, use_fallback: bool = False) -> Optional[str]:
        """
        Call LLM with retry and fallback logic.
        
        Args:
            prompt: The prompt to send
            use_fallback: Whether to use fallback model
            
        Returns:
            Generated text or None
        """
        if not self.llm_client:
            return None
        
        model = self.fallback_model if use_fallback else self.primary_model
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant that explains restaurant scheduling decisions clearly and concisely."},
            {"role": "user", "content": prompt}
        ]
        
        # Try primary model
        result = self.llm_client.chat_completion(
            messages=messages,
            model=model,
            max_tokens=self.max_tokens,
            temperature=self.temperature
        )
        
        # If primary fails and not already using fallback, try fallback
        if result is None and not use_fallback:
            self.log(f"Primary model failed, trying fallback: {self.fallback_model}", "warning")
            time.sleep(config.llm.retry_delay)
            result = self._call_llm(prompt, use_fallback=True)
        
        return result
    
    def execute(self,
                schedule: Schedule,
                compliance_result: ComplianceResult,
                employees: List[Employee],
                store: Store,
                **kwargs) -> Dict[str, Any]:
        """
        Generate explanations for the schedule.
        
        Args:
            schedule: The final schedule
            compliance_result: Compliance validation results
            employees: List of employees
            store: Store configuration
            
        Returns:
            Dictionary containing various explanations
        """
        self.log("Generating schedule explanations...")
        
        explanations = {
            "summary": self._generate_summary(schedule, compliance_result, store),
            "coverage_analysis": self._generate_coverage_analysis(schedule, store),
            "employee_assignments": self._generate_employee_summary(schedule, employees),
            "compliance_notes": self._generate_compliance_notes(compliance_result),
            "recommendations": self._generate_recommendations(schedule, compliance_result, employees),
        }
        
        # If there were violations/warnings, explain them
        if compliance_result.violations or compliance_result.warnings:
            explanations["issues"] = self._explain_issues(compliance_result)
        
        # If there are pending approvals, generate manager action items
        if compliance_result.pending_approvals:
            explanations["manager_approvals"] = self._generate_manager_approvals(compliance_result)
        
        # Send to Coordinator
        self.send(
            MessageType.DATA,
            {
                "type": "explanations",
                "content": explanations,
            },
            receiver="Coordinator"
        )
        
        self.log("Explanations generated", "success")
        return explanations
    
    def _generate_summary(self, schedule: Schedule, 
                          compliance_result: ComplianceResult,
                          store: Store) -> str:
        """Generate an executive summary of the schedule."""
        summary_data = schedule.summary()
        
        if self.use_llm and self.llm_client:
            llm_summary = self._llm_generate_summary(summary_data, compliance_result, store)
            if llm_summary:
                return llm_summary
        
        # Template-based summary (fallback)
        status = "✅ COMPLIANT" if compliance_result.is_compliant else "⚠️ NEEDS REVIEW"
        
        pending_note = ""
        if compliance_result.pending_approvals:
            pending_note = f"\n• 📋 Pending Manager Approval: {len(compliance_result.pending_approvals)}"
        
        return f"""
📋 SCHEDULE SUMMARY - {store.name}
{'=' * 50}

Period: {summary_data['date_range']}
Status: {status} (Score: {compliance_result.score:.1f}/100)

📊 Key Metrics:
• Total Assignments: {summary_data['total_assignments']}
• Employees Scheduled: {summary_data['unique_employees']}
• Total Hours: {summary_data['total_hours']:.1f}
• Days Covered: {summary_data['days']}

📈 Compliance:
• Hard Violations: {len(compliance_result.violations)}
• Soft Warnings: {len(compliance_result.warnings)}{pending_note}

This schedule was automatically generated by the Multi-Agent 
Scheduling System, optimizing for Fair Work Act compliance,
peak period coverage, and employee preferences.
"""
    
    def _llm_generate_summary(self, summary_data: Dict, 
                               compliance_result: ComplianceResult,
                               store: Store) -> Optional[str]:
        """Generate summary using LLM."""
        prompt = f"""
Generate a brief, professional executive summary for this restaurant schedule:

Store: {store.name} ({store.store_type.value})
Period: {summary_data['date_range']}
Total Assignments: {summary_data['total_assignments']}
Employees: {summary_data['unique_employees']}
Total Hours: {summary_data['total_hours']}
Compliance Score: {compliance_result.score}/100
Violations: {len(compliance_result.violations)} hard, {len(compliance_result.warnings)} soft

Keep it concise (3-4 sentences) and highlight key achievements or concerns.
Start with the most important information.
"""
        return self._call_llm(prompt)
    
    def _generate_coverage_analysis(self, schedule: Schedule, store: Store) -> str:
        """Generate analysis of coverage by period."""
        lines = [
            "\n📊 COVERAGE ANALYSIS",
            "=" * 50
        ]
        
        # Analyze coverage by day of week
        from collections import defaultdict
        day_coverage = defaultdict(list)
        
        for target_date in schedule.get_dates_in_range():
            day_name = target_date.strftime("%A")
            assignments = schedule.get_assignments_by_date(target_date)
            day_coverage[day_name].append(len(assignments))
        
        lines.append("\nAverage Daily Coverage by Day of Week:")
        for day, counts in day_coverage.items():
            avg = sum(counts) / len(counts) if counts else 0
            bar = "█" * int(avg / 2)
            lines.append(f"  {day[:3]}: {bar} ({avg:.1f} staff)")
        
        # Station breakdown
        lines.append("\nCoverage by Station:")
        for station in store.get_active_stations():
            assignments = schedule.get_assignments_by_station(station)
            lines.append(f"  {station.value}: {len(assignments)} shifts")
        
        return "\n".join(lines)
    
    def _generate_employee_summary(self, schedule: Schedule, 
                                    employees: List[Employee]) -> str:
        """Generate summary of employee assignments."""
        lines = [
            "\n👥 EMPLOYEE ASSIGNMENTS",
            "=" * 50
        ]
        
        # Group by employee type
        from collections import defaultdict
        by_type = defaultdict(list)
        
        for employee in employees:
            assignments = schedule.get_assignments_by_employee(employee.id)
            hours = sum(a.shift.hours for a in assignments)
            by_type[employee.employee_type.value].append({
                "name": employee.name,
                "shifts": len(assignments),
                "hours": hours,
                "min": employee.weekly_hours_target[0],
                "max": employee.weekly_hours_target[1],
            })
        
        for emp_type, emp_list in by_type.items():
            lines.append(f"\n{emp_type}:")
            for emp in sorted(emp_list, key=lambda x: x['hours'], reverse=True)[:5]:
                status = "✓" if emp['min'] <= emp['hours'] / 2 <= emp['max'] else "!"
                lines.append(
                    f"  {status} {emp['name']}: {emp['shifts']} shifts, "
                    f"{emp['hours']:.1f}h/2wk"
                )
        
        return "\n".join(lines)
    
    def _generate_compliance_notes(self, compliance_result: ComplianceResult) -> str:
        """Generate notes about compliance status."""
        lines = [
            "\n⚖️ COMPLIANCE NOTES (Fair Work Act)",
            "=" * 50
        ]
        
        if compliance_result.is_compliant:
            lines.append("\n✅ All hard constraints satisfied:")
            lines.append("  • Maximum weekly hours respected")
            lines.append("  • Minimum 10-hour rest between shifts")
            lines.append("  • Maximum 6 consecutive working days")
            lines.append("  • Skills matched to station requirements")
        else:
            lines.append(f"\n⚠️ {len(compliance_result.violations)} violations require attention:")
            for v in compliance_result.violations[:5]:
                lines.append(f"  ❌ {v.description}")
        
        if compliance_result.warnings:
            lines.append(f"\n📝 {len(compliance_result.warnings)} optimization opportunities:")
            for w in compliance_result.warnings[:3]:
                lines.append(f"  • {w.description}")
        
        return "\n".join(lines)
    
    def _generate_recommendations(self, schedule: Schedule,
                                   compliance_result: ComplianceResult,
                                   employees: List[Employee]) -> str:
        """Generate actionable recommendations."""
        lines = [
            "\n💡 RECOMMENDATIONS",
            "=" * 50
        ]
        
        recommendations = []
        
        # Check for understaffed employees
        for employee in employees:
            assignments = schedule.get_assignments_by_employee(employee.id)
            hours = sum(a.shift.hours for a in assignments)
            min_hours = employee.weekly_hours_target[0] * 2  # 2 weeks
            
            if hours < min_hours * 0.8:
                recommendations.append(
                    f"Consider adding shifts for {employee.name} "
                    f"({hours:.1f}/{min_hours}h target)"
                )
        
        # Add based on violations
        for violation in compliance_result.warnings[:2]:
            if violation.suggestions:
                recommendations.append(violation.suggestions[0])
        
        if not recommendations:
            recommendations.append("Schedule is well-optimized. No immediate actions needed.")
        
        for i, rec in enumerate(recommendations[:5], 1):
            lines.append(f"  {i}. {rec}")
        
        return "\n".join(lines)
    
    def _explain_issues(self, compliance_result: ComplianceResult) -> str:
        """Generate detailed explanation of issues."""
        lines = [
            "\n🔍 DETAILED ISSUE ANALYSIS",
            "=" * 50
        ]
        
        if compliance_result.violations:
            lines.append("\n❌ CRITICAL ISSUES (Must Fix):")
            for v in compliance_result.violations:
                lines.append(f"\n  Issue: {v.description}")
                lines.append(f"  Severity: {v.severity}/10")
                if v.suggestions:
                    lines.append(f"  Suggested Fix: {v.suggestions[0]}")
        
        if compliance_result.warnings:
            lines.append("\n⚠️ WARNINGS (Should Address):")
            for w in compliance_result.warnings[:5]:
                lines.append(f"\n  Warning: {w.description}")
                if w.suggestions:
                    lines.append(f"  Suggestion: {w.suggestions[0]}")
        
        return "\n".join(lines)
    
    def _generate_manager_approvals(self, compliance_result: ComplianceResult) -> str:
        """
        Generate detailed explanation for items requiring manager approval.
        
        This supports the human-in-the-loop pattern by providing managers with:
        - Clear description of the issue
        - Why automated resolution failed
        - Available options for manual resolution
        """
        lines = [
            "\n📋 MANAGER APPROVAL REQUIRED",
            "=" * 50,
            "\nThe following items could not be automatically resolved",
            "and require manager decision:\n"
        ]
        
        for i, approval in enumerate(compliance_result.pending_approvals, 1):
            lines.append(f"┌{'─' * 48}┐")
            lines.append(f"│ ITEM {i}: {approval.constraint_type.value.upper():<38} │")
            lines.append(f"├{'─' * 48}┤")
            lines.append(f"│ Date: {str(approval.affected_date or 'N/A'):<41} │")
            lines.append(f"│ Description: ")
            
            # Wrap description
            desc = approval.description
            while len(desc) > 45:
                lines.append(f"│   {desc[:45]:<45} │")
                desc = desc[45:]
            lines.append(f"│   {desc:<45} │")
            
            # Escalation reason
            reason = approval.details.get("escalation_reason", "Unable to resolve automatically")
            lines.append(f"├{'─' * 48}┤")
            lines.append(f"│ Why approval needed:")
            for line in reason.split(". "):
                if line:
                    while len(line) > 43:
                        lines.append(f"│   • {line[:43]}")
                        line = line[43:]
                    lines.append(f"│   • {line:<43} │")
            
            # Manager options
            lines.append(f"├{'─' * 48}┤")
            lines.append(f"│ MANAGER OPTIONS:")
            lines.append(f"│   □ A) Accept understaffed shift             │")
            lines.append(f"│   □ B) Authorize overtime for qualified staff│")
            lines.append(f"│   □ C) Contact casual pool for coverage      │")
            lines.append(f"│   □ D) Reduce station services temporarily   │")
            lines.append(f"│   □ E) Request shift swap from other store   │")
            lines.append(f"└{'─' * 48}┘")
            lines.append("")
        
        # Add LLM-generated contextual advice if available
        if self.use_llm and self.llm_client and len(compliance_result.pending_approvals) > 0:
            advice = self._generate_manager_advice(compliance_result.pending_approvals)
            if advice:
                lines.append("\n💡 SYSTEM RECOMMENDATION:")
                lines.append(advice)
        
        return "\n".join(lines)
    
    def _generate_manager_advice(self, pending_approvals) -> Optional[str]:
        """Use LLM to generate contextual advice for manager."""
        approval_text = "\n".join([
            f"- {a.description} on {a.affected_date}"
            for a in pending_approvals[:3]
        ])
        
        prompt = f"""
You are an assistant helping a McDonald's restaurant manager with scheduling decisions.

The following staffing gaps could not be automatically filled:
{approval_text}

Provide a brief (2-3 sentences), practical recommendation considering:
- This is a fast-food restaurant with variable customer traffic
- Staff safety and legal compliance are top priorities
- Cross-training has already been attempted

Be specific and actionable.
"""
        return self._call_llm(prompt)
    
    def explain_decision(self, decision: str, context: Dict) -> str:
        """
        Generate an explanation for a specific scheduling decision.
        Called by other agents when they need to explain something.
        
        Args:
            decision: Description of the decision
            context: Additional context
            
        Returns:
            Human-readable explanation
        """
        if self.use_llm and self.llm_client:
            prompt = f"""
Explain this scheduling decision in simple terms for a restaurant manager:

Decision: {decision}
Context: {context}

Keep it brief (2-3 sentences) and professional.
"""
            result = self._call_llm(prompt)
            if result:
                return result
        
        # Fallback
        return f"Decision: {decision}. This was determined based on {context.get('reason', 'scheduling constraints')}."
    
    def generate_conflict_summary(self, violations: List[Violation]) -> str:
        """
        Generate a summary of conflicts for manager review.
        
        Args:
            violations: List of violations to summarize
            
        Returns:
            Human-readable summary
        """
        if not violations:
            return "No conflicts detected."
        
        if self.use_llm and self.llm_client:
            violation_text = "\n".join([
                f"- {v.description} (severity: {v.severity}/10)"
                for v in violations[:5]
            ])
            
            prompt = f"""
Summarize these scheduling conflicts for a restaurant manager:

{violation_text}

Provide a brief (2-3 sentence) summary highlighting the most critical issues.
"""
            result = self._call_llm(prompt)
            if result:
                return result
        
        # Fallback
        critical = [v for v in violations if v.severity >= 8]
        return f"Found {len(violations)} conflicts: {len(critical)} critical, {len(violations) - len(critical)} minor. Review recommended."
    
    def _on_request(self, message: Message) -> None:
        """Handle explanation requests from other agents."""
        content = message.content
        
        if isinstance(content, dict):
            request_type = content.get("type")
            
            if request_type == "explain_decision":
                decision = content.get("decision", "")
                context = content.get("context", {})
                explanation = self.explain_decision(decision, context)
                self.respond(message, {"explanation": explanation})
            
            elif request_type == "explain_violation":
                violation = content.get("violation")
                if violation:
                    explanation = f"Violation: {violation}. This needs to be addressed to ensure Fair Work Act compliance."
                    self.respond(message, {"explanation": explanation})
            
            elif request_type == "summarize_conflicts":
                violations = content.get("violations", [])
                summary = self.generate_conflict_summary(violations)
                self.respond(message, {"summary": summary})
