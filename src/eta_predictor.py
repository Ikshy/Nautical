import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import RandomForestRegressor   # ML মডেল / ML model
from sklearn.preprocessing import LabelEncoder       # ক্যাটাগরি → নম্বর / Category to number
from sklearn.model_selection import train_test_split # ডেটা ভাগ / Split data
from sklearn.metrics import mean_absolute_error      # মডেল যাচাই / Model evaluation
import logging
import warnings
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)



WEATHER_FACTORS = {
    "Calm":         {"multiplier": 1.00, "desc": "শান্ত সমুদ্র / Calm sea"},
    "Light Breeze": {"multiplier": 1.05, "desc": "হালকা বাতাস / Light breeze"},
    "Moderate":     {"multiplier": 1.15, "desc": "মাঝারি / Moderate"},
    "Rough":        {"multiplier": 1.30, "desc": "রুক্ষ সমুদ্র / Rough sea"},
    "Storm":        {"multiplier": 1.60, "desc": "ঝড় / Storm"},
}


FUEL_RATES = {
    "Cargo":        2.5,
    "Tanker":       3.0,
    "Ferry":        1.8,
    "Container":    4.0,
    "Bulk Carrier": 2.8,
    "Cruise":       5.5,
    "Unknown":      2.5,
}




def calculate_simple_eta(distance_nm, speed_knots, weather="Calm"):
    
    
    w_mult = WEATHER_FACTORS.get(weather, WEATHER_FACTORS["Calm"])["multiplier"]

   
    if speed_knots < 0.5:
        return {
            "eta_hours":    999.0,
            "eta_datetime": "N/A — Ship anchored",
            "method":       "simple_formula",
        }

    base_eta     = distance_nm / speed_knots          # মূল ETA / Base ETA hours
    adjusted_eta = base_eta * w_mult                  # আবহাওয়া সহ ETA / Weather adjusted
    eta_dt       = datetime.utcnow() + timedelta(hours=adjusted_eta)

    return {
        "eta_hours":            round(adjusted_eta, 2),
        "eta_hours_base":       round(base_eta, 2),
        "eta_datetime":         eta_dt.strftime("%Y-%m-%d %H:%M UTC"),
        "weather_condition":    weather,
        "weather_multiplier":   w_mult,
        "weather_delay_hours":  round(adjusted_eta - base_eta, 2),
        "method":               "simple_formula",
    }




class MLETAPredictor:
    

    def __init__(self):
        
        self.model = RandomForestRegressor(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            n_jobs=-1          # সব CPU কোর ব্যবহার / Use all CPU cores
        )
        self.label_encoder = LabelEncoder()  # জাহাজের ধরন এনকোড / Encode ship types
        self.is_trained    = False
        self.mae           = None            # Mean Absolute Error

    def _generate_training_data(self, n=2000):
       
        np.random.seed(42)
        types = ["Cargo","Tanker","Ferry","Container","Bulk Carrier","Cruise"]

        df = pd.DataFrame({
            "distance_nm":   np.random.uniform(20, 500, n),
            "speed_knots":   np.random.uniform(5, 25, n),
            "weather_factor": np.random.choice(
                [f["multiplier"] for f in WEATHER_FACTORS.values()], n
            ),
            "ship_type":     np.random.choice(types, n),
            "port_busyness": np.random.uniform(0, 1, n),   # বন্দরের ব্যস্ততা / Port busyness
            "hour_of_day":   np.random.randint(0, 24, n),  # দিনের সময় / Time of day
        })

        
        base       = df["distance_nm"] / df["speed_knots"]
        w_delay    = base * (df["weather_factor"] - 1)
        port_delay = df["port_busyness"] * np.random.uniform(0, 3, n)
        noise      = np.random.normal(0, 0.5, n)

        df["eta_hours"] = (base + w_delay + port_delay + noise).clip(lower=0.5)
        return df

    def train(self):
        
        logger.info(" Training ML model...")
        df = self._generate_training_data()

        
        df["ship_type_enc"] = self.label_encoder.fit_transform(df["ship_type"])

        self.features = ["distance_nm","speed_knots","weather_factor",
                         "ship_type_enc","port_busyness","hour_of_day"]

        X = df[self.features]
        y = df["eta_hours"]

        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        self.model.fit(X_train, y_train)          
        self.is_trained = True

        self.mae = mean_absolute_error(y_test, self.model.predict(X_test))
        logger.info(f" ML model trained. MAE = {self.mae:.2f} hours")

    def predict(self, distance_nm, speed_knots, ship_type="Cargo",
                weather="Calm", port_busyness=0.5):
        """
        ML মডেল দিয়ে একটি জাহাজের ETA পূর্বাভাস।
        Predict ETA for one ship using the trained ML model.
        """
        if not self.is_trained:
            self.train()

        w_factor = WEATHER_FACTORS.get(weather, WEATHER_FACTORS["Calm"])["multiplier"]

        try:
            type_enc = self.label_encoder.transform([ship_type])[0]
        except ValueError:
            type_enc = 0   

        X = np.array([[
            distance_nm,
            speed_knots,
            w_factor,
            type_enc,
            port_busyness,
            datetime.utcnow().hour,   
        ]])

        ml_eta  = float(max(0.1, self.model.predict(X)[0]))
        eta_dt  = datetime.utcnow() + timedelta(hours=ml_eta)
        simple  = calculate_simple_eta(distance_nm, speed_knots, weather)

        return {
            "ml_eta_hours":     round(ml_eta, 2),
            "simple_eta_hours": simple["eta_hours"],
            "eta_datetime":     eta_dt.strftime("%Y-%m-%d %H:%M UTC"),
            "confidence":       "HIGH" if self.mae and self.mae < 1.5 else "MEDIUM",
            "method":           "random_forest_ml",
        }




class ETAPredictor:
    

    def __init__(self, use_ml=True, weather="Calm"):
        self.use_ml       = use_ml
        self.weather      = weather
        self.ml           = MLETAPredictor() if use_ml else None
        self.predictions_df = pd.DataFrame()
        logger.info(f" ETAPredictor ready. ML={use_ml}, Weather={weather}")

    def predict_all(self, ships_df, port_busyness=0.5):
        
        if ships_df.empty:
            return pd.DataFrame()

        
        if self.use_ml and self.ml and not self.ml.is_trained:
            self.ml.train()

        rows = []
        for _, ship in ships_df.iterrows():
            dist      = float(ship.get("distance_nm", 0))
            speed     = float(ship.get("speed_knots", 0))
            stype     = ship.get("ship_type", "Cargo")

            
            simple = calculate_simple_eta(dist, speed, self.weather)

            
            if self.use_ml and self.ml:
                ml_res    = self.ml.predict(dist, speed, stype, self.weather, port_busyness)
                final_eta = ml_res["ml_eta_hours"]
                method    = "ML + Simple"
            else:
                final_eta = simple["eta_hours"]
                method    = "Simple Formula"

            
            if final_eta < 2:
                urgency = "🔴 IMMINENT"
            elif final_eta < 6:
                urgency = "🟡 SOON"
            elif final_eta < 24:
                urgency = "🟢 TODAY"
            else:
                urgency = "⚪ SCHEDULED"

            
            fuel_rate = FUEL_RATES.get(stype, 2.5)

            rows.append({
                "mmsi":               ship.get("mmsi", ""),
                "ship_name":          ship.get("ship_name", "Unknown"),
                "ship_type":          stype,
                "distance_nm":        round(dist, 1),
                "speed_knots":        round(speed, 1),
                "simple_eta_hours":   simple["eta_hours"],
                "ml_eta_hours":       ml_res["ml_eta_hours"] if self.use_ml else None,
                "final_eta_hours":    round(final_eta, 2),
                "eta_datetime":       (datetime.utcnow() + timedelta(hours=final_eta))
                                      .strftime("%Y-%m-%d %H:%M UTC"),
                "urgency":            urgency,
                "weather":            self.weather,
                "weather_factor":     simple["weather_multiplier"],
                "fuel_rate_ton_hr":   fuel_rate,
                "estimated_fuel_tons": round(fuel_rate * final_eta, 1),
                "prediction_method":  method,
            })

        self.predictions_df = pd.DataFrame(rows)
        logger.info(f" ETA predicted for {len(rows)} ships")
        return self.predictions_df

    def get_predictions_json(self):
       
        if self.predictions_df.empty:
            return []
        return self.predictions_df.fillna("N/A").to_dict(orient="records")


# ── Quick test ──
if __name__ == "__main__":
    from ship_tracker import ShipTracker

    tracker  = ShipTracker(use_simulation=True)
    ships_df = tracker.fetch_ships()

    predictor    = ETAPredictor(use_ml=True, weather="Moderate")
    predictions  = predictor.predict_all(ships_df)

    cols = ["ship_name","ship_type","distance_nm","speed_knots","final_eta_hours","urgency"]
    print(predictions[cols].to_string(index=False))