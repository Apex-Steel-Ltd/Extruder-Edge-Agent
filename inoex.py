import asyncio
from asyncua import Client

# Production script for Frappe/ERPNext integration
# Machine: Battenfeld-Cincinnati BCtouch UX (PE-630 / PE-63)
# Protocol: OPC UA | Port: 48031
# Sheet: FM06.17 Production Log Sheet PE/PPR 63
#
# CONFIRMED ZONE MAPPING (verified on physical machine 10-Jun-2026):
#
#   Feed zone (~52°C, water-cooled) = MeasurementZones.Feeding_Act
#   C1        = BarrelZone_001   (~198-200°C)
#   C2        = BarrelZone_002   (~200°C)
#   C3        = BarrelZone_003   (~200°C)
#   C4        = BarrelZone_004   (~200°C)
#   C5        = BarrelZone_005   (~200°C, cylinder:5 on screen)
#   AD        = Adapter_001      (~200°C, confirmed physical visit)
#   D1-D10    = DieZone_001-010
#
# JOCKEY TEMPS (B1/B2, B3/D1, D2/D3 on sheet):
#   NOT in OPC UA. All Feedblock/Dielip/Meltpipe nodes are unused (Active=0).
#   These come from a separate downstream instrument — manual entry only.

async def read_machine_data(machine_ip):
    OPCUA_URL = f"opc.tcp://{machine_ip}:48031"
    """
    Connects to the BCtouch UX OPC UA server and returns a dict
    of all production parameters for Frappe/ERPNext.
    Covers FM06.17 Production Log Sheet (both pages).
    """
    machine_data = {}
    client = Client(url=OPCUA_URL, timeout=10)

    original_create_session = client.uaclient.create_session
    async def custom_create_session(params):
        params.ServerUri = "urn:5801914-010:battenfeldcincinnati:bcuasvr"
        return await original_create_session(params)
    client.uaclient.create_session = custom_create_session

    await client.connect()

    try:
        nodes_to_read = {

            # ── BPC Line throughput ───────────────────────────────────────
            "weight_per_hour_line_set":          "ns=2;s=Extruder_001.BPC.Weight_per_hour_Line_Set",
            "weight_per_hour_line_actual":       "ns=2;s=Extruder_001.BPC.Weight_per_hour_Line_Act",
            "weight_per_hour_actual_E1":         "ns=2;s=Extruder_001.BPC.Weight_per_hour_Act",
            "weight_per_hour_set_E1":            "ns=2;s=Extruder_001.BPC.Weight_per_hour_Set",
            "weight_per_hour_actual_E2":         "ns=2;s=Extruder_002.BPC.Weight_per_hour_Act",
            "weight_per_hour_set_E2":            "ns=2;s=Extruder_002.BPC.Weight_per_hour_Set",

            # ── IGS / Gravimetric counters ────────────────────────────────
            "igs1_material_order_actual":        "ns=2;s=Extruder_001.Gravi.Gravimetric_[0]_Counter_Order",
            "igs2_material_order_actual":        "ns=2;s=Extruder_002.Gravi.Gravimetric_[0]_Counter_Order",
            "e1_material_total":                 "ns=2;s=Extruder_001.Gravi.Gravimetric_[0]_Counter_Total",
            "e2_material_total":                 "ns=2;s=Extruder_002.Gravi.Gravimetric_[0]_Counter_Total",

            # ── Caterpillar / Haul-off ────────────────────────────────────
            "caterpillar_speed_actual":          "ns=2;s=Extruder_001.puller.puller_Speed_Act",
            "caterpillar_speed_set":             "ns=2;s=Extruder_001.puller.puller_Speed_Set",
            "caterpillar_torque_master":         "ns=2;s=Extruder_001.puller.puller_Load_Act",

            # ── Saw / Cutter ──────────────────────────────────────────────
            "saw_actual_length":                 "ns=2;s=Extruder_001.saw.saw_actual_length",
            "saw_product_length_set":            "ns=2;s=Extruder_001.saw.saw_product[1]_length_Set",
            "saw_actual_qty_pieces":             "ns=2;s=Extruder_001.saw.saw_product[1]_pieces_Act",

            # ── IUS Ultrasonic Scanner ────────────────────────────────────
            # Values are 0.0 when scanner is offline — this is normal
            "outer_diameter_mean":               "ns=2;s=Extruder_001.IUS.OuterDiameter_Mean",
            "wall_thickness_mean":               "ns=2;s=Extruder_001.IUS.Wallthickness_Mean",
            "wall_thickness_min":                "ns=2;s=Extruder_001.IUS.Wallthickness_Min",
            "ovality":                           "ns=2;s=Extruder_001.IUS.Ovality",
            "eccentricity":                      "ns=2;s=Extruder_001.IUS.Eccentricity",

            # ── Vacuum tank ───────────────────────────────────────────────
            "vacuum_tank_1":                     "ns=2;s=Extruder_001.tanks.Vacuum_Act_1",

            # ── Machine running state ─────────────────────────────────────
            "e1_running":                        "ns=2;s=Extruder_001.Maindrive.Extruder_Running",
            "e2_running":                        "ns=2;s=Extruder_002.Maindrive.Extruder_Running",

            # ── E1 Main drive ─────────────────────────────────────────────
            "e1_screw_speed_actual":             "ns=2;s=Extruder_001.Maindrive.Extruder_Screw_Act",
            "e1_screw_speed_set":                "ns=2;s=Extruder_001.Maindrive.Extruder_Screw_Set",
            "e1_melt_pressure_1_actual":         "ns=2;s=Extruder_001.Pressure.Melt_Pressure_1_Act",
            "e1_melt_pressure_2_actual":         "ns=2;s=Extruder_001.Pressure.Melt_Pressure_2_Act",
            "e1_melt_temperature_actual":        "ns=2;s=Extruder_001.TemperatureZones.MeasurementZones.Melttemperature_1_Act",
            "e1_melt_temperature_2_actual":      "ns=2;s=Extruder_001.TemperatureZones.MeasurementZones.Melttemperature_2_Act",
            "e1_torque_actual":                  "ns=2;s=Extruder_001.Maindrive.Extruder_Load_Act",

            # ── E1 Feed zone (water-cooled ~50°C) and water temp ─────────
            # Confirmed by operator: Feeding_Act = feed zone column on sheet
            "e1_feed_zone_actual":               "ns=2;s=Extruder_001.TemperatureZones.MeasurementZones.Feeding_Act",
            "e1_water_temp_actual":              "ns=2;s=Extruder_001.TemperatureZones.MeasurementZones.Watertemp_Act",

            # ── E1 Barrel zones — Actual + Set ───────────────────────────
            # Confirmed mapping: C1=BarrelZone_001 ... C5=BarrelZone_005
            "e1_c1_actual":                      "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_001.ActualValue",
            "e1_c1_set":                         "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_001.SetValue",
            "e1_c2_actual":                      "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_002.ActualValue",
            "e1_c2_set":                         "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_002.SetValue",
            "e1_c3_actual":                      "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_003.ActualValue",
            "e1_c3_set":                         "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_003.SetValue",
            "e1_c4_actual":                      "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_004.ActualValue",
            "e1_c4_set":                         "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_004.SetValue",
            "e1_c5_actual":                      "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_005.ActualValue",
            "e1_c5_set":                         "ns=2;s=Extruder_001.TemperatureZones.BarrelZone_005.SetValue",

            # ── E1 Adapter — Actual + Set ─────────────────────────────────
            # Confirmed: Adapter_001 = AD column, reads ~200°C
            "e1_ad_actual":                      "ns=2;s=Extruder_001.TemperatureZones.Adapter_001.ActualValue",
            "e1_ad_set":                         "ns=2;s=Extruder_001.TemperatureZones.Adapter_001.SetValue",

            # ── E1 Die zones — Actual + Set ───────────────────────────────
            # D9 reads ambient (~33°C) — water-cooled sizing zone, not a heater
            "e1_d1_actual":                      "ns=2;s=Extruder_001.TemperatureZones.DieZone_001.ActualValue",
            "e1_d1_set":                         "ns=2;s=Extruder_001.TemperatureZones.DieZone_001.SetValue",
            "e1_d2_actual":                      "ns=2;s=Extruder_001.TemperatureZones.DieZone_002.ActualValue",
            "e1_d2_set":                         "ns=2;s=Extruder_001.TemperatureZones.DieZone_002.SetValue",
            "e1_d3_actual":                      "ns=2;s=Extruder_001.TemperatureZones.DieZone_003.ActualValue",
            "e1_d3_set":                         "ns=2;s=Extruder_001.TemperatureZones.DieZone_003.SetValue",
            "e1_d4_actual":                      "ns=2;s=Extruder_001.TemperatureZones.DieZone_004.ActualValue",
            "e1_d4_set":                         "ns=2;s=Extruder_001.TemperatureZones.DieZone_004.SetValue",
            "e1_d5_actual":                      "ns=2;s=Extruder_001.TemperatureZones.DieZone_005.ActualValue",
            "e1_d5_set":                         "ns=2;s=Extruder_001.TemperatureZones.DieZone_005.SetValue",
            "e1_d6_actual":                      "ns=2;s=Extruder_001.TemperatureZones.DieZone_006.ActualValue",
            "e1_d6_set":                         "ns=2;s=Extruder_001.TemperatureZones.DieZone_006.SetValue",
            "e1_d7_actual":                      "ns=2;s=Extruder_001.TemperatureZones.DieZone_007.ActualValue",
            "e1_d7_set":                         "ns=2;s=Extruder_001.TemperatureZones.DieZone_007.SetValue",
            "e1_d8_actual":                      "ns=2;s=Extruder_001.TemperatureZones.DieZone_008.ActualValue",
            "e1_d8_set":                         "ns=2;s=Extruder_001.TemperatureZones.DieZone_008.SetValue",
            "e1_d9_actual":                      "ns=2;s=Extruder_001.TemperatureZones.DieZone_009.ActualValue",
            "e1_d9_set":                         "ns=2;s=Extruder_001.TemperatureZones.DieZone_009.SetValue",
            "e1_d10_actual":                     "ns=2;s=Extruder_001.TemperatureZones.DieZone_010.ActualValue",
            "e1_d10_set":                        "ns=2;s=Extruder_001.TemperatureZones.DieZone_010.SetValue",

            # ── E2 Main drive ─────────────────────────────────────────────
            "e2_screw_speed_actual":             "ns=2;s=Extruder_002.Maindrive.Extruder_Screw_Act",
            "e2_screw_speed_set":                "ns=2;s=Extruder_002.Maindrive.Extruder_Screw_Set",
            "e2_melt_pressure_actual":           "ns=2;s=Extruder_002.Pressure.Melt_Pressure_1_Act",
            "e2_melt_temperature_actual":        "ns=2;s=Extruder_002.TemperatureZones.MeasurementZones.Melttemperature_1_Act",
            "e2_melt_temperature_2_actual":      "ns=2;s=Extruder_002.TemperatureZones.MeasurementZones.Melttemperature_2_Act",
            "e2_torque_actual":                  "ns=2;s=Extruder_002.Maindrive.Extruder_Load_Act",

            # ── E2 Feed zone ──────────────────────────────────────────────
            "e2_feed_zone_actual":               "ns=2;s=Extruder_002.TemperatureZones.MeasurementZones.Feeding_Act",

            # ── E2 Barrel zones — Actual + Set ───────────────────────────
            "e2_c1_actual":                      "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_001.ActualValue",
            "e2_c1_set":                         "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_001.SetValue",
            "e2_c2_actual":                      "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_002.ActualValue",
            "e2_c2_set":                         "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_002.SetValue",
            "e2_c3_actual":                      "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_003.ActualValue",
            "e2_c3_set":                         "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_003.SetValue",
            "e2_c4_actual":                      "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_004.ActualValue",
            "e2_c4_set":                         "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_004.SetValue",
            "e2_c5_actual":                      "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_005.ActualValue",
            "e2_c5_set":                         "ns=2;s=Extruder_002.TemperatureZones.BarrelZone_005.SetValue",

            # ── E2 Adapter ────────────────────────────────────────────────
            "e2_ad_actual":                      "ns=2;s=Extruder_002.TemperatureZones.Adapter_001.ActualValue",
            "e2_ad_set":                         "ns=2;s=Extruder_002.TemperatureZones.Adapter_001.SetValue",

            # ── E2 Die zones — Actual + Set (D1-D5 only for E2) ──────────
            "e2_d1_actual":                      "ns=2;s=Extruder_002.TemperatureZones.DieZone_001.ActualValue",
            "e2_d1_set":                         "ns=2;s=Extruder_002.TemperatureZones.DieZone_001.SetValue",
            "e2_d2_actual":                      "ns=2;s=Extruder_002.TemperatureZones.DieZone_002.ActualValue",
            "e2_d2_set":                         "ns=2;s=Extruder_002.TemperatureZones.DieZone_002.SetValue",
            "e2_d3_actual":                      "ns=2;s=Extruder_002.TemperatureZones.DieZone_003.ActualValue",
            "e2_d3_set":                         "ns=2;s=Extruder_002.TemperatureZones.DieZone_003.SetValue",
            "e2_d4_actual":                      "ns=2;s=Extruder_002.TemperatureZones.DieZone_004.ActualValue",
            "e2_d4_set":                         "ns=2;s=Extruder_002.TemperatureZones.DieZone_004.SetValue",
            "e2_d5_actual":                      "ns=2;s=Extruder_002.TemperatureZones.DieZone_005.ActualValue",
            "e2_d5_set":                         "ns=2;s=Extruder_002.TemperatureZones.DieZone_005.SetValue",
        }

        for key, node_id in nodes_to_read.items():
            try:
                node = client.get_node(node_id)
                value = await node.read_value()
                machine_data[key] = value
            except Exception:
                machine_data[key] = None

    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    return machine_data