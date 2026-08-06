"""
CLI wrapper for Google Earth Engine geospatial tools.
Called by pi's bash tool via the bridge extension.

Usage:
  python cli/gee.py '<base64-json-args>'
"""
import sys
import json
import os
import base64
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _get_property_coords(car_codes: list) -> list:
    """Look up property coordinates from session state (Valkey)."""
    import redis
    valkey = redis.Redis(
        host=os.getenv("VALKEY_HOST", "localhost"),
        port=int(os.getenv("VALKEY_PORT", "6379")),
        db=int(os.getenv("VALKEY_DB", "0")),
        decode_responses=True,
    )
    # We need user_id to look up state, but GEE tools don't receive it.
    # Instead, we search all sessions for matching car_codes.
    # ponytail: O(n) scan, fine for now; add user_id param if slow.
    car_str = ", ".join(car_codes)
    for key in valkey.scan_iter("session:*"):
        raw = valkey.get(key)
        if not raw:
            continue
        state = json.loads(raw)
        for prop in state.get("all_properties", []):
            if prop.get("car_code") == car_str:
                from app.schemas.rural_property import RuralProperty
                return RuralProperty.model_validate(prop).get_coords()
    raise ValueError(f"Property not found for CAR: {car_str}")


def pasture_stats(args: dict) -> dict:
    from app.services.geospatial.gee import query_pasture_statistics
    coords = _get_property_coords(args["car_codes"])
    stats = query_pasture_statistics(coords, args.get("year", 2026), args.get("month", 5))
    return {"stats_text": str(stats), "stats": stats.model_dump()}


def topographic_stats(args: dict) -> dict:
    from app.services.geospatial.gee import query_topographic_stats
    coords = _get_property_coords(args["car_codes"])
    stats = query_topographic_stats(coords)
    return {"stats_text": str(stats), "stats": stats.model_dump()}


def property_image(args: dict) -> dict:
    from app.services.geospatial.gee import retrieve_feature_images
    import base64 as b64
    coords = _get_property_coords(args["car_codes"])
    imgs = retrieve_feature_images(coords)
    buf = BytesIO()
    imgs[0].save(buf, format="PNG")
    return {"message": "O contorno vermelho indica a delimitação da propriedade.", "images": [b64.b64encode(buf.getvalue()).decode()]}


def biomass_image(args: dict) -> dict:
    from app.services.geospatial.gee import retrieve_t2g_biomass_image, retrieve_mapbiomas_biomass_image
    import datetime, base64 as b64
    coords = _get_property_coords(args["car_codes"])
    today = datetime.date.today()
    img = retrieve_t2g_biomass_image(coords, today.month, today.year)
    if img is None:
        img = retrieve_mapbiomas_biomass_image(coords, year=2024)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return {"message": "Legenda: Azul claro (Alta) a Roxo escuro (Baixa concentração de biomassa).", "images": [b64.b64encode(buf.getvalue()).decode()]}


def soil_texture_image(args: dict) -> dict:
    from app.services.geospatial.gee import retrieve_feature_soil_texture_image
    import base64 as b64
    coords = _get_property_coords(args["car_codes"])
    img = retrieve_feature_soil_texture_image(coords)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return {"message": "Legenda: Afloramento, Muito Argiloso, Argila, Siltoso, Arenoso, Médio.", "images": [b64.b64encode(buf.getvalue()).decode()]}


def pasture_classification_image(args: dict) -> dict:
    from app.services.geospatial.pasture_classification import classify_pasture_on_the_fly
    from app.schemas.rural_property import RuralProperty
    import ee, base64 as b64, redis, json as _json

    car_codes = args["car_codes"]
    coords = _get_property_coords(car_codes)
    roi = ee.Geometry.MultiPolygon(coords)
    car_code = ", ".join(car_codes)
    result = classify_pasture_on_the_fly(roi=roi, car_code=car_code)
    buf = BytesIO()
    result["imagem"].save(buf, format="PNG")
    return {
        "message": f"Área de pastagem classificada (ano {result['pred_year']}): {result['area_pasto_ha']} hectares. Verde = Pastagem.",
        "images": [b64.b64encode(buf.getvalue()).decode()],
    }


ACTIONS = {
    "pasture_stats": pasture_stats,
    "topographic_stats": topographic_stats,
    "property_image": property_image,
    "biomass_image": biomass_image,
    "soil_texture_image": soil_texture_image,
    "pasture_classification_image": pasture_classification_image,
}

if __name__ == "__main__":
    args = json.loads(base64.b64decode(sys.argv[1]))
    action = args.pop("action")
    fn = ACTIONS.get(action)
    if not fn:
        print(json.dumps({"error": f"Unknown action: {action}"}))
        sys.exit(1)
    try:
        result = fn(args)
        print(json.dumps(result, default=str))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
