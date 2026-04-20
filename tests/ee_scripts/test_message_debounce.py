import pytest
import asyncio


_MOCK_MESSAGE_BUFFER = {}
_MOCK_USER_TASKS = {}

async def mock_process_buffer(user_id: str):
    """
    Espelho do motor de debounce implementado no router.py.
    (Tempos reduzidos para o teste não ficar lento)
    """
    has_media = any(msg.get("type") == "image" for msg in _MOCK_MESSAGE_BUFFER.get(user_id, []))
    
    
    sleep_time = 0.5 if has_media else 0.2 
    await asyncio.sleep(sleep_time)

    messages = _MOCK_MESSAGE_BUFFER.pop(user_id, [])
    _MOCK_USER_TASKS.pop(user_id, None)

    combined_text = []
    arquivos_falsos = []

    for msg in messages:
        if msg.get("type") == "text":
            combined_text.append(msg["text"]["body"])
        elif msg.get("type") == "image":
            arquivos_falsos.append(f"/tmp/mock_{msg['image']['id']}.jpg")
            if "caption" in msg.get("image", {}):
                combined_text.append(msg["image"]["caption"])

    return " ".join(combined_text), arquivos_falsos

@pytest.mark.asyncio
async def test_debounce_image_and_text_concatenation():
    """
    Valida o fluxo: Usuário manda Foto -> Espera -> Manda Texto -> Pacote é fechado junto.
    """
    user_id = "5511999999999"

    
    _MOCK_MESSAGE_BUFFER[user_id] = [{"type": "image", "image": {"id": "12345"}}]
    _MOCK_USER_TASKS[user_id] = True
    
    
    task = asyncio.create_task(mock_process_buffer(user_id))

    
    _MOCK_MESSAGE_BUFFER[user_id].append({"type": "text", "text": {"body": "Esse é o pasto do lote 4."}})

    
    await asyncio.sleep(0.1)
    _MOCK_MESSAGE_BUFFER[user_id].append({"type": "text", "text": {"body": "Acha que preciso adubar?"}})

   
    resultado_texto, arquivos = await task

    
    assert len(arquivos) == 1
    assert arquivos[0] == "/tmp/mock_12345.jpg"
    assert resultado_texto == "Esse é o pasto do lote 4. Acha que preciso adubar?"
    assert user_id not in _MOCK_MESSAGE_BUFFER  

@pytest.mark.asyncio
async def test_debounce_fast_text_messages():
    """
    Valida o fluxo: Usuário manda múltiplos textos rápidos ("Oi", "Tudo bem?", "Tenho uma dúvida").
    """
    user_id = "5511888888888"

    _MOCK_MESSAGE_BUFFER[user_id] = [{"type": "text", "text": {"body": "Oi"}}]
    _MOCK_USER_TASKS[user_id] = True
    task = asyncio.create_task(mock_process_buffer(user_id))

    await asyncio.sleep(0.1)
    _MOCK_MESSAGE_BUFFER[user_id].append({"type": "text", "text": {"body": "Tudo bem?"}})

    resultado_texto, arquivos = await task

    assert len(arquivos) == 0
    assert resultado_texto == "Oi Tudo bem?"