import requests          
import pandas as pd      
import math            
from datetime import datetime, timedelta
import random
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ── বন্দরের তথ্য / Port Configuration ──
PORT_CONFIG = {
    "name": "Port of Copenhagen",
    "lat": 55.6867,    # কোপেনহেগেনের অক্ষাংশ / Latitude
    "lon": 12.5990,    # কোপেনহেগেনের দ্রাঘিমাংশ / Longitude
    "country": "Denmark",
}

API_CONFIG = {
    "vesselapi_url": "https://api.vtexplorer.com/vessels",
    "api_key": "YOUR_API_KEY_HERE",   # আপনার API কী দিন / Put your API key here
    "radius_nm": 200,
}


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    দুটি GPS পয়েন্টের মধ্যে দূরত্ব নটিক্যাল মাইলে বের করে।
    Calculate distance between two GPS points in nautical miles.
    """
    R = 3440.065  # পৃথিবীর ব্যাসার্ধ NM তে / Earth radius in nautical miles

    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlat   = math.radians(lat2 - lat1)
    dlon   = math.radians(lon2 - lon1)

    # Haversine সূত্র / Haversine formula
    a = math.sin(dlat/2)**2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(R * c, 2)



def generate_simulated_ships(num_ships=12):
    ship_types = {
        "Cargo":        (8, 14),
        "Tanker":       (7, 12),
        "Ferry":        (15, 22),
        "Container":    (12, 18),
        "Bulk Carrier": (8, 13),
        "Cruise":       (14, 20),
    }

    names = [
        "Maersk Elba", "Nordic Star", "Baltic Queen", "Copenhagen Express",
        "Viking Trader", "Norden Spirit", "Scandic Pioneer", "Sea Dragon",
        "Arctic Wind", "Jutland Glory", "Baltic Carrier", "Nordic Eagle",
    ]

    origins = ["Rotterdam", "Hamburg", "Oslo", "Stockholm", "Helsinki",
               "Gothenburg", "Antwerp", "Bremerhaven", "Gdansk", "Riga"]

    ships = []
    now = datetime.utcnow()

    for i in range(min(num_ships, len(names))):
        stype = random.choice(list(ship_types.keys()))
        speed = round(random.uniform(*ship_types[stype]), 1)

        
        angle    = random.uniform(0, 360)
        dist_nm  = random.uniform(20, 200)
        dist_deg = dist_nm / 60

        lat = PORT_CONFIG["lat"] + dist_deg * math.cos(math.radians(angle))
        lon = PORT_CONFIG["lon"] + dist_deg * math.sin(math.radians(angle))

        actual_dist = haversine_distance(lat, lon, PORT_CONFIG["lat"], PORT_CONFIG["lon"])
        eta_hours   = actual_dist / speed if speed > 0 else 999
        eta_time    = now + timedelta(hours=eta_hours)

        ships.append({
            "mmsi":         f"2{random.randint(1000000, 9999999)}",
            "ship_name":    names[i],
            "ship_type":    stype,
            "latitude":     round(lat, 4),
            "longitude":    round(lon, 4),
            "speed_knots":  speed,
            "heading":      random.randint(0, 359),
            "destination":  "COPENHAGEN",
            "origin":       random.choice(origins),
            "distance_nm":  actual_dist,
            "eta_hours":    round(eta_hours, 2),
            "eta_datetime": eta_time.strftime("%Y-%m-%d %H:%M UTC"),
            "timestamp":    now.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "status":       "Underway",
            "flag":         random.choice(["DK","NO","SE","FI","DE","NL"]),
            "data_source":  "SIMULATED",
        })

    logger.info(f"✅ Simulated {len(ships)} ships near Copenhagen")
    return ships



def fetch_from_vtexplorer(api_key):
    
    params = {
        "userkey": api_key,
        "lat":     PORT_CONFIG["lat"],
        "lon":     PORT_CONFIG["lon"],
        "radius":  API_CONFIG["radius_nm"],
        "format":  "json",
    }
    try:
        logger.info("🌐 Fetching from VT Explorer API...")
        r = requests.get(API_CONFIG["vesselapi_url"], params=params, timeout=10)
        r.raise_for_status()

        ships = []
        for v in r.json():
            lat   = float(v.get("LAT", 0))
            lon   = float(v.get("LON", 0))
            speed = float(v.get("SPEED", 0)) / 10   # VT Explorer uses 0.1 knot units

            dist      = haversine_distance(lat, lon, PORT_CONFIG["lat"], PORT_CONFIG["lon"])
            eta_hours = dist / speed if speed > 0.5 else 999
            eta_time  = datetime.utcnow() + timedelta(hours=eta_hours)

            ships.append({
                "mmsi":         v.get("MMSI", "Unknown"),
                "ship_name":    v.get("NAME", "Unknown Vessel"),
                "ship_type":    v.get("TYPE", "Unknown"),
                "latitude":     lat,
                "longitude":    lon,
                "speed_knots":  round(speed, 1),
                "heading":      int(v.get("COURSE", 0)),
                "destination":  v.get("DEST", "COPENHAGEN"),
                "origin":       "Unknown",
                "distance_nm":  dist,
                "eta_hours":    round(eta_hours, 2),
                "eta_datetime": eta_time.strftime("%Y-%m-%d %H:%M UTC"),
                "timestamp":    datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "status":       v.get("STATUS", "Underway"),
                "flag":         v.get("FLAG", "XX"),
                "data_source":  "VT_EXPLORER_API",
            })

        logger.info(f"✅ Got {len(ships)} ships from API")
        return ships

    except Exception as e:
        logger.warning(f"⚠️  API failed ({e}) — will use simulated data")
        return []



class ShipTracker:
    

    def __init__(self, api_key=None, use_simulation=False):
        self.api_key        = api_key
        self.use_simulation = use_simulation
        self.ships_df       = pd.DataFrame()
        self.last_updated   = None
        logger.info(f"🚢 ShipTracker ready for {PORT_CONFIG['name']}")

    def fetch_ships(self):
        
        ships_data = []

       
        if self.api_key and self.api_key != "YOUR_API_KEY_HERE" and not self.use_simulation:
            ships_data = fetch_from_vtexplorer(self.api_key)

        
        if not ships_data:
            ships_data = generate_simulated_ships()

       
        self.ships_df = pd.DataFrame(ships_data)

        if not self.ships_df.empty:
            
            for col in ["latitude","longitude","speed_knots","distance_nm","eta_hours"]:
                self.ships_df[col] = pd.to_numeric(self.ships_df[col], errors="coerce")

           
            self.ships_df = self.ships_df.sort_values("distance_nm").reset_index(drop=True)

        self.last_updated = datetime.utcnow()
        logger.info(f"📊 Tracking {len(self.ships_df)} ships total")
        return self.ships_df

    def get_ships_geojson(self):
        
        if self.ships_df.empty:
            return {"type": "FeatureCollection", "features": []}

        features = []
        for _, s in self.ships_df.iterrows():
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [s["longitude"], s["latitude"]]},
                "properties": {
                    "mmsi": s["mmsi"], "name": s["ship_name"], "type": s["ship_type"],
                    "speed": s["speed_knots"], "heading": s["heading"],
                    "distance_nm": s["distance_nm"], "eta_hours": s["eta_hours"],
                    "eta_datetime": s["eta_datetime"], "origin": s["origin"],
                    "destination": s["destination"], "flag": s["flag"],
                }
            })
        return {"type": "FeatureCollection", "features": features}

    def get_summary_stats(self):
        
        if self.ships_df.empty:
            return {}
        return {
            "total_ships":      len(self.ships_df),
            "avg_speed_knots":  round(self.ships_df["speed_knots"].mean(), 1),
            "avg_distance_nm":  round(self.ships_df["distance_nm"].mean(), 1),
            "closest_ship":     self.ships_df.iloc[0]["ship_name"],
            "closest_distance": self.ships_df.iloc[0]["distance_nm"],
            "ships_within_50nm": len(self.ships_df[self.ships_df["distance_nm"] <= 50]),
            "ship_types":       self.ships_df["ship_type"].value_counts().to_dict(),
            "last_updated":     self.last_updated.strftime("%Y-%m-%d %H:%M UTC"),
        }


# ── Quick test ──
if __name__ == "__main__":
    tracker  = ShipTracker(use_simulation=True)
    ships_df = tracker.fetch_ships()
    print(ships_df[["ship_name","ship_type","distance_nm","speed_knots","eta_hours"]].to_string())
    print("\nStats:", tracker.get_summary_stats())