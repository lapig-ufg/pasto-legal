import os
import base64
import textwrap

from os import getenv
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agno.agent.agent import Agent
from agno.media import Audio, File, Image, Video
from agno.team.team import Team
from agno.tools.whatsapp import WhatsAppTools
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.whatsapp import get_media_async, send_image_message_async, typing_indicator_async, upload_media_async

from app.interfaces.whatsapp.security import validate_webhook_signature


# TODO: O contato de desenvolvimento só deve responder números conhecidos.
# TODO: No primeiro contato o sistema deve enviar o termo de consentimento. Interface: vídeo, voz e texto.
def attach_routes(router: APIRouter, agent: Optional[Agent] = None, team: Optional[Team] = None) -> APIRouter:
    if agent is None and team is None:
        raise ValueError("Either agent or team must be provided.")

    whatsapp_tools = WhatsAppTools(async_mode=True)

    @router.get("/status")
    async def status():
        return {"status": "available"}

    @router.get("/webhook")
    async def verify_webhook(request: Request):
        """Handle WhatsApp webhook verification"""
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")

        verify_token = getenv("WHATSAPP_VERIFY_TOKEN")
        if not verify_token:
            raise HTTPException(status_code=500, detail="WHATSAPP_VERIFY_TOKEN is not set")

        if mode == "subscribe" and token == verify_token:
            if not challenge:
                raise HTTPException(status_code=400, detail="No challenge received")
            return PlainTextResponse(content=challenge)

        raise HTTPException(status_code=403, detail="Invalid verify token or mode")

    @router.post("/webhook")
    async def webhook(request: Request, background_tasks: BackgroundTasks):
        """Handle incoming WhatsApp messages"""
        try:
            # Get raw payload for signature validation
            payload = await request.body()
            signature = request.headers.get("X-Hub-Signature-256")

            # Validate webhook signature
            if not validate_webhook_signature(payload, signature):
                log_warning("Invalid webhook signature")
                raise HTTPException(status_code=403, detail="Invalid signature")

            body = await request.json()

            log_info(body)

            # Validate webhook data
            if body.get("object") != "whatsapp_business_account":
                log_warning(f"Received non-WhatsApp webhook object: {body.get('object')}")
                return {"status": "ignored"}

            # Process messages in background
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    messages = change.get("value", {}).get("messages", [])

                    if not messages:
                        continue

                    message = messages[0]
                    background_tasks.add_task(process_message, message, agent, team)

            return {"status": "processing"}

        except Exception as e:
            log_error(f"Error processing webhook: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def process_message(message: dict, agent: Optional[Agent], team: Optional[Team]):
        """Process a single WhatsApp message in the background"""
        log_info(message)

        try:
            message_text = ""
            message_image = None
            message_video = None
            message_audio = None
            message_doc = None
            
            message_id = message.get("id")
            await typing_indicator_async(message_id)

            match message.get("type"):
                case "text":
                    message_text = message["text"]["body"]
                case "image":
                    try:
                        message_text = message["image"]["caption"]
                    except Exception:
                        message_text = "Describe the image"
                    finally:
                        message_image = message["image"]["id"]
                case "video":
                    try:
                        message_text = message["video"]["caption"]
                    except Exception:
                        message_text = "Describe the video"
                    finally:
                        message_video = message["video"]["id"]
                case "audio":
                    message_text = "Reply to audio"
                    message_audio = message["audio"]["id"]
                case "document":
                    message_text = "Process the document"
                    message_doc = message["document"]["id"]
                case "location":
                    # TODO: Alterar prompt para um mais adequado com armazenamento.
                    message_text = f"""Peça ao agente Coletor que guarde as seguintes coordenadas Lat: {message['location']['latitude']} Long: {message['location']['longitude']}. Em seguida, peça ao agente Analista que gere uma visualização da minha propriedade rural."""
                case _:
                    return

            phone_number = message["from"]
            log_info(f"Processing message from {phone_number}: {message_text}")

            if team:
                response = await team.arun(
                    message_text,
                    user_id=phone_number,
                    session_id=f"wa:{phone_number}",
                    files=[File(content=await get_media_async(message_doc))] if message_doc else None,
                    images=[Image(content=await get_media_async(message_image))] if message_image else None,
                    videos=[Video(content=await get_media_async(message_video))] if message_video else None,
                    audio=[Audio(content=await get_media_async(message_audio))] if message_audio else None,
                )

            if response.reasoning_content:
                await _send_whatsapp_message(phone_number, f"Reasoning: \n{response.reasoning_content}", italics=True)

            if response.images:
                number_of_images = len(response.images)
                log_info(f"images generated: f{number_of_images}")

                for i in range(number_of_images):
                    image_bytes = None
                    image_content = response.images[i].content
                    
                    if isinstance(image_content, bytes):
                        try:
                            decoded_string = image_content.decode("utf-8")

                            image_bytes = base64.b64decode(decoded_string)
                        except UnicodeDecodeError:
                            image_bytes = image_content
                    elif isinstance(image_content, str):
                        image_bytes = base64.b64decode(image_content)
                    else:
                        log_error(f"Unexpected image content type: {type(image_content)} for user {phone_number}")

                    if image_bytes:
                        media_id = await upload_media_async(media_data=image_bytes, mime_type="image/png", filename="image.png")
                        await send_image_message_async(media_id=media_id, recipient=phone_number, text=response.content)
                    else:
                        log_warning(f"Could not process image content for user {phone_number}. Type: {type(image_content)}")
                        await _send_whatsapp_message(phone_number, response.content)  # type: ignore
            else:
                await _send_whatsapp_message(phone_number, response.content)  # type: ignore

        except Exception as e:
            log_error(f"Error processing message: {str(e)}")

            try:
                await _send_whatsapp_message(phone_number, "Desculpe, ocorreu um erro ao processar sua mensagem. Por favor, tente novamente mais tarde.")
            except Exception as send_error:
                log_error(f"Error sending error message: {str(send_error)}")

    async def _send_whatsapp_message(recipient: str, message: str, italics: bool = False):
        message_batches = textwrap.wrap(message, width=4000, replace_whitespace=False, drop_whitespace=False)

        for i, batch in enumerate(message_batches, 1):
            if len(message_batches) > 1:
                batch_message = f"[{i}/{len(message_batches)}] {batch}"
            else:
                batch_message = f"{batch}"

            if italics:
                # TODO: É possível que, caso o texto possua "\n\n", a menssagem gere um "__" literal.
                formatted_batch = "\n".join([f"_{line}_" for line in batch_message.split("\n")])
                await whatsapp_tools.send_text_message_async(recipient=recipient, text=formatted_batch)
            else:
                await whatsapp_tools.send_text_message_async(recipient=recipient, text=batch_message)

    return router