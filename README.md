# 🍔  A Multi-Agent Workforce Scheduling System for McDonald’s Operations

An intelligent multi-agent system for automated workforce scheduling designed for McDonald’s Australia operations.

## 🎯 Challenge

To replace manual 4-8 hours weekly scheduling with an AI-powered system that generates optimal 2-week rosters in under 180 seconds.

---

## 🏗️ Multi-Agent Architecture

### Agent Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                          COORDINATOR AGENT                                  │
│          (Master Orchestrator - 7+ Phases with Human-in-the-Loop)           │
│  • Manages workflow    • Tracks progress    • Reports results               │
└────────────────────────────────────────────────────────────────────────────┘
                                    │
          ┌─────────────────────────┼─────────────────────────┐
          ▼                         ▼                         ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   DATA LOADER    │    │     DEMAND       │    │     STAFF        │
│                  │    │   FORECASTER     │    │    MATCHER       │
│ • Load CSVs      │───▶│ • Predict needs  │───▶│ • Assign shifts  │
│ • Parse employees│    │ • Peak periods   │    │ • Bidding/Auction│
│ • Store configs  │    │ • Weekend boost  │    │ • Fairness boost │
└──────────────────┘    └──────────────────┘    └──────────────────┘
                                                        │
                                    ┌───────────────────┘
                                    ▼
┌──────────────────────────────────────────────────────────────────┐
│                    ITERATIVE REFINEMENT LOOP                      │
│  ┌──────────────────┐         ┌──────────────────┐               │
│  │   COMPLIANCE     │◀───────▶│    CONFLICT      │               │
│  │   VALIDATOR      │         │    RESOLVER      │               │
│  │                  │         │                  │               │
│  │ • Fair Work Act  │ Violations│ • Generate fixes│               │
│  │ • Peak coverage  │─────────▶│ • Negotiate bids │               │
│  │ • Hours limits   │         │ • Rank by impact │               │
│  │ • Skill/stations │◀────────│ • Apply changes  │               │
│  └──────────────────┘ Updated └──────────────────┘               │
│                       Schedule                                    │
└──────────────────────────────────────────────────────────────────┘
                                    │
          ┌─────────────────────────┴─────────────────────────┐
          ▼                                                   ▼
┌──────────────────┐                              ┌──────────────────┐
│    EXPLAINER     │                              │     ROSTER       │
│    (LLM-Powered) │                              │   GENERATOR      │
│                  │                              │                  │
│ • Generate summary│                              │ • Export Excel   │
│ • Explain decisions│                             │ • Color coding   │
│ • Manager approvals│                             │ • Multi-sheets   │
└──────────────────┘                              └──────────────────┘ 
```

### Message Bus Communication

```
┌─────────────────────────────────────────────────────────────────┐
│                        MESSAGE BUS                               │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐            │
│  │ REQUEST │  │  DATA   │  │VIOLATION│  │COMPLETE │            │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘            │
│       │            │            │            │                  │
│  Agent A ──────────────────────────────────▶ Agent B            │
│       │     Typed Messages with Correlation IDs                 │
│       │            │            │            │                  │
│  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐  ┌────┴────┐            │
│  │RESPONSE │  │SCHEDULE │  │APPROVAL │  │ STATUS  │            │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

**What you'll see in logs (bus examples)**
- `[MessageBus] DataLoader → Coordinator (data) correlation=2d313a2c | {'status': 'loaded', 'employee_count': 40, 'store_count': 2}`
- `[MessageBus] ComplianceValidator → ConflictResolver (violation) correlation=e4b06660 | {'violations': [...]}`
- `[MessageBus] ConflictResolver → Coordinator (resolution_selected) correlation=0bf632b8 | {'violation': '...', 'resolution': '...'}`
- `[MessageBus] RosterGenerator → Coordinator (complete) correlation=cae6315d | {'type': 'roster_generated', 'filepath': 'output/roster_Store_1_2024-12-09_20251211.xlsx', ...}`

### Workflow Phases

```
Phase 1: DATA LOADING ────────▶ Load 40 employees, 2 stores, shift codes, manager roster
Phase 2: DEMAND FORECASTING ──▶ Generate 14-day staffing requirements (peak/off-peak, weekend uplift)
Phase 3: INITIAL MATCHING ────▶ Create ~200 initial assignments via bidding/auction
Phase 4: VALIDATION LOOP ─────▶ Iterate: Validate → Resolve/Negotiate → Repeat (max 5 iterations)
Phase 5: FINAL VALIDATION ────▶ Confirm 0 hard violations
Phase 5.5: MANAGER ESCALATION ▶ Human-in-the-loop for unresolved hard constraints
Phase 6: EXPLANATIONS ────────▶ LLM-generated summaries & recommendations
Phase 7: EXPORT ──────────────▶ Multi-sheet Excel roster
```

---

## 🚀 Quick Start

### Web Interface (Streamlit)

```bash
# Install dependencies
pip install -r requirements.txt

# Launch web interface
python -m streamlit run streamlit_app.py

# Opens at http://localhost:8501
```
If you prefer to test it directly in the cloud (no local setup), use: https://yepaimultiagentworkforceschedulingsystem.streamlit.app/

The web interface provides:
- Interactive store selection (CBD Core or Suburban Residential)
- Real-time agent status updates
- Results dashboard with compliance metrics
- Coverage quality visualization
- Fairness (Gini coefficient) display
- Schedule preview with filtering
- Excel roster download
- Store comparison view

---

## 📊 Features - start from here today!

### Core Capabilities
- ✅ **Intelligent Roster Generation**: 40 employees, 2-week schedule, <180 seconds
- ✅ **Peak Coverage Optimization**: Lunch (11-14), Dinner (17-21), Weekends +20%
- ✅ **Conflict Detection & Resolution**: Automatic violation detection with ranked solutions
- ✅ **Employee Skill Matching**: Kitchen, Counter, McCafe, Dessert station assignments
- ✅ **Fair Work Compliance**: Australian labor law validation

### Advanced Features
- 🔄 **Cross-Training**: McCafe/Counter staff can cover Dessert Station
- 👤 **Human-in-the-Loop**: Unresolvable issues escalate to manager approval
- 🤖 **LLM Explanations**: AI-generated summaries using free OpenRouter models
- 📊 **Multi-Sheet Excel**: Roster, Employee Summary, Coverage, Compliance sheets

---

## 📁 Project Structure

```
mcdonald_scheduling_system/
├── agents/                     # 🤖 Multi-Agent System
│   ├── base_agent.py           #    Abstract base class
│   ├── coordinator.py          #    Master orchestrator
│   ├── data_loader.py          #    CSV data loading
│   ├── demand_forecaster.py    #    Staffing predictions
│   ├── staff_matcher.py        #    Employee-shift matching
│   ├── compliance_validator.py #    Constraint checking
│   ├── conflict_resolver.py    #    Resolution generation
│   ├── explainer.py            #    LLM-powered explanations
│   └── roster_generator.py     #    Excel export
│
├── models/                     # 📦 Data Models
│   ├── employee.py             #    Employee, Station, EmployeeType
│   ├── shift.py                #    Shift, TimeSlot, ShiftType
│   ├── schedule.py             #    Schedule, Assignment
│   ├── constraints.py          #    Violation, ComplianceResult
│   └── store.py                #    Store configuration
│
├── communication/              # 📨 Agent Communication
│   ├── message.py              #    Message protocol
│   └── message_bus.py          #    Pub/sub messaging
│
├── data/                       # 📂 Input Data (CSV)
├── output/                     # 📤 Generated Rosters
├── config.py                   # ⚙️  LLM configuration
├── streamlit_app.py            # 🌐 Web interface (main entry point)
├── benchmark.py                # ⚡ Standalone performance testing tool
└── requirements.txt            # 📋 Dependencies
```

---

## 🔧 Configuration

### OpenRouter API (Free LLM Models)

The Explainer agent uses OpenRouter with free models. Get your API key at [openrouter.ai/keys](https://openrouter.ai/keys)

```bash
# Set your OpenRouter API key
export OPENROUTER_API_KEY="your-key-here"
```

**Free Models Used:**
- Primary: `mistralai/mistral-7b-instruct:free` (Mistral - backup)
- Fallback: `google/gemma-2-9b-it:free` (Google Gemma 2 - reliable)

Note: The system works without an API key (uses template-based explanations).

### Performance Benchmarking (Optional)

The `benchmark.py` file is a standalone performance testing tool that can be run independently:

```bash
# Run performance benchmarks
python benchmark.py
```

**What it does:**
- Tests data loading performance (CSV parsing)
- Tests demand forecasting performance
- Provides statistical analysis (mean, median, std dev)
- Collects profiling data from `@profile_function` decorators

**Note:** Warnings about "Coordinator not found" are expected in standalone benchmark mode - agents are tested individually without the full system running.

---

## 📈 Success Metrics

| Metric | Target | Achieved |
|--------|--------|----------|
| Roster Generation Time | < 180s | ✅ **9 seconds** |
| Hard Constraint Compliance | 100% | ✅ **0 violations** |
| Employees Scheduled | 40 | ✅ **40** |
| Peak Coverage | Optimized | ✅ |
| Conflict Resolution | Automatic | ✅ **4 iterations** |

---

## 🎯 Constraint Handling

### Hard Constraints (Must Satisfy)
| Constraint | Description | Source |
|------------|-------------|--------|
| Availability | Employee must be available for assigned shift | Business |
| Skill Match | Employee must be trained for station | Business |
| Max Hours | Full-time ≤38h, Part-time ≤32h, Casual ≤24h | Fair Work Act |
| Rest Period | Minimum 10 hours between shifts | Fair Work Act |
| Consecutive Days | Maximum 6 consecutive working days | Fair Work Act |
| Min Staffing | At least 2 staff on duty, 1 per station | Business |

### Soft Constraints (Should Optimize)
| Constraint | Description |
|------------|-------------|
| Min Hours | Meet target minimum hours per employee type |
| Peak Coverage | Optimal staffing during lunch/dinner rush |
| Fair Distribution | Balance shifts across employees |
| Preferences | Respect employee shift preferences |

---

## 🏆 Yep AI x McDonald's Challenge

Built for the Yep AI Multi-Agent Challenge, December 2024.

### Key Innovations
1. **Hybrid Agent Architecture**: Deliberative planning + Reactive conflict handling
2. **Cross-Training System**: Flexible station coverage
3. **Human-in-the-Loop**: Manager escalation for edge cases
4. **Deterministic Core**: LLM only for explanations, not decisions

---

## 📜 License

MIT License - Built for Yep AI Challenge
