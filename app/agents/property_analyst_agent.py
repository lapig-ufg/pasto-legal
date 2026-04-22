from agno.run import RunContext
from agno.agent import Agent
from agno.skills import Skills, LocalSkills, SkillValidationError
from agno.tools.calculator import CalculatorTools

from app.tools.property_analyst_tools import (
    generate_property_image,
    generate_biomass_image,
    get_pasture_stats,
    get_soil_texture_stats
    )
from app.utils.interfaces.property_record import RuralProperty
from app.configs.models import model


try:
    skills = Skills(loaders=[LocalSkills("app/skills/property_analyst_agent")])
except SkillValidationError as e:
    print(f"Skill validation failed: {e}")
    print(f"Errors: {e.errors}")
    skills = None


def get_instructions(run_context: RunContext):
    session_state = run_context.session_state

    registered_properties = [RuralProperty.model_validate(prop) for prop in session_state.get("registered_properties", [])]
    if registered_properties:
        registrations_text = '\n'.join([str(prop) for prop in registered_properties])
    else:
        registrations_text = "Vazio"

    instructions = f"""
        <registrations>
        {registrations_text}
        <registrations>                    
                
        <instructions>
        - Sempre informe o ano de referência das análise. Use 2024 como ano de referência para os dados mais atualizados.
        - Seja o mais conciso possível, explicando os resultados de forma simples para o pequeno produtore rural.
        - Use seu conhecimento com base em cartilhas e conhecimentos da Embrapa para esclarecer dúvidas dos usuários.
        - Use markdown no formato do WhatsApp. Não use bullet points.
        <instructions>
                                                                  
        <workflow>                    
        - Se o usuário fizer perguntas não relacionadas a **Agropecuária**, responda ESTRITAMENTE com:
            > "Atualmente só posso lhe ajudar com questões relativas a eficiência de pastagens. Se precisar de ajuda com esses temas, estou à disposição! Para outras questões, recomendo consultar fontes oficiais ou especialistas na área."
        - Se o usuário fizer perguntas fora da ESCALA TERRITORIAL: **Propriedade Rural**, responda ESTRITAMENTE com:
            > "Minha análise é focada especificamente no nível da propriedade rural. Para visualizar dados em escala territorial (como estatísticas por Bioma, Estado ou Município), recomendo consultar a plataforma oficial do MapBiomas: https://plataforma.brasil.mapbiomas.org/"
        - Se não possuir possuir ferramentas para gerar os dados solicitados responda com:
            > "Opa, que ideia legal! Infelizmente, no momento, não tenho as ferramentas necessárias para gerar esse tipo de análise. Mas, para eu conseguir levar essa ideia pro nosso time de desenvolvimento, poderia me dizer um pouco mais sobre o que você gostaria de ver nesse tipo de análise? Assim, posso passar essa sugestão para eles e quem sabe a gente consiga implementar no futuro!"                           
        <workflow>
    """
    
    return instructions


property_analyst_agent = Agent(
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
        get_soil_texture_stats,
        generate_property_image,
        generate_biomass_image
    ],
    skills=skills,
    use_instruction_tags=False,
    instructions=get_instructions,
    model=model
)