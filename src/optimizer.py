import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)



FUEL_CONFIG = {
    
    "burn_rates": {
        "Cargo":        1.2,
        "Tanker":       1.8,
        "Ferry":        0.8,
        "Container":    2.0,
        "Bulk Carrier": 1.4,
        "Cruise":       3.2,
        "Unknown":      1.5,
    },

    
    "price_usd_per_ton": 650,

    
    "co2_per_ton_fuel": 3.17,
}


OPT_CONFIG = {
    "min_speed_knots":       5,    # সর্বনিম্ন নিরাপদ গতি / Min safe speed
    "max_speed_knots":       25,   # সর্বোচ্চ গতি / Max speed
    "wait_threshold_hours":  0.5,  # এর কম অপেক্ষায় অপ্টিমাইজ করা হবে না
                                   # Don't optimize if wait is less than this
}




class ArrivalOptimizer:
    

    def __init__(self):
        logger.info(" ArrivalOptimizer ready")

    

    def calculate_fuel_saved(self, ship_type: str, waiting_hours: float) -> dict:
        
        rate = FUEL_CONFIG["burn_rates"].get(
            ship_type,
            FUEL_CONFIG["burn_rates"]["Unknown"]
        )

        # অপেক্ষার সময়ে মোট জ্বালানি নষ্ট / Total fuel wasted during wait
        fuel_wasted  = rate * waiting_hours

        # আর্থিক ক্ষতি / Financial loss from wasted fuel
        cost_wasted  = fuel_wasted * FUEL_CONFIG["price_usd_per_ton"]

        # CO2 নির্গমন / CO2 emitted during wait
        co2_emitted  = fuel_wasted * FUEL_CONFIG["co2_per_ton_fuel"]

        # ৮০% অপ্টিমাইজেশন দক্ষতা ধরা হচ্ছে
        # Assuming 80% optimization efficiency
        eff          = 0.80
        fuel_saved   = fuel_wasted * eff
        cost_saved   = cost_wasted * eff
        co2_saved    = co2_emitted * eff

        return {
            "burn_rate_ton_hr":   rate,
            "fuel_wasted_tons":   round(fuel_wasted,  2),
            "fuel_saved_tons":    round(fuel_saved,   2),
            "cost_wasted_usd":    round(cost_wasted,  0),
            "cost_saved_usd":     round(cost_saved,   0),
            "co2_emitted_tons":   round(co2_emitted,  2),
            "co2_saved_tons":     round(co2_saved,    2),
        }

    

    def recommend_speed(self, distance_nm: float, current_speed: float,
                        waiting_hours: float, ship_type: str) -> dict:
        """
        জাহাজকে একটু ধীরে যেতে বলা যাতে বার্থ খালি হওয়ার সময় পৌঁছায়।
        Tell the ship to slow down so it arrives just as a berth becomes free.

        কৌশল / Strategy:
          নতুন গতি = দূরত্ব ÷ (পুরনো সময় + অপেক্ষার সময়)
          new_speed = distance ÷ (old_travel_time + waiting_time)
        """
        # অপেক্ষা সহনীয় হলে কিছু করার দরকার নেই
        # Wait is acceptable — no action needed
        if waiting_hours <= OPT_CONFIG["wait_threshold_hours"]:
            return {
                "action":              "MAINTAIN_SPEED",
                "recommended_speed":   current_speed,
                "speed_change_knots":  0.0,
                "speed_change_pct":    0.0,
                "new_eta_hours":       distance_nm / current_speed if current_speed > 0 else 0,
                "time_saved_hours":    0.0,
                "fuel_saved_tons":     0.0,
                "cost_saved_usd":      0.0,
                "co2_saved_tons":      0.0,
                "reason":              " অপেক্ষা সহনীয় / Wait is acceptable",
            }

        # বর্তমান ভ্রমণ সময় / Current travel time in hours
        current_travel = distance_nm / current_speed if current_speed > 0 else 0

        # নতুন লক্ষ্য সময় = পুরনো সময় + অপেক্ষার সময়
        # New target time = old time + wait (arrive when berth is free)
        target_travel  = current_travel + waiting_hours

        # প্রয়োজনীয় নতুন গতি / Required new speed
        optimal_speed  = distance_nm / target_travel if target_travel > 0 else current_speed

        # গতির সীমা মেনে চলা / Clamp within safe limits
        optimal_speed  = max(
            OPT_CONFIG["min_speed_knots"],
            min(OPT_CONFIG["max_speed_knots"], optimal_speed)
        )

        speed_change   = optimal_speed - current_speed
        action         = "SLOW_DOWN" if speed_change < 0 else "SPEED_UP"

        # জ্বালানি সাশ্রয় / Fuel savings from eliminating the wait
        fuel_info      = self.calculate_fuel_saved(ship_type, waiting_hours)

        return {
            "action":              action,
            "recommended_speed":   round(optimal_speed, 1),
            "current_speed":       current_speed,
            "speed_change_knots":  round(speed_change, 1),
            "speed_change_pct":    round(speed_change / current_speed * 100
                                         if current_speed > 0 else 0, 1),
            "new_eta_hours":       round(target_travel, 2),
            "time_saved_hours":    round(waiting_hours, 2),
            "fuel_saved_tons":     fuel_info["fuel_saved_tons"],
            "cost_saved_usd":      fuel_info["cost_saved_usd"],
            "co2_saved_tons":      fuel_info["co2_saved_tons"],
            "reason":              (
                f"🐌 গতি কমিয়ে বার্থ খালি হওয়ার সময় পৌঁছান / "
                f"Slow down to arrive when berth is free"
            ),
        }

    

    def generate_recommendations(self,
                                  simulation_df: pd.DataFrame,
                                  predictions_df: pd.DataFrame) -> pd.DataFrame:
        """
        সব জাহাজের জন্য অপ্টিমাইজেশন সুপারিশ তৈরি করে।
        Generate optimization recommendations for every ship.
        """
        if simulation_df.empty or predictions_df.empty:
            logger.warning("  No data for optimization")
            return pd.DataFrame()

        # দুটি DataFrame একসাথে মেশানো / Merge simulation + prediction data
        merged = simulation_df.merge(
            predictions_df[["mmsi", "distance_nm", "speed_knots", "estimated_fuel_tons"]],
            on="mmsi",
            how="left"
        )

        rows = []
        for _, ship in merged.iterrows():
            stype        = ship.get("ship_type",    "Cargo")
            wait_hrs     = float(ship.get("waiting_hours", 0))
            dist         = float(ship.get("distance_nm",   0))
            speed        = float(ship.get("speed_knots",   10))
            eta_hrs      = float(ship.get("eta_hours",     0))
            eta_str      = ship.get("eta_datetime", "")

            # গতি সুপারিশ / Speed recommendation
            rec          = self.recommend_speed(dist, speed, wait_hrs, stype)

            # জ্বালানি তথ্য / Fuel info
            fuel         = self.calculate_fuel_saved(stype, wait_hrs)

            # অপ্টিমাইজড আগমনের সময় / Optimized arrival datetime
            opt_hrs      = eta_hrs + wait_hrs
            opt_dt       = datetime.utcnow() + timedelta(hours=opt_hrs)

            # অগ্রাধিকার / Priority based on potential savings
            if wait_hrs > 4:
                priority = "🔴 HIGH"
            elif wait_hrs > 1:
                priority = "🟡 MEDIUM"
            else:
                priority = "🟢 LOW"

            rows.append({
                # জাহাজের পরিচয় / Ship identity
                "mmsi":                    ship.get("mmsi", ""),
                "ship_name":               ship.get("ship_name", "Unknown"),
                "ship_type":               stype,

                # বর্তমান অবস্থা / Current status
                "current_speed_knots":     speed,
                "current_eta_hours":       eta_hrs,
                "current_eta_datetime":    eta_str,
                "predicted_waiting_hours": wait_hrs,

                # সুপারিশ / Recommendation
                "action":                  rec["action"],
                "recommended_speed_knots": rec["recommended_speed"],
                "speed_change_knots":      rec["speed_change_knots"],
                "speed_change_pct":        rec["speed_change_pct"],
                "optimized_eta_hours":     round(opt_hrs, 2),
                "optimized_eta_datetime":  opt_dt.strftime("%Y-%m-%d %H:%M UTC"),
                "new_waiting_hours":       0.0,   # অপ্টিমাইজের পর অপেক্ষা নেই

                # সাশ্রয় / Savings
                "fuel_saved_tons":         fuel["fuel_saved_tons"],
                "cost_saved_usd":          fuel["cost_saved_usd"],
                "co2_saved_tons":          fuel["co2_saved_tons"],

                # অগ্রাধিকার ও সারসংক্ষেপ / Priority & summary
                "priority":                priority,
                "benefit_summary":         (
                    f"${fuel['cost_saved_usd']:,.0f} saved | "
                    f"{fuel['fuel_saved_tons']} t fuel | "
                    f"{fuel['co2_saved_tons']} t CO₂"
                ),
            })

        opt_df = pd.DataFrame(rows)
        logger.info(f" Generated {len(opt_df)} recommendations")
        return opt_df

    

    def get_fleet_summary(self, recommendations_df: pd.DataFrame) -> dict:
        """
        পুরো বহরের অপ্টিমাইজেশন ফলাফলের সারসংক্ষেপ।
        Summary of optimization results across the entire fleet.
        """
        if recommendations_df.empty:
            return {}

        df = recommendations_df

        # মোট সাশ্রয় / Total savings across all ships
        total_fuel   = df["fuel_saved_tons"].sum()
        total_cost   = df["cost_saved_usd"].sum()
        total_co2    = df["co2_saved_tons"].sum()
        total_wait   = df["predicted_waiting_hours"].sum()

        # কতটি জাহাজের উল্লেখযোগ্য অপেক্ষা আছে
        # How many ships have significant waiting time
        ships_waiting = len(df[df["predicted_waiting_hours"] > OPT_CONFIG["wait_threshold_hours"]])

        # সবচেয়ে বেশি সুবিধা পাবে এমন জাহাজ
        # Ship that benefits most from optimization
        if len(df) > 0:
            top_ship = df.nlargest(1, "cost_saved_usd")["ship_name"].values[0]
        else:
            top_ship = "N/A"

        return {
            "total_ships_optimized":  len(df),
            "ships_with_waiting":     ships_waiting,
            "total_waiting_hours":    round(total_wait,  1),
            "total_fuel_saved_tons":  round(total_fuel,  1),
            "total_cost_saved_usd":   round(total_cost,  0),
            "total_co2_saved_tons":   round(total_co2,   1),
            "high_priority_ships":    len(df[df["priority"] == "🔴 HIGH"]),
            "top_beneficiary_ship":   top_ship,
            "environmental_benefit":  f"{round(total_co2, 1)} tons CO₂ avoided",
            "financial_benefit":      f"${round(total_cost, 0):,.0f} USD saved",
        }


# ── Quick test ──
if __name__ == "__main__":
    from ship_tracker  import ShipTracker
    from eta_predictor import ETAPredictor
    from port_simulator import PortSimulator

    tracker     = ShipTracker(use_simulation=True)
    ships_df    = tracker.fetch_ships()

    predictor   = ETAPredictor(use_ml=True, weather="Moderate")
    pred_df     = predictor.predict_all(ships_df)

    simulator   = PortSimulator()
    sim_df      = simulator.simulate_all_ships(pred_df)

    optimizer   = ArrivalOptimizer()
    rec_df      = optimizer.generate_recommendations(sim_df, pred_df)

    print("\n⚡ Optimization Recommendations:")
    cols = ["ship_name","current_speed_knots","recommended_speed_knots",
            "predicted_waiting_hours","cost_saved_usd","priority"]
    print(rec_df[cols].to_string(index=False))

    print("\n Fleet Summary:")
    for k, v in optimizer.get_fleet_summary(rec_df).items():
        print(f"   {k}: {v}")