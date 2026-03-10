import sys
import os
import logging
from datetime import datetime
from threading import Thread
import time


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, jsonify, request

from ship_tracker   import ShipTracker,   PORT_CONFIG
from eta_predictor  import ETAPredictor,  WEATHER_FACTORS
from port_simulator import PortSimulator
from optimizer      import ArrivalOptimizer

# ── লগিং সেটআপ / Logging setup ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# ── Flask অ্যাপ / Flask app ──
app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static"
)




tracker   = ShipTracker(use_simulation=True)
predictor = ETAPredictor(use_ml=True, weather="Calm")
simulator = PortSimulator()
optimizer = ArrivalOptimizer()



cache = {
    "ships_geojson":   {"type": "FeatureCollection", "features": []},
    "eta_predictions": [],
    "port_simulation": [],
    "optimization":    [],
    "congestion":      {},
    "forecast":        [],
    "fleet_summary":   {},
    "tracker_stats":   {},
    "last_updated":    None,
    "update_count":    0,
}




def refresh_all_data(weather="Calm"):

    global cache

    try:
        logger.info(f"🔄 Refreshing data... (weather={weather})")

        # ── ১. জাহাজ ট্র্যাকিং / Ship Tracking ──
        ships_df              = tracker.fetch_ships()
        cache["ships_geojson"] = tracker.get_ships_geojson()
        cache["tracker_stats"] = tracker.get_summary_stats()

        # ── ২. ETA পূর্বাভাস / ETA Prediction ──
        predictor.weather      = weather
        busyness               = cache["congestion"].get("occupancy_rate", 50) / 100
        predictions_df         = predictor.predict_all(ships_df, port_busyness=busyness)
        cache["eta_predictions"] = predictor.get_predictions_json()

        # ── ৩. পোর্ট সিমুলেশন / Port Simulation ──
        simulation_df          = simulator.simulate_all_ships(predictions_df)
        cache["congestion"]    = simulator.calculate_congestion()
        cache["forecast"]      = simulator.get_forecast_timeline(hours_ahead=24)

        if not simulation_df.empty:
            cache["port_simulation"] = (
                simulation_df.fillna("N/A").to_dict(orient="records")
            )

        # ── ৪. অপ্টিমাইজেশন / Optimization ──
        if not simulation_df.empty and not predictions_df.empty:
            rec_df = optimizer.generate_recommendations(simulation_df, predictions_df)
            if not rec_df.empty:
                cache["optimization"]  = rec_df.fillna("N/A").to_dict(orient="records")
                cache["fleet_summary"] = optimizer.get_fleet_summary(rec_df)

        # ── সময় আপডেট / Timestamp ──
        cache["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        cache["update_count"] += 1
        logger.info(f"✅ Cache updated. #{cache['update_count']}")

    except Exception as e:
        logger.error(f"❌ Refresh error: {e}")




def background_updater():

    logger.info("⏱️  Background updater started")
    while True:
        try:
            refresh_all_data()
            time.sleep(60)        # ৬০ সেকেন্ড বিরতি / 60s interval
        except Exception as e:
            logger.error(f"❌ Background error: {e}")
            time.sleep(30)        # ত্রুটি হলে ৩০ সেকেন্ড / 30s on error




@app.route("/")
def index():

    return render_template(
        "index.html",
        port=PORT_CONFIG,
        weather_options=list(WEATHER_FACTORS.keys()),
        last_updated=cache["last_updated"],
    )


@app.route("/api/ships")
def api_ships():

    return jsonify(cache["ships_geojson"])


@app.route("/api/eta")
def api_eta():

    return jsonify({
        "predictions":  cache["eta_predictions"],
        "count":        len(cache["eta_predictions"]),
        "last_updated": cache["last_updated"],
    })


@app.route("/api/congestion")
def api_congestion():

    return jsonify({
        "current":      cache["congestion"],
        "forecast":     cache["forecast"],
        "last_updated": cache["last_updated"],
    })


@app.route("/api/optimization")
def api_optimization():
  
    return jsonify({
        "recommendations": cache["optimization"],
        "fleet_summary":   cache["fleet_summary"],
        "last_updated":    cache["last_updated"],
    })


@app.route("/api/stats")
def api_stats():
    """
    সিস্টেমের সামগ্রিক পরিসংখ্যান।
    Overall system statistics.
    """
    return jsonify({
        "tracker":      cache["tracker_stats"],
        "congestion":   cache["congestion"],
        "fleet_summary":cache["fleet_summary"],
        "last_updated": cache["last_updated"],
        "update_count": cache["update_count"],
    })


@app.route("/api/all")
def api_all():
    
    return jsonify({
        "ships":           cache["ships_geojson"],
        "eta_predictions": cache["eta_predictions"],
        "congestion":      cache["congestion"],
        "forecast":        cache["forecast"],
        "optimization":    cache["optimization"],
        "fleet_summary":   cache["fleet_summary"],
        "stats":           cache["tracker_stats"],
        "last_updated":    cache["last_updated"],
        "port":            PORT_CONFIG,
    })


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    
    # অনুরোধ থেকে আবহাওয়া নেওয়া / Get weather from request body
    body    = request.get_json(silent=True) or {}
    weather = body.get("weather", "Calm")

    refresh_all_data(weather=weather)

    return jsonify({
        "status":       "success",
        "message":      "Data refreshed successfully",
        "last_updated": cache["last_updated"],
    })



# প্রথম ডেটা লোড / Initial data load before serving requests
logger.info("🚀 Starting Nautical Dashboard...")
refresh_all_data()

# ব্যাকগ্রাউন্ড থ্রেড চালু / Start background refresh thread
bg_thread = Thread(target=background_updater, daemon=True)
bg_thread.start()

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  🌊 NAUTICAL Dashboard")
    print("  http://localhost:5000")
    print("=" * 50 + "\n")
    app.run(
        debug=False,
        host="0.0.0.0",
        port=5000,
        use_reloader=False    # ব্যাকগ্রাউন্ড থ্রেড দুবার না চালাতে
                              # Prevents double-starting background thread
    )