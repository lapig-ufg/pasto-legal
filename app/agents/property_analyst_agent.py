import textwrap
from agno.run import RunContext
from agno.agent import Agent
from agno.models.google import Gemini
from agno.skills import Skills, LocalSkills, SkillValidationError
from agno.tools.calculator import CalculatorTools

from app.tools.property_analyst_tools import (
    generate_property_image,
    generate_biomass_image,
    get_pasture_stats
    )
from app.utils.interfaces.property_record import PropertyRecord


try:
    skills = Skills(loaders=[LocalSkills("app/skills/property_analyst_agent")])
except SkillValidationError as e:
    print(f"Skill validation failed: {e}")
    print(f"Errors: {e.errors}")
    skills = None


def get_instructions(run_context: RunContext):
    session_state = run_context.session_state or {}
    
    # Captura a persona definida na sessão
    user_persona = session_state.get("user_persona", "Desconhecido")

    registered_properties = [PropertyRecord.model_validate(record) for record in session_state.get("registered_properties", [])]
    if registered_properties:
        registrations_text = '\n'.join([str(record) for record in registered_properties])
    else:
        registrations_text = "Vazio"

    # Lógica Dinâmica da Persona para o Especialista
    persona_instructions = ""
    if user_persona == "Produtor":
        persona_instructions = textwrap.dedent("""
            - PERFIL DE RESPOSTA (PRODUTOR): Seja o mais conciso possível, explicando os resultados de forma SIMPLES e ACESSÍVEL para o produtor rural.
            - TRADUÇÃO DE MÉTRICAS: Converta métricas abstratas para a realidade prática (exemplo: prefira falar sobre "capacidade de suporte/lotação animal" no lugar de "índice de biomassa bruta").
            - FOCO: Direcione os resultados geoprocessados para a viabilidade econômica e instruções diretas de manejo na propriedade.
        """).strip()
    elif user_persona == "Técnico":
        persona_instructions = textwrap.dedent("""
            - PERFIL DE RESPOSTA (TÉCNICO): Opere no limite da profundidade analítica de um agrônomo/geoprocessador sênior.
            - DADOS BRUTOS: Entregue os dados espaciais brutos (ex: índices exatos de NDVI, biomassa, vigor e hectares precisos).
            - JARGÕES: Use terminologia técnica e metodologias agronômicas livremente (como a "metodologia Lapig para cálculo de Unidade Animal").
            - FOCO: O texto deve servir como um relatório técnico para suporte à decisão estratégica do consultor.
        """).strip()
    else:
         persona_instructions = "- PERFIL DE RESPOSTA (GERAL): Seja conciso e use conhecimentos da Embrapa para explicar os resultados de forma simples."

    instructions = textwrap.dedent(f"""\
        <registrations>
        {registrations_text}
        <registrations>                    
                
        <instructions>
        {persona_instructions}
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
    role=(
        "Especialista em agropecuária e geoprocessamento. Resposável por análises de dados, "
        "inteligência geográfica e suporte técnico de propriedades.\n"
        "Suas responsabilidades são:\n"
        "   - Esclarecer dúvidas técnicas e agronômicas gerais.\n"
        "   - Executar análises técnicas com o Google Earth Engine.\n"
        "   - Gerar análises espaciais, relatórios e mapas temáticos.\n"
    ),
    description=(
        "Agente especialista em agropecuária e geoprocessamento. Resposável por análises de dados, "
        "inteligência geográfica e suporte técnico de propriedades.\n"
        "Suas responsabilidades são:\n"
        "   - Esclarecer dúvidas técnicas e agronômicas gerais.\n"
        "   - Executar análises técnicas com o Google Earth Engine.\n"
        "   - Gerar análises espaciais, relatórios e mapas temáticos.\n"
    ),
    debug_mode=True,
    tools=[
        CalculatorTools(exclude_tools=["is_prime", "factorial"]),
        get_pasture_stats,
        generate_property_image,
        generate_biomass_image
    ],
    skills=skills,
    use_instruction_tags=False,
    instructions=get_instructions,
    model=Gemini(id="gemini-3-flash-preview")
)