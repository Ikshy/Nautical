import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)



BERTH_TYPES = {
    "cargo": {
        "name":             "Cargo Berth",
        "docking_time_hours": 3.0,    # পণ্য লোড/আনলোড সময় / Cargo load/unload time
        "capacity":         4,         # মোট বার্থ সংখ্যা / Total berths of this type
        "compatible_types": ["Cargo", "Container", "Bulk Carrier"],
    },
    "ferry": {
        "name":             "Ferry Terminal",
        "docking_time_hours": 1.0,    # ফেরি দ্রুত ছাড়ে / Ferries leave quickly
        "capacity":         3,
        "compatible_types": ["Ferry"],
    },
    "tanker": {
        "name":             "Tanker Berth",
        "docking_time_hours": 5.0,    # তেল পাম্পিং সময় / Oil pumping takes longer
        "capacity":         2,
        "compatible_types": ["Tanker"],
    },
    "cruise": {
        "name":             "Cruise Terminal",
        "docking_time_hours": 8.0,    # যাত্রী উঠা-নামার সময় / Passenger embark/disembark
        "capacity":         2,
        "compatible_types": ["Cruise"],
    },
    "general": {
        "name":             "General Berth",
        "docking_time_hours": 2.0,    # সাধারণ বার্থ / General purpose
        "capacity":         1,
        "compatible_types": ["Unknown"],
    },
}


CONGESTION_THRESHOLDS = {
    "LOW":    {"max": 40,  "color": "#2ecc71", "emoji": "🟢"},
    "MEDIUM": {"max": 70,  "color": "#f39c12", "emoji": "🟡"},
    "HIGH":   {"max": 100, "color": "#e74c3c", "emoji": "🔴"},
}




@dataclass
class Berth:
    berth_id:     str                        # বার্থের ID / Berth ID e.g. B01
    berth_type:   str                        # ধরন / Type e.g. cargo, ferry
    name:         str                        # নাম / Display name
    is_occupied:  bool              = False  # এখন ব্যবহৃত হচ্ছে কিনা / Currently in use?
    current_ship: Optional[str]     = None   # কোন জাহাজ আছে / Which ship is docked
    available_at: Optional[datetime]= None   # কখন খালি হবে / When will it be free

    def is_available(self, at_time: datetime = None) -> bool:
        
        t = at_time or datetime.utcnow()

        # বার্থ খালি অথবা সেই সময়ের আগেই খালি হয়ে যাবে
        # Free now, or will be free before the requested time
        if not self.is_occupied:
            return True
        if self.available_at and t >= self.available_at:
            return True
        return False




class PortSimulator:
    

    def __init__(self):
        self.berths: List[Berth] = []
        self.simulation_time     = datetime.utcnow()

        self._initialize_berths()     # সব বার্থ তৈরি / Create all berths
        self._pre_populate_berths()   # কিছু বার্থ আগে থেকে ব্যবহৃত করা / Pre-fill some berths

        logger.info(f"🏗️  Port Simulator ready. Total berths: {len(self.berths)}")

    # ── বার্থ তৈরি / Build Berths ──
    def _initialize_berths(self):
        n = 1
        for btype, cfg in BERTH_TYPES.items():
            for i in range(cfg["capacity"]):
                self.berths.append(Berth(
                    berth_id   = f"B{n:02d}",          # B01, B02, ...
                    berth_type = btype,
                    name       = f"{cfg['name']} {i+1}",
                ))
                n += 1

    
    def _pre_populate_berths(self):
        now = datetime.utcnow()
        pre_ships = [
            "Maersk Svendborg", "Nordic Carrier",
            "Baltic Trader",    "Sea Princess",
            "Copenhagen Mermaid"
        ]
        # প্রথম ৫টি বার্থ দখল / Occupy first 5 berths
        for i, berth in enumerate(self.berths[:5]):
            berth.is_occupied  = True
            berth.current_ship = pre_ships[i]
            # ১–৬ ঘণ্টার মধ্যে খালি হবে / Will free up within 1–6 hours
            berth.available_at = now + timedelta(hours=np.random.uniform(1, 6))

    

    def get_berth_for_ship(self, ship_type: str, at_time: datetime = None) -> Optional[Berth]:
        
        t = at_time or datetime.utcnow()

        # ১. নির্দিষ্ট বার্থে খোঁজা / Look in dedicated berths first
        for berth in self.berths:
            cfg        = BERTH_TYPES.get(berth.berth_type, {})
            compatible = cfg.get("compatible_types", [])
            if ship_type in compatible and berth.is_available(t):
                return berth

        # ২. সাধারণ বার্থে খোঁজা / Fall back to general berth
        for berth in self.berths:
            if berth.berth_type == "general" and berth.is_available(t):
                return berth

        return None   # কোনো বার্থ নেই / No berth available

    def get_docking_time(self, ship_type: str) -> float:
        
        for cfg in BERTH_TYPES.values():
            if ship_type in cfg["compatible_types"]:
                return cfg["docking_time_hours"]
        return BERTH_TYPES["general"]["docking_time_hours"]

    
    def calculate_waiting_time(self, ship_type: str, eta_str: str) -> dict:
        
        # ETA পার্স করা / Parse ETA string
        try:
            eta_dt = datetime.strptime(eta_str.replace(" UTC", ""), "%Y-%m-%d %H:%M")
        except Exception:
            eta_dt = datetime.utcnow() + timedelta(hours=6)

        docking_hrs = self.get_docking_time(ship_type)

        # ETA সময়ে বার্থ খালি আছে কিনা / Is any berth free at ETA?
        free_berth = self.get_berth_for_ship(ship_type, at_time=eta_dt)

        if free_berth:
            # ✅ সরাসরি ডক করতে পারবে / Ship can dock immediately
            departure = eta_dt + timedelta(hours=docking_hrs)
            return {
                "waiting_hours":  0.0,
                "berth_available": True,
                "assigned_berth": free_berth.berth_id,
                "docking_hours":  docking_hrs,
                "departure_time": departure.strftime("%Y-%m-%d %H:%M UTC"),
            }
        else:
            
            earliest = None
            for berth in self.berths:
                cfg = BERTH_TYPES.get(berth.berth_type, {})
                if ship_type in cfg.get("compatible_types", []) or berth.berth_type == "general":
                    if berth.available_at:
                        if earliest is None or berth.available_at < earliest:
                            earliest = berth.available_at

            if earliest:
                wait_hrs = max(0, (earliest - eta_dt).total_seconds() / 3600)
            else:
                wait_hrs = np.random.uniform(2, 8)   # অনুমান / Estimated wait

            actual_dock = eta_dt + timedelta(hours=wait_hrs)
            departure   = actual_dock + timedelta(hours=docking_hrs)

            return {
                "waiting_hours":   round(wait_hrs, 2),
                "berth_available": False,
                "assigned_berth":  "QUEUE",
                "docking_hours":   docking_hrs,
                "actual_dock_time": actual_dock.strftime("%Y-%m-%d %H:%M UTC"),
                "departure_time":  departure.strftime("%Y-%m-%d %H:%M UTC"),
            }

   

    def calculate_congestion(self) -> dict:
       
        now      = datetime.utcnow()
        occupied = sum(1 for b in self.berths if b.is_occupied and not b.is_available(now))
        total    = len(self.berths)
        rate     = (occupied / total * 100) if total > 0 else 0

        # LOW / MEDIUM / HIGH নির্ধারণ / Determine level
        if rate < CONGESTION_THRESHOLDS["LOW"]["max"]:
            level = "LOW"
        elif rate < CONGESTION_THRESHOLDS["MEDIUM"]["max"]:
            level = "MEDIUM"
        else:
            level = "HIGH"

        t = CONGESTION_THRESHOLDS[level]

        
        berth_stats = {}
        for btype in BERTH_TYPES:
            grp      = [b for b in self.berths if b.berth_type == btype]
            occ      = sum(1 for b in grp if b.is_occupied and not b.is_available(now))
            berth_stats[btype] = {
                "total":     len(grp),
                "occupied":  occ,
                "available": len(grp) - occ,
            }

        return {
            "level":            level,
            "occupancy_rate":   round(rate, 1),
            "occupied_berths":  occupied,
            "total_berths":     total,
            "available_berths": total - occupied,
            "color":            t["color"],
            "emoji":            t["emoji"],
            "berth_stats":      berth_stats,
            "timestamp":        now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

   

    def simulate_all_ships(self, predictions_df: pd.DataFrame) -> pd.DataFrame:
        
        if predictions_df.empty:
            return pd.DataFrame()

        rows = []
        for _, ship in predictions_df.iterrows():
            stype = ship.get("ship_type", "Cargo")
            eta   = ship.get("eta_datetime", "")

            w = self.calculate_waiting_time(stype, eta)

            rows.append({
                "mmsi":             ship.get("mmsi", ""),
                "ship_name":        ship.get("ship_name", "Unknown"),
                "ship_type":        stype,
                "eta_hours":        ship.get("final_eta_hours", 0),
                "eta_datetime":     eta,
                "waiting_hours":    w["waiting_hours"],
                "berth_available":  w["berth_available"],
                "assigned_berth":   w["assigned_berth"],
                "docking_hours":    w["docking_hours"],
                "total_port_time":  round(w["waiting_hours"] + w["docking_hours"], 2),
                "departure_time":   w.get("departure_time", "N/A"),
            })

        sim_df = pd.DataFrame(rows)
        cong   = self.calculate_congestion()
        logger.info(
            f"✅ Simulation done. "
            f"Congestion: {cong['level']} ({cong['occupancy_rate']}%) | "
            f"Waiting ships: {len(sim_df[sim_df['waiting_hours'] > 0])}"
        )
        return sim_df

    

    def get_forecast_timeline(self, hours_ahead=24) -> list:
        
        now      = datetime.utcnow()
        timeline = []

        for h in range(0, hours_ahead + 1, 2):   # প্রতি ২ ঘণ্টায় / Every 2 hours
            t   = now + timedelta(hours=h)
            occ = sum(
                1 for b in self.berths
                if b.is_occupied and b.available_at and b.available_at > t
            )
            total = len(self.berths)
            rate  = (occ / total * 100) if total > 0 else 0

            if rate < 40:   level = "LOW"
            elif rate < 70: level = "MEDIUM"
            else:           level = "HIGH"

            timeline.append({
                "time":             t.strftime("%H:%M"),
                "datetime":         t.strftime("%Y-%m-%d %H:%M UTC"),
                "hours_from_now":   h,
                "occupancy_rate":   round(rate, 1),
                "congestion_level": level,
                "occupied_berths":  occ,
                "available_berths": total - occ,
                "color":            CONGESTION_THRESHOLDS[level]["color"],
            })

        return timeline


# ── Quick test ──
if __name__ == "__main__":
    from ship_tracker import ShipTracker
    from eta_predictor import ETAPredictor

    tracker      = ShipTracker(use_simulation=True)
    ships_df     = tracker.fetch_ships()

    predictor    = ETAPredictor(use_ml=True)
    predictions  = predictor.predict_all(ships_df)

    simulator    = PortSimulator()
    sim_df       = simulator.simulate_all_ships(predictions)

    cong = simulator.calculate_congestion()
    print(f"\n{cong['emoji']}  Congestion : {cong['level']}  ({cong['occupancy_rate']}%)")
    print(f"   Berths    : {cong['occupied_berths']}/{cong['total_berths']} occupied\n")

    cols = ["ship_name","ship_type","eta_hours","waiting_hours","assigned_berth","total_port_time"]
    print(sim_df[cols].to_string(index=False))