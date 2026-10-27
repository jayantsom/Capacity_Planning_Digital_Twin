# Capacity Planning Fundamentals

The project models telecom/networking manufacturing routes for parent systems and made child modules. Capacity is evaluated against demand at a declared site, route step or test, resource pool, month, and planning-version grain.

## Demand

Demand is explicit:

- `DIRECT_CUSTOMER`
- `SPARE`
- `SERVICE`
- `BOM_DEPENDENT`

A child’s total requirement equals dependent BOM quantity plus separately identified independent demand. Effective-dated sourcing allocates made or purchased child quantities without double counting.

## Resource behaviors

| Behavior | Capacity treatment |
|---|---|
| Alternative pool | Pool qualified alternatives once |
| Serial step | Send full required demand through every required step |
| Paired fixture | Limit throughput by compatible tester-fixture-handler pairs |
| Multi-DUT | Limit parallel DUTs by channels, licences, slots, cavities, sockets, and efficiency |
| Standalone | Treat independently operating active fixtures as stations |
| Shared pool | Sum simultaneous qualified demand against one fleet |
| Dedicated | Serve only approved products |

## Core equations

For a simple single-DUT resource:

- adjusted cycle time = base handling/test time plus retest time;
- productive seconds per shift = shift hours × 3600 × (1 − allowance) × productivity;
- units per resource per shift = productive seconds ÷ adjusted cycle time;
- monthly fleet supply = units per shift × shifts × resource quantity;
- gap = supply − demand;
- utilization = demand ÷ supply.

Retest behavior may use fixed Type 1 parameters or measured Type 2 terms. Units must remain explicit, and division-by-zero or invalid ratio cases must fail validation rather than produce misleading output.

For multi-DUT resources, nominal slot count is insufficient. Effective parallelism is the minimum compatible physical/licensed limit, adjusted by synchronous/asynchronous cycle behavior, changeover, OEE, and parallel efficiency.

## OEE

OEE is:

`availability × performance × quality`

All three inputs are fractions internally. Presentation may convert them to percentages at the UI boundary.

## Scenarios

Normal and maximum capacity use explicit shift/calendar assumptions. They are deterministic scenarios, not forecasts. CapEx adds Monte Carlo uncertainty but remains simulation.

Bottleneck thresholds are app configuration, not universal telecom standards. Results are synthetic and must not be used for production decisions.
