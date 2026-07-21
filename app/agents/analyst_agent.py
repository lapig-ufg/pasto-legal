import textwrap
from agno.run import RunContext
from agno.agent import Agent
from agno.skills import Skills, LocalSkills, SkillValidationError
from agno.tools.calculator import CalculatorTools
from agno.utils.log import log_debug

from app.tools.property_analyst_tools import (
    generate_property_image,
    generate_biomass_image,
    generate_soil_texture_image,
    get_pasture_stats,
    get_topographic_stats
    )
from app.tools.tts_tools import generate_speech
from app.utils.interfaces.property_record import RuralProperty
from app.utils.interfaces.user_persona import UserPersona
from app.configs.config import config


try:
    skills = Skills(loaders=[LocalSkills("app/skills/property_analyst_agent")])
except SkillValidationError as e:
    skills = None


def get_instructions(run_context: RunContext):
    session_state = run_context.session_state or {}
    
    user_persona = session_state.get("user_persona", None)
    if user_persona is None:
        user_persona_text = "Perfil geral: Produtor rural ou parceiro do Pasto Legal. Adote um tom acolhedor e respeitoso do campo."
    else:
        try:
            if isinstance(user_persona, dict):
                user_persona = UserPersona.model_validate(user_persona)
            user_persona_text = str(user_persona)
        except Exception:
            user_persona_text = str(user_persona)

    all_properties = [RuralProperty.model_validate(record) for record in session_state.get("all_properties", [])]
    if all_properties:
        registrations_text = '\n'.join([str(record) for record in all_properties])
    else:
        registrations_text = "Vazio"

    instructions = textwrap.dedent(f"""\
        <user-persona>
        {user_persona_text}
        </user-persona>

        <registrations>
        {registrations_text}
        <registrations>                    
                
        <instructions>
        - Sempre informe o ano de referência das análise.
        - Seja o mais conciso possível, explicando os resultados de forma simples.
        - Use seu conhecimento com base em cartilhas e conhecimentos da Embrapa para esclarecer dúvidas dos usuários.
        - Gere imagens apenas quando explicitamente pedido pelo usuário.
        - Gere apenas um tipo de imagem por vez. Nunca gere mais de um tipo de imagem por vez.
        - Use markdown no formato do WhatsApp. Não use bullet points.
        <instructions>
                                                                  
        <workflow>                    
        - Se o usuário fizer perguntas não relacionadas a **Agropecuária**, responda ESTRITAMENTE com:
            > "Atualmente só posso lhe ajudar com questões relativas a eficiência de pastagens..."
        - Se o usuário fizer perguntas fora da ESCALA TERRITORIAL: **Propriedade Rural**, responda ESTRITAMENTE com:
            > "Minha análise é focada especificamente no nível da propriedade rural..."
        - Se não possuir ferramentas para gerar os dados solicitados responda com:
            > "Opa, que ideia legal! Infelizmente, no momento, não tenho as ferramentas necessárias..."                           
        <workflow>
    """).strip()
    
    return instructions


analyst_agent = Agent(
    name="Agente Extensionista Agrônomo",
    debug_mode=config.DEBUG_MODE,
    tools=[
        CalculatorTools(
            exclude_tools=["is_prime", "factorial"]
        ),
        get_pasture_stats,
        get_topographic_stats,
        generate_property_image,
        generate_biomass_image,
        generate_soil_texture_image,
        generate_speech
    ],
    skills=skills,
    use_instruction_tags=False,
    instructions=get_instructions,
    model=config.model
)