# Guia de Configuração: Ollama (Local) + Docker

Este documento descreve como configurar o seu ambiente para que o serviço rodando dentro de um container Docker consiga se comunicar com o **Ollama** instalado nativamente na sua máquina física.

## O Problema
Por padrão, o Docker isola a rede do container. O `localhost` dentro do container refere-se ao próprio container, não à sua máquina. Além disso, por segurança, o Ollama vem configurado para aceitar conexões apenas da própria máquina física (`127.0.0.1`).

---

## 1. Configuração no `docker-compose.yml`

Para que o container saiba quem é a sua máquina física, você deve mapear o hostname `host.docker.internal`.

No seu serviço, adicione:

```yaml
services:
  seu_serviço:
    # ... outras configurações ...
    environment:
      - OLLAMA_HOST=http://host.docker.internal:11434
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

* `extra_hosts`: Mapeia o IP do gateway do Docker para o nome `host.docker.internal`.
* `OLLAMA_HOST`: Variável de ambiente que a maioria das bibliotecas (LangChain, Ollama-python) utiliza para encontrar a API.

---

## 2. Configuração no Host (Sua Máquina)

Você precisa autorizar o Ollama a receber conexões vindas da rede virtual do Docker.

### No Linux (Ubuntu/Debian)
O Ollama roda como um serviço do `systemd`. Precisamos adicionar uma variável de ambiente ao serviço:

1. Crie o arquivo de configuração de override:
   ```bash
   sudo mkdir -p /etc/systemd/system/ollama.service.d
   echo -e "[Service]\nEnvironment=\"OLLAMA_HOST=0.0.0.0\"" | sudo tee /etc/systemd/system/ollama.service.d/override.conf
   ```

2. Recarregue e reinicie o serviço:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart ollama
   ```

3. **Verificação:** Rode `sudo ss -tulnp | grep 11434`. Deve aparecer `0.0.0.0:11434` ou `*:11434`. Se aparecer `127.0.0.1`, a configuração falhou.

### No Windows
1. Feche o Ollama totalmente (ícone na bandeja do sistema).
2. Abra o Terminal (PowerShell ou CMD).
3. Defina a variável de ambiente para a sessão atual:
   * PowerShell: `$env:OLLAMA_HOST="0.0.0.0"`
   * CMD: `set OLLAMA_HOST=0.0.0.0`
4. Inicie o Ollama pelo mesmo terminal: `ollama serve`.

### No macOS
1. Encerre o aplicativo Ollama.
2. No Terminal, execute:
   ```bash
   launchctl setenv OLLAMA_HOST "0.0.0.0"
   ```
3. Reinicie o aplicativo Ollama.

---

## 3. Firewall (Caso a conexão falhe)

Se as configurações acima estiverem corretas e a conexão ainda for recusada, o seu firewall pode estar bloqueando a porta.

* **Linux (UFW):** `sudo ufw allow 11434/tcp`
* **Windows:** Adicione uma regra de entrada no Firewall para a porta `11434`.

---

## 4. Teste de Conexão

Para garantir que tudo está funcionando, rode este comando de dentro do container (substitua `<container_id>` pelo ID ou nome do seu container):

```bash
docker exec -it <container_id> curl http://host.docker.internal:11434
```

**Resposta esperada:** `Ollama is running`