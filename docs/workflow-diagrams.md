# Diagramas da Arquitetura do Workflow

Coleção de diagramas (Mermaid) para visualizar a arquitetura do `pasto_legal_workflow`. Cada diagrama foca em uma perspectiva diferente.

> Os diagramas Mermaid podem ser renderizados no GitHub/GitLab diretamente, ou colados em https://mermaid.live.

---

## 1. Visão Geral — Orquestração de Alto Nível

O Workflow roda duas vertentes em paralelo (`grade_and_respond`) e então consolida tudo no `merge_response`.

```mermaid
flowchart TD
    Input([Mensagem do usuário]) --> Parallel

    subgraph Parallel["Parallel: grade_and_respond"]
        direction LR
        EB["evaluation_branch<br/><i>satisfaction.py</i>"]
        NR["normal_response<br/><i>normal_response.py</i>"]
    end

    EB --> Merge
    NR --> Merge

    Merge["merge_response<br/><i>feedback.py</i>"]
    Merge --> Output([Resposta final enviada ao usuário])

    style Parallel fill:#eef,stroke:#446
    style Merge fill:#efe,stroke:#464
```

---

## 2. Detalhe — `evaluation_branch` (gradação de satisfação)

Grada a satisfação (1–5), ramifica em 3 vias (Condition é binária, então a 3ª via é um Condition aninhado) e persiste feedback.

```mermaid
flowchart TD
    In([Mensagem]) --> Grade["grade_satisfaction<br/>grader_agent → 1..5"]
    Grade --> SS1[("session_state.satisfaction_grade = N")]
    SS1 --> B1{"branch_on_grade<br/>is_frustrated? N<3"}

    B1 -->|Sim| Fr["handle_frustration<br/>frustration_handler_agent"]
    Fr --> SFr["save_frustration<br/>→ FrustrationFeedback"]

    B1 -->|Não| B2{"amazed_or_neutral<br/>is_amazed? N>3"}
    B2 -->|Sim| Am["amazed_handler<br/>amazed_handler_agent"]
    Am --> SAm["save_amazed<br/>→ PositiveFeedback"]
    B2 -->|Não| Ne["neutral_handler<br/>neutral_handler_agent"]

    SFr --> End([handler_message em session_state])
    SAm --> End
    Ne --> End

    style Grade fill:#eef,stroke:#446
    style B1 fill:#ffe,stroke:#886
    style B2 fill:#ffe,stroke:#886
    style SFr fill:#fee,stroke:#844
    style SAm fill:#efe,stroke:#484
```

---

## 3. Detalhe — `normal_response` (roteamento por intenção/registro)

Roteia a mensagem: pergunta de sistema → Q&A; técnica com propriedade → Team; técnica sem propriedade → Loop de cadastro + análise preliminar.

```mermaid
flowchart TD
    In([Mensagem]) --> C0{"normal_response<br/>is_system_question?<br/>(question_classifier_agent)"}

    C0 -->|Sim: guia/FAQ/sistema| QA["answer_system<br/>question_answer_agent"]
    C0 -->|Não: técnica/EMBRAPA| C1{"check_registered_property?<br/>all_properties em session_state"}

    C1 -->|Sim| Team["team_response<br/>pasto_legal_team"]
    C1 -->|Não| RA["register_and_analyze"]

    QA --> Out([Saída para o merge])
    Team --> Out

    RA --> Reset["reset_registration_flag<br/>property_name_set = False"]
    Reset --> Loop["property_registration_loop<br/>Loop max=5"]
    Loop --> C2{"registered_or_canceled?<br/>property_name_set?"}

    C2 -->|Sim| Hitl["preliminary_analysis<br/>property_analyst_agent<br/>+ HumanReview (HITL)"]
    C2 -->|Não| Cancel["property_canceled<br/>mensagem de cancelamento"]
    Hitl --> Out
    Cancel --> Out

    style C0 fill:#ffe,stroke:#886
    style C1 fill:#ffe,stroke:#886
    style C2 fill:#ffe,stroke:#886
    style Hitl fill:#fef,stroke:#848
    style Loop fill:#eef,stroke:#446
```

---

## 4. Detalhe — `property_registration_loop` (o Loop de cadastro)

O `Loop` roda `property_manager_agent` + `check_registration_done` por até 5 iterações, encadeando a saída de uma iteração na próxima (`forward_iteration_output=True`).

```mermaid
flowchart TD
    Start([Início do Loop]) --> Iter["Iteração i (1..5)"]
    Iter --> PM["property_manager<br/>property_manager_agent"]
    PM --> CD{"check_registration_done<br/>property_name_set?"}
    CD -->|Não| Fwd["Encaminha conteúdo do agente<br/>→ próxima iteração"]
    Fwd -->|próxima iteração| Iter
    CD -->|Sim| Done['Retorna "DONE"']
    Done --> Exit([Sai do Loop])

    Iter -. max 5 atingido .-> MaxExit["Saída por limite<br/>sem DONE"]
    MaxExit --> Exit

    style CD fill:#ffe,stroke:#886
    style Done fill:#efe,stroke:#484
    style MaxExit fill:#fee,stroke:#844
```

---

## 5. Sequência — Execução de ponta a ponta (com paralelismo e HITL)

Mostra como as duas vertentes rodam em paralelo e onde o HITL pausa a execução antes do merge.

```mermaid
sequenceDiagram
    autonumber
    participant U as Usuário
    participant WF as Workflow
    participant EB as evaluation_branch
    participant NR as normal_response
    participant MR as merge_response
    participant DB as Banco (feedback)

    U->>WF: mensagem
    activate WF
    par grade_and_respond
        WF->>EB: rodar
        EB->>EB: grade_satisfaction (1..5)
        EB->>EB: branch_on_grade → handler
        alt nota < 3
            EB->>DB: save_frustration (FrustrationFeedback)
        else nota > 3
            EB->>DB: save_amazed (PositiveFeedback)
        else nota = 3
            EB->>EB: neutral_handler
        end
        EB-->>WF: handler_message
    and
        WF->>NR: rodar
        NR->>NR: is_system_question?
        alt sistema
            NR->>NR: question_answer_agent
        else técnica + registrado
            NR->>NR: pasto_legal_team
        else técnica + sem registro
            loop até 5 ou DONE
                NR->>NR: property_manager_agent
                NR->>NR: check_registration_done
            end
            alt DONE (set_property_name OK)
                NR->>NR: property_analyst_agent
                Note over NR: HumanReview: pausa (is_paused)
                Note over WF: continue_run() + req.confirm()
                NR-->>WF: análise preliminar
            else falhou
                NR->>NR: property_canceled
            end
        end
        NR-->>WF: resposta normal
    end
    WF->>MR: merge_response
    MR->>MR: combina (desculpas se nota<3)
    MR-->>WF: resposta final
    WF-->>U: resposta
    deactivate WF
```

---

## 6. Módulos — Grafo de Dependências

Como o monolito foi dividido em `app/workflows/`. Sem ciclos.

```mermaid
flowchart LR
    feedback["feedback.py<br/>merge_response<br/>save_frustration<br/>save_amazed"]
    satisfaction["satisfaction.py<br/>evaluation_branch"]
    normal["normal_response.py<br/>normal_response"]
    main["main_workflow.py<br/>pasto_legal_workflow<br/>(composição raiz)"]
    phone["phone_check.py<br/>phone_number_check<br/>(não conectado)"]

    satisfaction -->|importa save_*| feedback
    main -->|importa evaluation_branch| satisfaction
    main -->|importa normal_response| normal
    main -->|importa merge_response| feedback

    main -->|importa db| DB["app.database.agno_db"]

    style main fill:#eef,stroke:#446,stroke-width:2px
    style phone fill:#eee,stroke:#999,stroke-dasharray: 4 4
```

---

## 7. Fluxo de `session_state`

Quais chaves o Workflow lê/escreve no `session_state` compartilhado. Esse dicionário é a cola entre as vertentes paralelas e o merge.

```mermaid
flowchart LR
    subgraph Reads["Lidos"]
        R1["all_properties<br/>(has_registered_property)"]
        R2["property_name_set<br/>(property_name_set,<br/>check_registration_done)"]
    end

    subgraph Writes["Escritos"]
        W1["satisfaction_grade<br/>(grade_satisfaction)"]
        W2["handler_message<br/>(handlers)"]
        W3["property_name_set<br/>(reset_registration_flag=False,<br/>set_property_name=True)"]
    end

    Grade["grade_satisfaction"] --> W1
    Handlers["handle_*"] --> W2
    Reset["reset_registration_flag"] --> W3
    Tool["set_property_name<br/>(tool)"] --> W3

    W1 --> Branch["branch_on_grade<br/>(is_frustrated/is_amazed)"]
    W1 --> Merge["merge_response<br/>(grade<3?)"]
    W2 --> Merge
    R1 --> HasReg["check_registered_property"]
    R2 --> RegOrCanc["registered_or_canceled"]
    R2 --> CheckDone["check_registration_done<br/>→ DONE marker"]

    style Writes fill:#efe,stroke:#484
    style Reads fill:#eef,stroke:#446
```

> **Observação sobre o `Loop`:** o `end_condition` recebe apenas `List[StepOutput]` (sem acesso a `session_state`). Por isso `check_registration_done` expõe a flag como o marcador `"DONE"` em um `StepOutput`, e `_registration_end_condition` procura por `"DONE"`. Com `forward_iteration_output=True`, quando ainda não terminou, o passo repassa o conteúdo anterior do agente para a próxima iteração manter a conversa.

---

## 8. Mapa de Saídas do `merge_response`

Como o resultado final é montado conforme a nota de satisfação.

```mermaid
flowchart TD
    Merge["merge_response"]
    Merge --> G{"grade < 3?"}
    G -->|Sim: frustrado| Frustrado["\"Desculpe pelo inconveniente. {handler}\n\nAqui está uma resposta melhor:\n{normal_response}\""]
    G -->|Não: neutro ou encantado| NeutroOk["{handler}\n\n{normal_response}"]
    NeutroOk --> SemHandler{"handler vazio?"}
    SemHandler -->|Sim| ApenasNormal["{normal_response}"]
    SemHandler -->|Não| ComHandler["{handler}\n\n{normal_response}"]

    Frustrado --> Out([Resposta final])
    ApenasNormal --> Out
    ComHandler --> Out

    style Frustrado fill:#fee,stroke:#844
    style ComHandler fill:#efe,stroke:#484
    style ApenasNormal fill:#efe,stroke:#484
```