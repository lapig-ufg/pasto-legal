"""
CLI wrapper for property registration tools.
Called by pi's bash tool via the pi subprocess extension.

Usage:
  python cli/property.py '<base64-json-args>'

Each action reads/writes session state from Valkey/Redis.
"""
import sys
import json
import os
import base64
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import redis

VALKEY_HOST = os.getenv("VALKEY_HOST", "localhost")
VALKEY_PORT = int(os.getenv("VALKEY_PORT", "6379"))
VALKEY_DB = int(os.getenv("VALKEY_DB", "0"))

valkey = redis.Redis(host=VALKEY_HOST, port=VALKEY_PORT, db=VALKEY_DB, decode_responses=True)


def _get_state(user_id: str) -> dict:
    raw = valkey.get(f"session:{user_id}")
    return json.loads(raw) if raw else {}

def _set_state(user_id: str, state: dict) -> None:
    valkey.set(f"session:{user_id}", json.dumps(state, default=str))


def register_by_car(args: dict) -> dict:
    from app.services.geospatial.sicar import fetch_property_by_car, clean_car_code
    from app.services.geospatial.gee import retrieve_feature_images
    from app.services.geospatial.image import create_vertical_mosaic
    from app.schemas.rural_property import RuralProperty
    from io import BytesIO
    import base64 as b64

    car_codes = args["car_codes"]
    user_id = args["user_id"]
    state = _get_state(user_id)

    clean_codes = [clean_car_code(c) for c in car_codes]
    if None in clean_codes:
        return {"message": "Formato de CAR inválido. O padrão exige: 2 letras do Estado, 7 números, 32 caracteres.", "images": []}

    properties = fetch_property_by_car(car_codes=car_codes)
    if not properties:
        return {"message": "Nenhuma propriedade encontrada com esse código CAR. Verifique e tente novamente.", "images": []}

    prop = RuralProperty.unify(properties)
    state["candidate_properties"] = [prop.model_dump()]
    state["registration_state"] = "pending"
    _set_state(user_id, state)

    imgs = retrieve_feature_images(prop.get_coords())
    mosaic = create_vertical_mosaic(imgs)
    buf = BytesIO()
    mosaic.save(buf, format="PNG")
    img_b64 = b64.b64encode(buf.getvalue()).decode()

    desc = prop.describe()
    if len(properties) == 1:
        msg = f"Encontrei 1 propriedade:\n> {desc}\n\nEsta é a propriedade correta?"
    else:
        msg = f"Encontrei {len(properties)} propriedades que foram unificadas:\n> {desc}\n\nConfirma?"

    return {"message": msg, "images": [img_b64], "session_state": state}


def register_by_coords(args: dict) -> dict:
    from app.services.geospatial.sicar import fetch_property_by_coordinates
    from app.services.geospatial.gee import retrieve_feature_images
    from app.services.geospatial.image import create_vertical_mosaic
    from app.schemas.rural_property import RuralProperty
    from io import BytesIO
    import base64 as b64

    lat, lon = args["latitude"], args["longitude"]
    user_id = args["user_id"]
    state = _get_state(user_id)

    properties = fetch_property_by_coordinates(latitude=lat, longitude=lon)
    if not properties:
        return {"message": "Nenhuma propriedade encontrada nessas coordenadas. Verifique e tente novamente.", "images": []}

    # Check already registered
    registered_map = {p.get("car_code"): p for p in state.get("all_properties", [])}
    for prop in properties:
        if prop.car_code in registered_map:
            return {"message": f"Esta propriedade já está cadastrada: {prop.describe()}", "images": []}

    state["candidate_properties"] = [p.model_dump() for p in properties]
    state["registration_state"] = "pending"
    _set_state(user_id, state)

    imgs = retrieve_feature_images([p.get_coords()[0] for p in properties])

    if len(properties) == 1:
        buf = BytesIO()
        imgs[0].save(buf, format="PNG")
        img_b64 = b64.b64encode(buf.getvalue()).decode()
        return {"message": f"Encontrei 1 propriedade:\n> {properties[0].describe()}\n\nÉ esta?", "images": [img_b64], "session_state": state}
    else:
        mosaic = create_vertical_mosaic(imgs)
        buf = BytesIO()
        mosaic.save(buf, format="PNG")
        img_b64 = b64.b64encode(buf.getvalue()).decode()
        opts = "\n".join(f"  Opção {i+1} - {p.describe()}" for i, p in enumerate(properties))
        return {"message": f"Encontrei {len(properties)} propriedades:\n{opts}\n\nQual é a correta? Responda com o número.", "images": [img_b64], "session_state": state}


def register_by_url(args: dict) -> dict:
    from app.services.geospatial.sicar import fetch_coordinates_by_url, fetch_property_by_coordinates
    from app.services.geospatial.gee import retrieve_feature_images
    from app.services.geospatial.image import create_vertical_mosaic
    from io import BytesIO
    import base64 as b64

    url = args["url"]
    user_id = args["user_id"]
    state = _get_state(user_id)

    try:
        lat, lon = fetch_coordinates_by_url(url=url)
    except Exception as e:
        return {"message": f"Não foi possível extrair coordenadas deste link. Envie um link de compartilhamento do Google Maps.", "images": []}

    if lat is None or lon is None:
        return {"message": "Não foi possível extrair coordenadas deste link.", "images": []}

    # Reuse coordinate flow
    return register_by_coords({"latitude": lat, "longitude": lon, "user_id": user_id})


def confirm_selection(args: dict) -> dict:
    user_id = args["user_id"]
    state = _get_state(user_id)
    candidates = state.get("candidate_properties", [])
    if not candidates:
        return {"message": "Nenhuma propriedade pendente de confirmação.", "session_state": state}

    state["registration_state"] = "final"
    state["candidate_properties"] = [candidates[0]]
    _set_state(user_id, state)
    return {"message": "Propriedade confirmada! Qual nome você quer dar para ela?", "session_state": state}


def select_from_list(args: dict) -> dict:
    user_id = args["user_id"]
    selection = args["selection"]
    state = _get_state(user_id)
    candidates = state.get("candidate_properties", [])
    if not candidates:
        return {"message": "Nenhuma busca realizada ainda.", "session_state": state}
    if selection < 1 or selection > len(candidates):
        return {"message": f"Seleção inválida. Escolha um número entre 1 e {len(candidates)}.", "session_state": state}

    state["candidate_properties"] = [candidates[selection - 1]]
    state["registration_state"] = "final"
    _set_state(user_id, state)
    return {"message": f"Propriedade {selection} selecionada! Qual nome você quer dar para ela?", "session_state": state}


def complete_registration(args: dict) -> dict:
    from app.schemas.rural_property import RuralProperty

    user_id = args["user_id"]
    name = args["name"]
    state = _get_state(user_id)
    candidates = state.get("candidate_properties", [])
    if not candidates:
        return {"message": "Nenhuma propriedade para concluir cadastro.", "session_state": state}

    prop = candidates[0]
    prop["nickname"] = name
    all_props = state.get("all_properties", [])
    all_props.append(prop)
    state["all_properties"] = all_props
    state["candidate_properties"] = None
    state["registration_state"] = None
    _set_state(user_id, state)

    return {
        "message": f"Propriedade *{name}* (CAR: {prop['car_code']}) cadastrada com sucesso! 🎉\nAgora você já pode pedir análises da sua propriedade.",
        "session_state": state,
    }


def cancel_registration(args: dict) -> dict:
    user_id = args["user_id"]
    state = _get_state(user_id)
    state["candidate_properties"] = None
    state["registration_state"] = None
    _set_state(user_id, state)
    return {"message": "Cadastro cancelado. Como posso ajudar?", "session_state": state}


def remove_property(args: dict) -> dict:
    user_id = args["user_id"]
    car_code = args["car_code"]
    state = _get_state(user_id)
    all_props = state.get("all_properties", [])
    new_props = [p for p in all_props if p.get("car_code") != car_code]
    if len(new_props) == len(all_props):
        return {"message": "Propriedade não encontrada.", "session_state": state}
    state["all_properties"] = new_props
    _set_state(user_id, state)
    return {"message": "Propriedade removida com sucesso.", "session_state": state}


def remove_all(args: dict) -> dict:
    user_id = args["user_id"]
    state = _get_state(user_id)
    state["all_properties"] = []
    _set_state(user_id, state)
    return {"message": "Todas as propriedades foram removidas.", "session_state": state}


def set_name(args: dict) -> dict:
    user_id = args["user_id"]
    car_codes = args["car_codes"]
    name = args["name"]
    state = _get_state(user_id)
    all_props = state.get("all_properties", [])
    car_str = ", ".join(car_codes)
    for p in all_props:
        if p.get("car_code") == car_str:
            p["nickname"] = name
            _set_state(user_id, state)
            return {"message": f"Nome da propriedade alterado para *{name}*.", "session_state": state}
    return {"message": "Propriedade não encontrada.", "session_state": state}


ACTIONS = {
    "register_by_car": register_by_car,
    "register_by_coords": register_by_coords,
    "register_by_url": register_by_url,
    "confirm_selection": confirm_selection,
    "select_from_list": select_from_list,
    "complete_registration": complete_registration,
    "cancel_registration": cancel_registration,
    "remove": remove_property,
    "remove_all": remove_all,
    "set_name": set_name,
}

if __name__ == "__main__":
    args = json.loads(base64.b64decode(sys.argv[1]))
    action = args.pop("action")
    fn = ACTIONS.get(action)
    if not fn:
        print(json.dumps({"error": f"Unknown action: {action}"}))
        sys.exit(1)
    result = fn(args)
    print(json.dumps(result, default=str))
