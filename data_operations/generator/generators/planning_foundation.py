"""Generate bounded source facts for S&OP, NPI, operations flow, and scenarios."""

from __future__ import annotations

import hashlib
import sqlite3
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from capacity_twin_core.runtime.database_paths import get_sqlite_path
from data_operations.generator.catalogs.contract_tables import (
    build_resource_contracts,
    build_routes,
)
from data_operations.generator.generators.assignment_matrix import ASSIGNMENT_MATRIX
from data_operations.generator.generators.product_master import PRODUCTS
from data_operations.generator.generators.reference_data import FIXTURES, SYSTEMS


def _id(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]


def _stable_int(*parts: object, modulo: int) -> int:
    return int(_id(*parts)[:12], 16) % modulo


def _month_starts(start: date, end: date) -> list[date]:
    current = start.replace(day=1)
    result: list[date] = []
    while current <= end:
        result.append(current)
        current = (
            date(current.year + 1, 1, 1)
            if current.month == 12
            else date(current.year, current.month + 1, 1)
        )
    return result


def _month_end(value: date, upper_bound: date) -> date:
    return min(
        date(value.year, value.month, monthrange(value.year, value.month)[1]),
        upper_bound,
    )


def _write(path: Path, tables: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with sqlite3.connect(path) as connection:
        for name, rows in tables.items():
            frame = pd.DataFrame(rows)
            if frame.empty:
                raise ValueError(f"Planning foundation table {name} cannot be empty")
            frame.to_sql(name, connection, if_exists="replace", index=False)
            counts[name] = len(frame)
    return counts


def _sop_tables(config: dict[str, Any]) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    generation = config["data_generation"]
    actual_start = date.fromisoformat(generation["start_date_actual"])
    actual_end = date.fromisoformat(generation["end_date_actual"])
    forecast_end = date.fromisoformat(generation["end_date_forecast"])
    months = _month_starts(actual_start, forecast_end)
    plan_as_of = max(date.fromisoformat(value) for value in generation["plan_as_of_dates"])
    planning_version = f"PV-{plan_as_of:%Y%m%d}"
    volume = config["volume_profiles"][generation["volume"]]
    demand_scale = float(volume["demand_scale"])

    demand_tables: dict[str, list[dict]] = {
        "customer_order": [],
        "backlog_position": [],
        "constrained_production_plan": [],
        "shared_resource_allocation": [],
    }
    inventory_tables: dict[str, list[dict]] = {
        "material_inventory_position": [],
        "inbound_receipt": [],
        "shipment": [],
        "safety_stock_policy": [],
        "service_target": [],
    }
    resources = build_resource_contracts()["product_resource_qualification"]
    primary_resources = {
        (row.site_code, row.product_number): row.resource_id
        for row in resources[resources["is_primary"] == 1].itertuples()
    }

    for assignment in sorted(
        ASSIGNMENT_MATRIX, key=lambda row: (row["site_code"], row["product_number"])
    ):
        site = assignment["site_code"]
        product = assignment["product_number"]
        policy_id = _id("safety", site, product)
        service_id = _id("service", site, product)
        inventory_tables["safety_stock_policy"].append(
            {
                "safety_stock_policy_id": policy_id,
                "site_code": site,
                "product_number": product,
                "effective_start_date": actual_start.isoformat(),
                "effective_end_date": forecast_end.isoformat(),
                "safety_stock_quantity_ea": max(
                    10, round((100 + _stable_int(product, modulo=180)) * demand_scale * 0.35)
                ),
                "coverage_days": 14 + _stable_int(site, product, modulo=15),
                "policy_status": "ACTIVE",
                "quantity_unit": "EA",
            }
        )
        inventory_tables["service_target"].append(
            {
                "service_target_id": service_id,
                "site_code": site,
                "product_number": product,
                "customer_segment": "STRATEGIC" if product.endswith(("1", "4", "7")) else "STANDARD",
                "effective_start_date": actual_start.isoformat(),
                "effective_end_date": forecast_end.isoformat(),
                "fill_rate_target_pct": 0.95 + _stable_int(product, modulo=4) / 100,
                "on_time_in_full_target_pct": 0.92 + _stable_int(site, modulo=5) / 100,
                "maximum_backlog_days": 5 + _stable_int(site, product, modulo=10),
                "target_status": "ACTIVE",
                "ratio_unit": "PCT",
            }
        )

        prior_ending = max(25, round(180 * demand_scale))
        prior_backlog = 0
        resource_id = primary_resources.get((site, product), SYSTEMS[0][0])
        for month in months:
            period_end = _month_end(month, forecast_end)
            period_start = max(month, actual_start)
            demand = max(
                12,
                round(
                    (100 + _stable_int(site, product, month.isoformat(), modulo=260))
                    * demand_scale
                ),
            )
            production = round(demand * (0.70 + _stable_int(product, month, modulo=9) / 100))
            receipts = round(demand * (0.17 + _stable_int(site, month, modulo=8) / 100))
            available = prior_ending + production + receipts
            shipments = min(available, round(demand * (0.86 + _stable_int(month, modulo=10) / 100)))
            ending = available - shipments
            ending_backlog = max(0, prior_backlog + demand - shipments)
            order_line_id = _id("order-line", site, product, month)
            order_date = min(period_start, actual_end)
            request_date = max(
                actual_start,
                min(month + timedelta(days=14), forecast_end),
            )

            demand_tables["customer_order"].append(
                {
                    "customer_order_line_id": order_line_id,
                    "customer_order_id": _id("order", site, product, month),
                    "customer_id": f"CUST-{_stable_int(site, product, modulo=40) + 1:03d}",
                    "site_code": site,
                    "product_number": product,
                    "order_date": order_date.isoformat(),
                    "requested_delivery_date": request_date.isoformat(),
                    "confirmed_delivery_date": min(
                        request_date + timedelta(days=_stable_int(order_line_id, modulo=5)),
                        forecast_end,
                    ).isoformat(),
                    "ordered_quantity_ea": demand,
                    "order_status": "SHIPPED" if period_end <= actual_end else "CONFIRMED",
                    "order_priority": "EXPEDITE" if ending_backlog > 0 else "STANDARD",
                    "quantity_unit": "EA",
                }
            )
            demand_tables["backlog_position"].append(
                {
                    "backlog_position_id": _id("backlog", order_line_id, period_end),
                    "position_date": period_end.isoformat(),
                    "customer_order_line_id": order_line_id,
                    "site_code": site,
                    "product_number": product,
                    "open_quantity_ea": ending_backlog,
                    "backlog_age_days": 0 if ending_backlog == 0 else 5 + _stable_int(order_line_id, modulo=25),
                    "backlog_status": "CLEAR" if ending_backlog == 0 else "OPEN",
                    "quantity_unit": "EA",
                }
            )
            demand_tables["constrained_production_plan"].append(
                {
                    "production_plan_id": _id("plan", site, product, month, planning_version),
                    "site_code": site,
                    "product_number": product,
                    "month_key": month.year * 100 + month.month,
                    "planning_version_id": planning_version,
                    "plan_as_of_date": plan_as_of.isoformat(),
                    "constrained_production_quantity_ea": production,
                    "constraint_reason_code": (
                        "RESOURCE_LIMIT" if ending_backlog > 0 else "NONE"
                    ),
                    "plan_status": "APPROVED",
                    "quantity_unit": "EA",
                }
            )
            allocated_hours = round(production * (45 + _stable_int(product, modulo=90)) / 3600, 3)
            demand_tables["shared_resource_allocation"].append(
                {
                    "resource_allocation_id": _id(
                        "allocation", site, product, resource_id, month, planning_version
                    ),
                    "site_code": site,
                    "product_number": product,
                    "resource_id": resource_id,
                    "month_key": month.year * 100 + month.month,
                    "planning_version_id": planning_version,
                    "plan_as_of_date": plan_as_of.isoformat(),
                    "allocated_resource_hours": allocated_hours,
                    "allocation_ratio_pct": round(0.55 + _stable_int(product, modulo=35) / 100, 4),
                    "allocation_status": "APPROVED",
                    "time_unit": "HR",
                    "ratio_unit": "PCT",
                }
            )
            inventory_tables["material_inventory_position"].append(
                {
                    "inventory_position_id": _id("inventory", site, product, period_end),
                    "position_date": period_end.isoformat(),
                    "site_code": site,
                    "product_number": product,
                    "inventory_class": "FINISHED_GOOD",
                    "beginning_inventory_quantity_ea": prior_ending,
                    "on_hand_quantity_ea": ending,
                    "reserved_quantity_ea": min(ending, ending_backlog),
                    "in_transit_quantity_ea": receipts,
                    "available_quantity_ea": max(0, ending - min(ending, ending_backlog)),
                    "quantity_unit": "EA",
                }
            )
            inventory_tables["inbound_receipt"].append(
                {
                    "inbound_receipt_line_id": _id("receipt", site, product, month),
                    "site_code": site,
                    "product_number": product,
                    "supplier_id": f"SUP-{_stable_int(product, modulo=18) + 1:03d}",
                    "expected_receipt_date": max(
                        actual_start,
                        min(month + timedelta(days=8), forecast_end),
                    ).isoformat(),
                    "actual_receipt_date": (
                        max(
                            actual_start,
                            min(month + timedelta(days=9), actual_end),
                        ).isoformat()
                        if period_end <= actual_end
                        else None
                    ),
                    "received_quantity_ea": receipts,
                    "receipt_status": "RECEIVED" if period_end <= actual_end else "PLANNED",
                    "quantity_unit": "EA",
                }
            )
            inventory_tables["shipment"].append(
                {
                    "shipment_line_id": _id("shipment", order_line_id),
                    "customer_order_line_id": order_line_id,
                    "site_code": site,
                    "product_number": product,
                    "shipment_date": period_end.isoformat(),
                    "shipped_quantity_ea": shipments,
                    "shipment_status": "SHIPPED" if period_end <= actual_end else "PLANNED",
                    "quantity_unit": "EA",
                }
            )
            prior_ending = ending
            prior_backlog = ending_backlog
    return demand_tables, inventory_tables


def _npi_tables(config: dict[str, Any]) -> dict[str, list[dict]]:
    generation = config["data_generation"]
    actual_start = date.fromisoformat(generation["start_date_actual"])
    actual_end = date.fromisoformat(generation["end_date_actual"])
    forecast_end = date.fromisoformat(generation["end_date_forecast"])
    npi_products = [row for row in PRODUCTS if row[6] == "NPI"]
    assigned_site = {
        row["product_number"]: row["site_code"]
        for row in reversed(ASSIGNMENT_MATRIX)
        if row["product_status"] == "NPI"
    }
    names = (
        "npi_program",
        "npi_stage_gate",
        "npi_milestone",
        "npi_qualification_evidence",
        "npi_pilot_lot",
        "npi_tooling_readiness",
        "npi_ramp_target",
        "npi_ramp_actual",
        "npi_risk",
        "npi_owner",
        "npi_status_history",
    )
    tables: dict[str, list[dict]] = {name: [] for name in names}
    months = _month_starts(actual_start, forecast_end)
    owners = ("Program Manager", "Manufacturing Lead", "Test Lead", "Quality Lead")

    for index, product in enumerate(npi_products):
        product_number = product[0]
        site = assigned_site[product_number]
        program_id = f"NPI-{index + 1:03d}"
        launch = min(actual_start + timedelta(days=180 + index * 21), forecast_end)
        program_start = max(actual_start, launch - timedelta(days=180))
        program_status = "LAUNCHED" if launch <= actual_end else "IN_PROGRESS"
        tables["npi_program"].append(
            {
                "program_id": program_id,
                "program_name": f"{product_number} launch",
                "product_number": product_number,
                "lead_site_code": site,
                "planned_launch_date": launch.isoformat(),
                "effective_start_date": program_start.isoformat(),
                "effective_end_date": forecast_end.isoformat(),
                "program_status": program_status,
            }
        )
        for owner_index, role in enumerate(owners):
            tables["npi_owner"].append(
                {
                    "program_owner_id": _id(program_id, role),
                    "program_id": program_id,
                    "owner_role": role,
                    "owner_name": f"Owner {index + 1}-{owner_index + 1}",
                    "effective_start_date": program_start.isoformat(),
                    "effective_end_date": forecast_end.isoformat(),
                    "owner_status": "ACTIVE",
                }
            )
        for gate_number, gate_name in enumerate(("CONCEPT", "DESIGN", "QUALIFY", "PILOT", "LAUNCH"), 1):
            planned = min(program_start + timedelta(days=35 * gate_number), forecast_end)
            actual = min(planned + timedelta(days=(index + gate_number) % 6), actual_end)
            gate_status = "PASSED" if planned <= actual_end else "PLANNED"
            gate_id = _id(program_id, "gate", gate_number)
            tables["npi_stage_gate"].append(
                {
                    "stage_gate_id": gate_id,
                    "program_id": program_id,
                    "gate_sequence": gate_number,
                    "gate_name": gate_name,
                    "planned_gate_date": planned.isoformat(),
                    "actual_gate_date": actual.isoformat() if gate_status == "PASSED" else None,
                    "gate_status": gate_status,
                    "approval_evidence_id": _id("approval", gate_id) if gate_status == "PASSED" else None,
                }
            )
            tables["npi_milestone"].append(
                {
                    "milestone_id": _id(program_id, "milestone", gate_number),
                    "program_id": program_id,
                    "stage_gate_id": gate_id,
                    "milestone_name": f"{gate_name.title()} exit criteria",
                    "planned_date": planned.isoformat(),
                    "actual_date": actual.isoformat() if gate_status == "PASSED" else None,
                    "milestone_status": "COMPLETE" if gate_status == "PASSED" else "OPEN",
                }
            )
        for evidence_index, evidence_type in enumerate(("PROCESS", "TEST", "YIELD"), 1):
            evidence_date = min(program_start + timedelta(days=70 + evidence_index * 18), actual_end)
            tables["npi_qualification_evidence"].append(
                {
                    "qualification_evidence_id": _id(program_id, evidence_type),
                    "program_id": program_id,
                    "site_code": site,
                    "evidence_type": evidence_type,
                    "evidence_date": evidence_date.isoformat(),
                    "result_status": "ACCEPTED" if evidence_date < actual_end else "UNDER_REVIEW",
                    "evidence_reference": f"QE-{program_id}-{evidence_index:02d}",
                    "approved_by_role": "Quality Lead",
                }
            )
        for lot_sequence in range(1, 5):
            lot_date = min(program_start + timedelta(days=95 + lot_sequence * 14), actual_end)
            started = 40 + lot_sequence * 20
            passed = round(started * (0.72 + lot_sequence * 0.05))
            tables["npi_pilot_lot"].append(
                {
                    "pilot_lot_id": _id(program_id, "pilot", lot_sequence),
                    "program_id": program_id,
                    "site_code": site,
                    "lot_sequence": lot_sequence,
                    "lot_start_date": lot_date.isoformat(),
                    "lot_complete_date": min(lot_date + timedelta(days=3), actual_end).isoformat(),
                    "started_quantity_ea": started,
                    "passed_quantity_ea": passed,
                    "yield_pct": round(passed / started, 4),
                    "pilot_lot_status": "COMPLETE",
                    "quantity_unit": "EA",
                    "ratio_unit": "PCT",
                }
            )
        for tooling_type in ("FIXTURE", "PROGRAM", "GAUGE"):
            readiness = 0.82 + _stable_int(program_id, tooling_type, modulo=18) / 100
            tables["npi_tooling_readiness"].append(
                {
                    "tooling_readiness_id": _id(program_id, tooling_type),
                    "program_id": program_id,
                    "site_code": site,
                    "tooling_type": tooling_type,
                    "required_quantity_ea": 1 + _stable_int(tooling_type, modulo=4),
                    "ready_quantity_ea": 1 + _stable_int(tooling_type, modulo=4),
                    "readiness_pct": min(1.0, readiness),
                    "effective_date": min(actual_end, launch).isoformat(),
                    "readiness_status": "READY" if readiness >= 0.9 else "AT_RISK",
                    "quantity_unit": "EA",
                    "ratio_unit": "PCT",
                }
            )
        cumulative_actual = 0
        for month_index, month in enumerate(months):
            if month < program_start.replace(day=1):
                continue
            target = min(1200, 80 + month_index * 55)
            actual = round(target * (0.72 + min(0.24, month_index * 0.015)))
            tables["npi_ramp_target"].append(
                {
                    "ramp_target_id": _id(program_id, "target", month),
                    "program_id": program_id,
                    "site_code": site,
                    "month_key": month.year * 100 + month.month,
                    "target_quantity_ea": target,
                    "target_yield_pct": min(0.98, 0.78 + month_index * 0.01),
                    "target_status": "APPROVED",
                    "quantity_unit": "EA",
                    "ratio_unit": "PCT",
                }
            )
            if month <= actual_end.replace(day=1):
                cumulative_actual += actual
                tables["npi_ramp_actual"].append(
                    {
                        "ramp_actual_id": _id(program_id, "actual", month),
                        "program_id": program_id,
                        "site_code": site,
                        "month_key": month.year * 100 + month.month,
                        "actual_quantity_ea": actual,
                        "actual_yield_pct": min(0.97, 0.74 + month_index * 0.012),
                        "cumulative_quantity_ea": cumulative_actual,
                        "actual_status": "REPORTED",
                        "quantity_unit": "EA",
                        "ratio_unit": "PCT",
                    }
                )
        risk_status = "OPEN" if launch > actual_end else "CLOSED"
        tables["npi_risk"].append(
            {
                "risk_id": _id(program_id, "risk"),
                "program_id": program_id,
                "risk_category": "RAMP",
                "risk_description": "Synthetic ramp readiness exposure",
                "probability_pct": 0.25 + _stable_int(program_id, modulo=25) / 100,
                "impact_score": 2 + _stable_int(program_id, modulo=4),
                "mitigation_owner_role": "Program Manager",
                "effective_date": program_start.isoformat(),
                "risk_status": risk_status,
                "ratio_unit": "PCT",
            }
        )
        history_dates = sorted({program_start, min(program_start + timedelta(days=90), actual_end), min(launch, actual_end)})
        for sequence, status_date in enumerate(history_dates, 1):
            tables["npi_status_history"].append(
                {
                    "status_history_id": _id(program_id, "status", sequence),
                    "program_id": program_id,
                    "status_sequence": sequence,
                    "status_effective_at": datetime.combine(status_date, time(8)).isoformat(),
                    "program_status": ("PLANNED", "QUALIFYING", program_status)[min(sequence - 1, 2)],
                    "status_reason": "Synthetic governed lifecycle transition",
                }
            )
    return tables


def _operations_tables(config: dict[str, Any]) -> dict[str, list[dict]]:
    generation = config["data_generation"]
    actual_start = date.fromisoformat(generation["start_date_actual"])
    actual_end = date.fromisoformat(generation["end_date_actual"])
    stride = int(config["volume_profiles"][generation["volume"]]["execution_day_stride"])
    sample_start = max(actual_start, actual_end - timedelta(days=56))
    working_days = [
        sample_start + timedelta(days=offset)
        for offset in range((actual_end - sample_start).days + 1)
        if (sample_start + timedelta(days=offset)).weekday() < 5
    ]
    days = working_days[::stride] or [actual_end]
    route_frame, step_frame = build_routes()
    route_by_product = dict(
        zip(route_frame["product_number"], route_frame["route_id"], strict=True)
    )
    steps_by_route = {
        route_id: group.sort_values("step_sequence").to_dict("records")
        for route_id, group in step_frame.groupby("route_id")
    }
    qualifications = build_resource_contracts()["product_resource_qualification"]
    resource_by_key = {
        (row.site_code, row.product_number, row.test_type): row.resource_id
        for row in qualifications[qualifications["is_primary"] == 1].itertuples()
    }
    movement_rows: list[dict] = []
    schedule_rows: list[dict] = []
    lot_limit = int(config["local_16gb"].get("max_operations_lots", 12000))
    lot_count = 0
    for assignment in sorted(
        ASSIGNMENT_MATRIX, key=lambda row: (row["site_code"], row["product_number"])
    ):
        if lot_count >= lot_limit:
            break
        site = assignment["site_code"]
        product = assignment["product_number"]
        route_id = route_by_product[product]
        steps = steps_by_route[route_id]
        for day in days:
            if lot_count >= lot_limit:
                break
            lot_count += 1
            work_order_id = f"WO-{_id(site, product, day)[:16]}"
            lot_id = f"LOT-{_id(work_order_id)[:16]}"
            planned_qty = 24 + _stable_int(work_order_id, modulo=77)
            quantity = planned_qty
            start_ts = datetime.combine(day, time(6)) + timedelta(
                minutes=_stable_int(work_order_id, modulo=120)
            )
            previous_event_id: str | None = None
            in_progress = lot_count % 11 == 0
            emitted_steps = steps[:-1] if in_progress and len(steps) > 1 else steps
            first_event_index = len(movement_rows)
            for step_index, step in enumerate(emitted_steps):
                queue_entry = start_ts + timedelta(minutes=step_index * 95)
                queue_age = 8 + _stable_int(work_order_id, step_index, modulo=75)
                queue_exit = queue_entry + timedelta(minutes=queue_age)
                cycle_minutes = 12 + _stable_int(product, step_index, modulo=38)
                event_ts = queue_exit + timedelta(minutes=cycle_minutes)
                event_id = _id("movement", lot_id, step["route_step_id"])
                disposition = "PASS"
                rework_link = None
                if step_index == len(emitted_steps) - 1 and not in_progress and lot_count % 17 == 0:
                    disposition = "REWORK"
                    rework_link = previous_event_id
                elif step_index == len(emitted_steps) - 1 and not in_progress and lot_count % 29 == 0:
                    disposition = "SCRAP"
                    quantity = max(0, quantity - 1)
                movement_rows.append(
                    {
                        "movement_event_id": event_id,
                        "lot_id": lot_id,
                        "work_order_id": work_order_id,
                        "site_code": site,
                        "product_number": product,
                        "route_id": route_id,
                        "route_step_id": step["route_step_id"],
                        "route_step_sequence": step["step_sequence"],
                        "from_operation": "RELEASE" if step_index == 0 else steps[step_index - 1]["test_type"],
                        "to_operation": step["test_type"],
                        "queue_entry_at": queue_entry.isoformat(),
                        "queue_exit_at": queue_exit.isoformat(),
                        "movement_event_at": event_ts.isoformat(),
                        "input_quantity_ea": planned_qty if step_index == 0 else quantity,
                        "output_quantity_ea": quantity,
                        "disposition_code": disposition,
                        "rework_link_event_id": rework_link,
                        "machine_id": resource_by_key.get(
                            (site, product, step["test_type"]), SYSTEMS[0][0]
                        ),
                        "resource_id": resource_by_key.get(
                            (site, product, step["test_type"]), SYSTEMS[0][0]
                        ),
                        "event_status": "POSTED",
                        "quantity_unit": "EA",
                    }
                )
                previous_event_id = event_id
            completion = movement_rows[-1]["movement_event_at"]
            schedule_rows.append(
                {
                    "production_schedule_line_id": _id("schedule", work_order_id),
                    "work_order_id": work_order_id,
                    "lot_id": lot_id,
                    "site_code": site,
                    "product_number": product,
                    "scheduled_start_at": start_ts.isoformat(),
                    "scheduled_complete_at": (start_ts + timedelta(hours=10)).isoformat(),
                    "actual_start_at": movement_rows[first_event_index]["queue_entry_at"],
                    "actual_complete_at": None if in_progress else completion,
                    "planned_quantity_ea": planned_qty,
                    "completed_quantity_ea": 0 if in_progress else quantity,
                    "schedule_status": "IN_PROGRESS" if in_progress else "COMPLETE",
                    "quantity_unit": "EA",
                }
            )
    return {
        "lot_route_movement_event": movement_rows,
        "production_schedule": schedule_rows,
    }


def _equipment_cost_table(config: dict[str, Any]) -> list[dict]:
    start = config["data_generation"]["start_date_actual"]
    end = config["data_generation"]["end_date_forecast"]
    resources = [*SYSTEMS, *FIXTURES]
    return [
        {
            "equipment_cost_reference_id": _id("equipment-cost", row[0]),
            "equipment_id": row[0],
            "effective_start_date": start,
            "effective_end_date": end,
            "purchase_cost_usd": 65_000 + index * 12_500,
            "annual_maintenance_cost_usd": 4_500 + index * 700,
            "installation_cost_usd": 7_500 + index * 900,
            "lead_time_days": 45 + (index % 8) * 15,
            "currency_code": "USD",
            "cost_status": "APPROVED",
        }
        for index, row in enumerate(resources)
    ]


def generate_planning_foundation(config: dict[str, Any]) -> dict[str, int]:
    """Write all Phase 6 source facts into the existing nine-file source bundle."""
    demand_tables, inventory_tables = _sop_tables(config)
    outputs = {
        **_write(
            get_sqlite_path(config["databases"]["raw"]["demand"], config),
            demand_tables,
        ),
        **_write(
            get_sqlite_path(config["databases"]["raw"]["inventory"], config),
            inventory_tables,
        ),
        **_write(
            get_sqlite_path(config["databases"]["raw"]["npi"], config),
            _npi_tables(config),
        ),
        **_write(
            get_sqlite_path(config["databases"]["raw"]["execution"], config),
            _operations_tables(config),
        ),
    }
    machine_path = get_sqlite_path(config["databases"]["raw"]["machine"], config)
    outputs.update(_write(machine_path, {"equipment_cost_reference": _equipment_cost_table(config)}))
    return outputs
