# Glossary

> Every technical term used in this project, alphabetically ordered.

---

| Term | Definition |
|---|---|
| **ALT** | Accelerated Life Test — reliability test type; very high test time |
| **AT** | Acceptance Test — final acceptance test type |
| **AUC-PR** | Area Under Precision-Recall Curve — classification metric preferred over AUC-ROC for imbalanced datasets |
| **AUC-ROC** | Area Under Receiver Operating Characteristic Curve — classification metric; inflated for imbalanced classes |
| **Beta distribution** | Probability distribution bounded [0,1]; used to model yield uncertainty in Monte Carlo |
| **BIT** | Built-In Test — functional test type |
| **Bottleneck** | Condition where demand exceeds supply (gap% < 0) |
| **Bronze layer** | First DuckDB layer; validated, typed, deduplicated copy of raw SQLite data; prefix `brnz_` |
| **CapEx** | Capital Expenditure — cost of purchasing new test equipment |
| **Capacity** | Maximum DUTs a tester fleet can process in a period given all operational parameters |
| **Capacity mode** | NORMAL (standard shifts) or MAXIMUM (extended shifts) |
| **ChatOllama** | LangChain wrapper around Ollama's local LLM API |
| **Child demand** | `parent_demand × child_quantity` — no ratio split |
| **Contamination** | Isolation Forest parameter: expected fraction of anomalies (set to 0.05) |
| **Croston's method** | Intermittent demand forecasting method; separates demand size from inter-arrival interval |
| **CV** | Coefficient of Variation — `std / mean`; used to parameterise demand uncertainty in Monte Carlo |
| **Cycle time** | Total elapsed time per DUT including handling + test |
| **DuckDB** | In-process columnar analytics database; holds all Bronze/Silver/Gold data in one file |
| **DUT** | Device Under Test — unit being tested on the tester |
| **Effective demand** | `parent_demand_qty × child_quantity` — demand after hierarchy expansion |
| **FCT** | Functional Circuit Test — functional test type |
| **Feature store** | `gold_ml_feature_store` — single wide table feeding all 5 ML models |
| **Flexibility %** | `(supply_max − supply_normal) / supply_normal × 100` — surge capacity headroom |
| **Gap %** | `(supply − demand) / demand × 100` — primary capacity adequacy metric |
| **GCM** | Global Capacity Model — master join of product, equipment, and operational parameters |
| **Gold layer** | Business-ready DuckDB layer; 5-step capacity math output; prefix `gold_` and `srv_vw_` |
| **Handling time** | Seconds to load/unload one DUT; does not include test execution time |
| **ICT** | In-Circuit Test — functional test type |
| **Isolation Forest** | Unsupervised anomaly detection algorithm; isolates anomalies via random feature splitting |
| **LangGraph** | Graph-based agent orchestration framework; models agents as nodes in a directed state graph |
| **llama3.1:8b** | Local LLM via Ollama; chosen for native tool/function calling support |
| **MCP** | Model Context Protocol — structured tool-calling protocol over stdio JSON-RPC 2.0 |
| **Medallion architecture** | Layered data design: Raw → Bronze → Silver → Gold |
| **Method of moments** | Technique to fit Beta distribution parameters from sample mean and variance |
| **Month key** | Integer yyyymm format (e.g. 202301 = January 2023) |
| **NPI** | New Product Introduction — product with < 12 months history or < 3 qualified sites |
| **OEE** | Overall Equipment Effectiveness = Availability × Performance × Quality |
| **Ollama** | Local LLM runtime; runs quantised models without cloud API |
| **OTA** | Over-the-Air — RF test type; highest equipment cost |
| **OtherImpediments** | Locked to 0; all impediments captured in allowance and productivity |
| **P50 / P80 / P95** | Monte Carlo percentiles; P80 is the recommended planning target |
| **PAM** | Power Amplifier Module — RF test type |
| **PIM** | Passive Intermodulation — RF test type |
| **Planning horizon** | 18 months forward from Jul 2026 (Jul 2026 – Dec 2027) |
| **Productivity** | Fraction of non-allowance shift time resulting in productive output (default 0.95) |
| **Prophet** | Facebook/Meta time-series forecasting library; handles trend + seasonality |
| **PySpark** | Python API for Apache Spark; used in Silver layer for scalable transforms |
| **Retest** | Second (or further) test attempt for a DUT that failed first-pass |
| **Router** | LangGraph node that classifies user intent and directs to a domain agent |
| **SHAP** | SHapley Additive exPlanations — feature attribution method with exact Shapley values |
| **Silver layer** | Second DuckDB layer; joined, enriched, feature-engineered; prefix `slvr_` |
| **Snapshot** | Point-in-time capture of the production plan; two exist in this dataset |
| **SMOTE** | Synthetic Minority Oversampling Technique — generates synthetic minority class samples |
| **SSE** | Server-Sent Events — HTTP streaming protocol for real-time token delivery |
| **Step 1–5** | The five steps of the capacity math engine; see [Capacity Planning](./capacity-planning.md) |
| **TreeExplainer** | SHAP method for tree models; exact computation in $O(TLD^2)$ |
| **TRX** | Transceiver — RF test type |
| **UC** | Utilisation Check — acceptance test type |
| **Utilisation rate** | Fraction of available tester time spent productively (parameter in GCM config) |
| **uv** | Fast Python package manager replacing pip + venv |
| **Yield** | Fraction of DUTs passing on first test attempt (0–1) |
| **Yield forward-fill** | Carrying last known yield forward to months with missing data |
| **Yield feedback loop** | ML-predicted yield replaces static yield in capacity math → `gold_cap_ml_adjusted` |
