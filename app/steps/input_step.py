"""Input pre-processing step: converts media (audio/image) to text and
geospatial documents (shapefile/zip/rar, KMZ, KML, GeoJSON) to GeoJSON.

Executes the transcription agent for audio and the description agent for
images, consolidating everything into a single text for the following
steps (PII guardrail and business agents).

Geospatial documents are converted to a single GeoJSON ``FeatureCollection``
and attached to the step output as a ``.json`` file (``format="geojson"``), so
the single agent can decide to start the registration flow. The raw file is
never sent to the model.

On transcription/description/conversion failure, logs the error and continues
with whatever text is available (resilient fallback).

External interface:
    _input_processing_executor  -- StepExecutor consumed by main_workflow.
"""
from pathlib import Path
from typing import List

from agno.media import File
from agno.utils.log import log_debug, log_error
from agno.workflow import Step
from agno.workflow.types import StepInput, StepOutput

from app.services.geospatial.geojson_io import (
    SUPPORTED_EXTENSIONS,
    GeoFileError,
    UnsupportedFormatError,
    convert_geo_file_to_geojson,
    resolve_geo_filename,
    save_debug_json,
)


def _file_name(file: File) -> str:
    """Resolves the filename of an agno ``File`` (name, filename or filepath)."""
    name = file.name or file.filename
    if name:
        return str(name)
    if file.filepath:
        return Path(str(file.filepath)).name
    return ""


def _convert_geo_files(files: List[File]) -> tuple[List[File], List[str]]:
    """Converts supported geospatial files to GeoJSON ``File`` objects.

    Returns:
        Tuple (converted files, error notices).
    """
    converted: List[File] = []
    errors: List[str] = []

    for file in files:
        filename = _file_name(file)
        content = file.get_content_bytes()
        if not content:
            continue

        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            # WhatsApp may omit the filename; sniff the file type from its
            # magic bytes. Files that are not geospatial are left untouched.
            resolved = resolve_geo_filename(filename, content)
            if Path(resolved).suffix.lower() in SUPPORTED_EXTENSIONS:
                filename = resolved
            else:
                continue

        try:
            geojson_bytes = convert_geo_file_to_geojson(content, filename)
        except UnsupportedFormatError:
            continue
        except GeoFileError as error:
            log_error(f"geojson conversion failed for {filename}: {error}")
            errors.append(str(error))
            continue
        except Exception as error:  # pragma: no cover - defensive
            log_error(f"unexpected geojson conversion failure for {filename}: {error}")
            errors.append(
                "Ocorreu um erro inesperado ao processar o arquivo enviado. "
                "Tente novamente com outro arquivo."
            )
            continue

        stem = Path(filename).stem or "property"
        debug_path = save_debug_json(geojson_bytes, f"input_step_converted_{stem}")
        if debug_path:
            log_debug(f"converted geojson saved for debugging: {debug_path}")

        converted.append(
            File(
                content=geojson_bytes,
                mime_type="application/json",
                name=f"{stem}.json",
                format="geojson",
            )
        )

    return converted, errors


def _input_processing_executor(step_input: StepInput) -> StepOutput:
    """Converte mídia (áudio/imagem) em texto e arquivos geoespaciais em GeoJSON."""
    parts: list[str] = []

    texto = step_input.get_input_as_string() or ""
    if texto:
        parts.append(texto)

    if step_input.images or step_input.audio:
        from app.agents import audio_transcription_agent, image_description_agent

        if step_input.images:
            try:
                response = image_description_agent.run("", images=step_input.images)
                description = response.content or ""
                if description:
                    parts.append(f"[IMAGEM]{description}[/IMAGEM]")
            except Exception as e:
                log_error(f"image description failed: {e}")

        if step_input.audio:
            try:
                response = audio_transcription_agent.run("", audio=step_input.audio)
                transcription = response.content or ""
                if transcription:
                    parts.append(transcription)
            except Exception as e:
                log_error(f"audio transcription failed: {e}")

    converted_files: List[File] = []
    if step_input.files:
        converted_files, errors = _convert_geo_files(step_input.files)
        for error in errors:
            parts.append(
                f"[ARQUIVO GEOESPACIAL]Não foi possível processar o arquivo enviado: "
                f"{error}[/ARQUIVO GEOESPACIAL]"
            )

    return StepOutput(content="\n".join(parts), files=converted_files or None)


input_step = Step(
    name="Input Step",
    executor=_input_processing_executor,
)
