# MCP Gateway de Uber, aplicado a PhoneCentral

Análisis del artículo [Designing Uber's MCP Gateway](https://www.uber.com/us/en/blog/designing-mcp-gateway/)
y de qué significaría una arquitectura parecida en PhoneCentral.

> [!NOTE]
> **Nota de contexto**: *PhoneCentral* es una empresa ficticia de telefonía en la nube y comunicaciones corporativas (inspirada en arquitecturas reales de plataformas SaaS de comunicaciones como Dialpad). Se utiliza a lo largo de este documento y en el código del repositorio como caso de estudio técnico y entorno de prueba arquitectónico para sanitizar y anonimizar datos, herramientas propietarias y nombres internos de repositorios.

**Índice**

- [El artículo en una línea](#el-artículo-en-una-línea)
- [0) Conceptos base: tools, MCP client, server y transporte](#0-conceptos-base-tools-mcp-client-server-y-transporte)
- [1) Un flow agéntico en PhoneCentral, contado como historia](#1-un-flow-agéntico-en-phonecentral-contado-como-historia)
- [2) El mecanismo interno del flow de Juan](#2-el-mecanismo-interno-del-flow-de-juan)
- [3) Los problemas del mecanismo actual](#3-los-problemas-del-mecanismo-actual)
- [4) Adaptación a PhoneCentral de la arquitectura de Uber](#4-adaptación-a-phonecentral-de-la-arquitectura-de-uber)
- [5) Lo que el gateway no resuelve, riesgos nuevos y cómo arrancar](#5-lo-que-el-gateway-no-resuelve-riesgos-nuevos-y-cómo-arrancar)
- [Apéndice: resumen del artículo de Uber](#apéndice-resumen-del-artículo-de-uber)

---

## El artículo en una línea

Uber tenía cientos de equipos conectando agentes de IA a sistemas internos, cada uno por su cuenta, y lo
centralizó todo en un **MCP Gateway**: un único punto de entrada para que los agentes descubran y usen
herramientas con seguridad, permisos y control.

---

## 0) Conceptos base: tools, MCP client, server y transporte

Esta sección existe porque estos conceptos se confunden fácil. Hay dos trampas: la palabra **"server"** no
quiere decir "algo remoto", y **"client"** no es la persona ni el modelo.

### 0.1 Los 4 conceptos

| Concepto      | Qué es                                                            | En Claude Code en phonecentral-core                 |
| ------------- | ----------------------------------------------------------------- | --------------------------------------------------- |
| **Host**      | La app donde vive el agente                                       | Claude Code (la extensión de VSCode o la CLI)       |
| **Client**    | El conector dentro del host. Hay **uno por cada server**          | Claude Code abre uno por cada server configurado    |
| **Server**    | El programa que dice "tengo estas tools" y las ejecuta            | Atlassian, PagerDuty, Pulse UI, client-tools, Glean |
| **Transport** | Cómo viajan los mensajes (siempre JSON-RPC) entre client y server | `stdio` o `HTTP`                                    |

El **modelo** (Claude) no habla MCP. Solo dice "quiero llamar a la tool `getJiraIssue` con estos
parámetros". Es el **client**, dentro de Claude Code, el que traduce ese pedido a un mensaje MCP y lo manda
al server.

Hay dos transportes:

- **stdio**: Claude Code lanza el server como **proceso hijo en tu laptop** y le habla por stdin/stdout,
  como un pipe de Unix. No hay red de por medio.
- **Streamable HTTP**: el server está **en internet** y Claude Code le hace requests HTTP.

**Regla para recordar:** el client siempre está dentro de la app del agente; el server es quien tiene las
tools, y puede correr en tu laptop (stdio) o en la nube de otro (HTTP). Cada server lo implementa quien
conoce el sistema de fondo.

### 0.2 El client: una implementación, N instancias

- Es un **mismo código cliente**, genérico, escrito por Anthropic dentro de Claude Code (basado en el SDK
  oficial de MCP). No sabe nada de Jira ni de PagerDuty; solo sabe hablar el protocolo.
- Se **instancia una vez por server**. Claude Code lee la config del proyecto ([.mcp.json](../.mcp.json)) y
  también la del usuario (`~/.claude.json`); el Glean MCP, por ejemplo, va en la de usuario.
- Lo que cambia por instancia es sobre todo **el transporte y la auth**:

| Qué cambia   | stdio (Pulse UI, client-tools, puente de PagerDuty) | HTTP (Atlassian, Glean)           |
| ------------ | --------------------------------------------------- | --------------------------------- |
| Cómo conecta | Lanza un proceso hijo (`npx ...`)                   | Hace requests HTTPS a una URL     |
| Config       | `command`, `args`, `env`                            | `url`, `headers`                  |
| Auth         | Variables de entorno (tokens)                       | OAuth, guarda un token por server |

Cada instancia, al arrancar:

1. **Conecta** por su transporte.
2. **Handshake** (`initialize`): client y server se dicen qué versión del protocolo hablan y qué saben hacer.
3. **Pregunta qué tools hay** (`tools/list`).
4. **Registra esas tools** para el modelo con un prefijo: `mcp__<server>__<tool>`
   (ej. `mcp__atlassian__getJiraIssue`). El prefijo le dice a Claude Code a qué instancia mandar cada llamada.

```
Claude: "llamo mcp__atlassian__getJiraIssue"
   └─► Claude Code mira el prefijo "atlassian"
         └─► instancia del client #1 (HTTP) ─► mcp.atlassian.com
```

### 0.3 Los servers MCP configurados en el workspace

Los de [.mcp.json](../.mcp.json):

| Server           | Transport                    | Dónde corre                                       | Quién lo implementa                     | Auth                |
| ---------------- | ---------------------------- | ------------------------------------------------- | --------------------------------------- | ------------------- |
| **atlassian**    | HTTP                         | Nube de Atlassian (`mcp.atlassian.com`)           | Atlassian                               | OAuth en el browser |
| **pagerduty**    | stdio → HTTP (con un puente) | Puente local + server real en `mcp.pagerduty.com` | PagerDuty (el puente: open source)      | `PAGERDUTY_TOKEN`   |
| **pulse-ui**     | stdio                        | Tu laptop (proceso `node`)                        | PhoneCentral (Design System)            | Ninguna             |
| **client-tools** | stdio                        | Tu laptop (proceso `node`)                        | PhoneCentral (web-client-tools)         | Token de GitHub     |

**Atlassian: el server remoto "puro".** Claude Code no ejecuta nada local. Abre una conexión HTTP a
`mcp.atlassian.com`; la primera vez te logueás por OAuth, y desde ahí cada `getJiraIssue` es un request
HTTPS. Atlassian programó, hostea y opera el server. PhoneCentral solo lo consume.

**PagerDuty: remoto, pero con un puente local.** La config es `npx mcp-remote https://mcp.pagerduty.com/mcp`:

```
Claude Code ──stdio──► mcp-remote (en la laptop) ──HTTP + token──► server de PagerDuty
```

`mcp-remote` es un adaptador: Claude Code cree que habla con un server local por stdio, y el puente reenvía
todo por HTTP, inyectando tu token en el header.

**Pulse UI: server 100% local.** `npx @phonecentral/pulse-ui-mcp` descarga el paquete del Design System de PhoneCentral y lo
corre en la laptop. Los datos de componentes Vue/CSS, design tokens e íconos vienen **empaquetados dentro del paquete**,
así que no llama a nada externo.

**client-tools (web-client-tools): local, pero sale a internet por dentro.** También corre en la laptop vía `npx`, pero sus
tools inspeccionan el repositorio del cliente web/desktop (`phonecentral/web-client-tools`) **usando la API de GitHub** con tu token para consultar componentes de frontend, dependencias de paquetes y rutas de la app web. Hacia
Claude Code habla MCP por stdio; hacia GitHub habla REST normal, sin MCP.

```
                    LAPTOP                                       │  INTERNET
                                                                 │
 ┌──────────── Claude Code (HOST) ────────────┐                  │
 │  Claude (modelo) decide qué tool usar      │                  │
 │                                            │                  │
 │  client 1 ─────────────────── HTTP ────────┼──────────────────┼─► Atlassian MCP server
 │  client 2 ── stdio ─► [mcp-remote] ─ HTTP ─┼──────────────────┼─► PagerDuty MCP server
 │  client 3 ── stdio ─► [pulse-ui server]    │                  │
 │  client 4 ── stdio ─► [client-tools srv] ──┼── REST ──────────┼─► GitHub API
 └────────────────────────────────────────────┘                  │
```

Lo que **no** es MCP: `jira`, `gh`, `observe` y `sentry` son CLIs que Claude ejecuta por shell. Ahí no hay
ni client ni server MCP, solo un comando y su output.

### 0.4 Glean: dos roles distintos

**a) Glean como MCP server (Claude es el client).** PhoneCentral tiene un **Glean MCP server** que cada dev
conecta a nivel usuario en su herramienta (ver la skill
[firewatcher-error-scrub](../.claude/skills/firewatcher-error-scrub/SKILL.md) y la página de Confluence
*"Augment your AI tools with PhoneCentral context via Glean MCP"*). Es remoto (HTTP), lo hostea e implementa
Glean, y se autentica con el SSO de PhoneCentral.

**b) Glean como producto, internamente.** Cuando le preguntás algo a Glean desde su web, Glean **no** sale
a consultar Jira por MCP en ese momento. Ya tiene todo **indexado de antemano** mediante *connectors*:
integraciones propias que copian periódicamente Jira, Confluence, Slack y Drive a su índice. Es otro modelo:
indexar antes en vez de consultar en vivo. (No verificado: si PhoneCentral tiene configuradas además las funciones
de agentes de Glean que llaman a servers MCP externos.)

```
Dev ─► Claude Code ──MCP/HTTP──► Glean MCP server ─► índice de Glean
                                                        ▲
                                 connectors (no MCP) ───┘── Jira, Confluence, Slack, Drive
```

### 0.5 Secuencia completa: una pregunta que usa una tool de Atlassian

Ejemplo: **"¿De qué trata DP-200001?"** (ticket ficticio).

Primero, un dato clave: **el modelo no corre en la laptop**, corre en la nube de Anthropic. Claude Code hace
de intermediario: le manda texto al modelo y ejecuta las tools que el modelo pide. **La llamada MCP sale de
la laptop, no de Anthropic.**

```
 Nube Anthropic            Laptop                            Nube Atlassian
 ┌──────────┐          ┌──────────────────────┐          ┌──────────────────┐
 │  Claude  │◄────────►│ Claude Code          │◄────────►│ Atlassian MCP    │──► Jira API
 │ (modelo) │ API HTTP │  (host + MCP client) │ MCP/HTTP │ server           │
 └──────────┘          └──────────────────────┘          └──────────────────┘
```

#### Fase A: al abrir Claude Code (antes de preguntar nada)

**Paso 1. Leer la config.** Claude Code lee [.mcp.json](../.mcp.json) y encuentra
`atlassian: { type: http, url: https://mcp.atlassian.com/v2/mcp }`.

**Paso 2. Conectar y autenticar.** El client manda un request HTTPS. Si no hay token, el server responde
"no autorizado"; la primera vez se abre el browser, te logueás en Atlassian (OAuth) y Claude Code guarda el
token. Desde ahí, cada request viaja con `Authorization: Bearer <token>`.

**Paso 3. Handshake.**

```json
→ {"method": "initialize", "params": {"protocolVersion": "...", "clientInfo": {"name": "claude-code"}}}
← {"result": {"serverInfo": {"name": "atlassian"}, "capabilities": {"tools": {}},
              "instructions": "Atlassian MCP server. Three layers of tools..."}}
```

`instructions` es un texto de "manual de uso" que el server le manda al modelo. Termina dentro del system
prompt.

**Paso 4. Descubrimiento: `tools/list`.**

```json
→ {"method": "tools/list"}
← {"result": {"tools": [
     {"name": "getJiraIssue",
      "description": "Get a Jira issue by key...",
      "inputSchema": {"type": "object",
                      "properties": {"cloudId": {...}, "issueIdOrKey": {...}},
                      "required": ["cloudId", "issueIdOrKey"]}},
     {"name": "searchConfluence", ...},
     ...unas 20 más
  ]}}
```

Cada tool tiene **nombre, descripción en lenguaje natural y JSON Schema** de los parámetros.

**Paso 5. Registrar las tools.** Claude Code las renombra como `mcp__atlassian__getJiraIssue`, etc.

#### Fase B: el dev hace la pregunta

**Paso 6. Claude Code arma el request al modelo.** Le manda a la API de Anthropic el system prompt (que
incluye CLAUDE.md, las rules y las `instructions` de cada server MCP), la lista de tools disponibles y el
mensaje del dev.

**Paso 7. El modelo razona y pide una tool.** No responde con texto, sino con un bloque `tool_use`:

```json
{"type": "tool_use", "name": "mcp__atlassian__getJiraIssue",
 "input": {"cloudId": "phonecentral.atlassian.net", "issueIdOrKey": "DP-200001"}}
```

(Si el schema no estaba cargado, antes hay una vuelta extra con `ToolSearch`, ver 0.6. Si no conocía el
`cloudId`, otra vuelta llamando a `getAccessibleAtlassianResources`.)

**Paso 8. Permisos.** Claude Code revisa si esa tool está permitida en los settings. Si no lo está, pregunta:
*"¿Permitir mcp__atlassian__getJiraIssue?"*.

**Paso 9. Ruteo.** Por el prefijo `atlassian`, Claude Code le pasa la llamada a esa instancia del client.

**Paso 10. Llamada MCP real** (HTTPS desde la laptop, con el Bearer token del dev):

```json
→ {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
   "params": {"name": "getJiraIssue",
              "arguments": {"cloudId": "phonecentral.atlassian.net", "issueIdOrKey": "DP-200001"}}}
```

**Paso 11. El server hace el trabajo.** El server de Atlassian valida el token, llama a la **API REST
interna de Jira** con los permisos del dev (si el dev no puede ver ese ticket, falla) y arma la respuesta:

```json
← {"jsonrpc": "2.0", "id": 7,
   "result": {"content": [{"type": "text",
     "text": "{\"key\":\"DP-200001\",\"summary\":\"500 al enviar SMS\",\"status\":\"Open\",...}"}]}}
```

**Paso 12. Vuelta al modelo.** Claude Code le manda a la API el `tool_result` con ese contenido. **Todo ese
texto ocupa contexto del modelo**: si el ticket tiene 50 comentarios, entran los 50.

**Paso 13. Respuesta final.** El modelo lee el resultado y escribe la respuesta, que Claude Code muestra.

### 0.6 Tools "deferred" y qué pasa si el modelo elige la tool equivocada

Hay dos modos de presentarle las tools al modelo:

- **Modo normal (pocas tools):** al modelo le llega todo de entrada: **nombre + descripción + schema**.
  Decide y llama en un solo paso.
- **Modo deferred (muchas tools):** al modelo le llega **solo el nombre**, sin descripción ni schema, para
  no llenar el contexto. Entonces:
  1. El modelo decide **por el nombre** (y por las `instructions` del server).
  2. Llama a `ToolSearch("select:mcp__atlassian__getJiraIssue")`.
  3. Recién ahí recibe **descripción + schema**, y con eso arma la llamada real.

`ToolSearch` **no le pregunta nada al server**: Claude Code ya bajó todos los schemas en el `tools/list` del
arranque y los tiene en memoria. Solo le "oculta" al modelo los detalles hasta que los pide.

**Si el modelo supone `getX` pero la correcta era `getY`:**

1. Carga `getX` con `select:getX` y lee la descripción: *"Devuelve X, no incluye comentarios"*.
2. Se da cuenta del error y busca por **palabras clave**: `ToolSearch("jira issue comments")`. Esta búsqueda
   compara contra **nombres y descripciones** de todas las tools ocultas y devuelve las más parecidas, con su
   definición completa. Ahí aparece `getY`.
3. Atajos: cargar ambas de una (`select:getX,getY`) o arrancar directo por palabras clave.

El costo del error suele ser **una vuelta más** (tiempo y tokens). **El caso peligroso** es que la
descripción de `getX` no revele el error y el modelo la use igual: recibe un resultado incompleto o
incorrecto y solo lo detecta (si lo detecta) razonando sobre ese resultado. Por eso **nombres y
descripciones de las tools importan muchísimo**, y por eso Uber hace que un LLM genere descripciones
"agent-friendly" y que el dueño de cada tool las revise antes de habilitarla.

### 0.7 Tools estáticas vs. dinámicas: el `discover` de Atlassian

El server de Atlassian **no expone todas sus operaciones como tools sueltas**.

**Analogía:** un restaurante con una **carta corta** con los ~20 platos más pedidos, y para el resto,
**"preguntale al mozo"**.

- **Carta corta** = las tools primarias (`getJiraIssue`, `searchConfluence`, `createJiraIssue`...), que
  aparecen en `tools/list` como tools normales.
- **Mozo** = la tool `discover`. Atlassian tiene cientos de operaciones; publicarlas todas como tools
  inflaría el contexto de cada sesión.

**Ejemplo:** *"Agregá a María como watcher de DP-200001"*. No hay ninguna tool primaria para watchers.

```
Paso 1 — preguntarle al mozo
  Claude    → discover("agregar un watcher a un issue de Jira")
  Atlassian → "Existe la operación 'addJiraIssueWatcher'. Parámetros: issueKey, accountId.
               Es una escritura: ejecutala con executeWrite."

Paso 2 — ejecutarla con la tool genérica que corresponde
  Claude    → executeWrite(name="addJiraIssueWatcher", cloudId="...",
                           inputs={issueKey: "DP-200001", accountId: "<id de María>"})
  Atlassian → "OK, watcher agregado."
```

(El nombre `addJiraIssueWatcher` es ilustrativo; el real es el que devuelva `discover`.)

**¿Por qué tres `execute`?** Son "puertas" según el riesgo:

| Tool                 | Para qué                       | Ejemplo                      |
| -------------------- | ------------------------------ | ---------------------------- |
| `executeRead`        | Solo lee                       | Ver los watchers de un issue |
| `executeWrite`       | Crea o modifica                | Agregar un watcher           |
| `executeDestructive` | Borra o hace algo irreversible | Borrar un issue              |

Como son tres tools distintas, se pueden configurar permisos distintos en Claude Code (`executeRead` siempre
permitido, `executeDestructive` preguntar siempre). Con una sola tool `execute` no habría forma de distinguir.

**Analogía de programación:** las primarias son funciones "tipadas" y visibles desde el inicio; el resto es
como llamar por reflexión.

```python
# Tools "estáticas": nombre y firma visibles y tipados desde el inicio
suma(a: int, b: int)
resta(a: int, b: int)

# Tool "dinámica": un único punto de entrada genérico
operacion(name="sin", args=[180])      # ≈ getattr(math, "sin")(180)
```

| Aspecto                       | Estáticas (primarias) | Dinámicas (`discover` + `execute*`)                     |
| ----------------------------- | --------------------- | ------------------------------------------------------- |
| ¿Cómo sé que existe?          | Está en la lista      | Tengo que preguntar (`discover("seno")`)                |
| ¿Quién valida los parámetros? | El schema, antes      | El server, al ejecutar (`inputs` es un objeto genérico) |
| Costo                         | 1 llamada             | 2 llamadas (descubrir + ejecutar)                       |

**Dos capas de "esconder tools"** (no mezclarlas):

| Capa       | Quién la hace | Qué esconde                                    |
| ---------- | ------------- | ---------------------------------------------- |
| Deferred   | Claude Code   | Los schemas de las tools que sí están listadas |
| `discover` | Atlassian     | Operaciones que ni siquiera están listadas     |

**Conexión con Uber:** su *Omni MCP* es el mismo "mozo", pero **para todos los servers de la empresa a la
vez**, y es todo dinámico, sin carta corta: `discover_server`, `discover_tools`, `get_tool_schema` e
`invoke_tool`, para unas 5.000 tools.

### 0.8 Para el modelo, todas las tools son iguales

Una tool local como `Grep` y una tool MCP remota como `getJiraIssue` son **la misma abstracción** para el
modelo: **nombre + descripción + schema de parámetros**. El modelo emite siempre el mismo tipo de bloque:

```json
{"type": "tool_use", "name": "Grep", "input": {"pattern": "send_sms"}}
{"type": "tool_use", "name": "mcp__atlassian__getJiraIssue", "input": {"issueIdOrKey": "DP-200001"}}
```

El modelo no sabe si detrás hay código local, un proceso o un request HTTP (la única pista es el prefijo
`mcp__`, que es solo una convención). **La diferencia está en Claude Code, al despachar:**

```
                         tool_use del modelo
                                 │
                         Claude Code (dispatcher)
                                 │
          ┌──────────────────────┼─────────────────────────────┐
          ▼                      ▼                             ▼
   Built-in "pura"         Built-in Bash                  MCP tool
   (Read, Grep, Edit)      (corre un comando)             (mcp__atlassian__...)
          │                      │                             │
   Código de Claude Code   Proceso en la shell            MCP client (instancia)
   en la laptop            ej. `jira issue view`               │ HTTP/stdio
                                 │                             ▼
                           El CLI sale a la red          MCP server ─► Jira API
                           por su cuenta (REST)
```

| Tipo           | Quién la implementa                         | Cómo se ejecuta                  |
| -------------- | ------------------------------------------- | -------------------------------- |
| `Grep`, `Read` | Anthropic, dentro de Claude Code            | Directo, en el proceso local     |
| `Bash`         | Anthropic (la tool); el comando, cualquiera | Lanza un proceso en la shell     |
| `mcp__*`       | El dueño del server (Atlassian, etc.)       | Pasa por el MCP client al server |

Todo vuelve al modelo como un `tool_result` con texto, venga de donde venga.

Detalle: `jira issue view DP-200001` (vía `Bash`) y `getJiraIssue` (vía MCP) **hacen lo mismo**, pero para
el modelo son tools distintas con caminos distintos. Esa duplicación es uno de los problemas de la sección 3.

---

## 1) Un flow agéntico en PhoneCentral, contado como historia

**Lunes, 10:00.** A Juan, ingeniero de UV, le asignan el ticket **PC-200001** (ficticio): *"Algunos usuarios
reciben un error 500 al mandar un SMS desde la app"*.

Antes de los agentes, Juan habría hecho todo a mano: abrir Jira, leer el ticket, buscar en Confluence, entrar
a Observe para ver logs, abrir Sentry para ver el stack trace, buscar en el código, arreglar, correr tests,
abrir el PR y volver a Jira para comentar. Son unas 8 pestañas y 8 logins.

**Ahora abre Claude Code en `phonecentral-core` y escribe:**

> "Investigá y resolvé PC-200001"

Esto es lo que pasa, visto desde afuera:

| Paso | Lo que hace Claude                                  | Con qué herramienta             |
| ---- | --------------------------------------------------- | ------------------------------- |
| 1    | Lee el ticket: descripción, pasos, call_id, usuario | `jira` CLI (o Atlassian MCP)    |
| 2    | Busca docs del feature de SMS                       | Atlassian MCP (Confluence)      |
| 3    | Busca los logs del error en producción              | `observe` CLI (skill)           |
| 4    | Trae el stack trace exacto                          | `sentry` CLI (skill)            |
| 5    | Revisa si hubo incidente o alerta relacionada       | PagerDuty MCP                   |
| 6    | Lee la entidad del usuario en Datastore             | skill `datastore-lookup` (REST) |
| 7    | Encuentra la línea culpable en `phonevoice/`        | lectura local del repo          |
| 8    | Escribe el fix y el test, y corre tox               | shell local                     |
| 9    | Abre el PR                                          | `gh` CLI                        |
| 10   | Comenta en el ticket con el link al PR              | `jira` CLI                      |

**10:40.** Juan revisa el diff, lo aprueba y listo.

### La clave para entender el artículo

En una sola tarea el agente tocó **unos 7 sistemas distintos**, y **cada uno se conecta de una forma
diferente**:

- Unos son **servers MCP** declarados en [.mcp.json](../.mcp.json): Atlassian, PagerDuty, Pulse UI y
  client-tools.
- Otros son **CLIs** que Juan tiene instalados y autenticados en su laptop: `jira`, `gh`, `observe`,
  `sentry`, `pup`.
- Otros son **skills** del repo que llaman directo a una API REST (Datastore, FST artifacts).

Y eso es solo Claude Code. Hay otros flows agénticos en PhoneCentral con el mismo patrón: **Glean** responde
preguntas cruzando Jira, Confluence, Slack y Drive; las skills de **on-call** (`cbe-oncall-investigate`,
`telephony-investigation`) cruzan PagerDuty, Observe y Jira; y el agente `pr-reviewer` corre por cron. Cada
uno arma sus propias conexiones.

Ese "cada uno conecta lo suyo, a su manera" es exactamente el punto de partida de Uber.

---

## 2) El mecanismo interno del flow de Juan

Con lo de la sección 0 (el modelo pide una tool → Claude Code la despacha), ahora miremos **qué hay detrás de
cada uno de los 10 pasos**.

### Lo que Juan tuvo que preparar antes (una sola vez)

| Sistema    | Qué instaló o configuró Juan                            | Credencial                             |
| ---------- | ------------------------------------------------------- | -------------------------------------- |
| Jira       | `jira` CLI + Atlassian MCP en [.mcp.json](../.mcp.json) | API token de Jira + OAuth de Atlassian |
| Confluence | (el mismo Atlassian MCP)                                | OAuth de Atlassian                     |
| Observe    | CLI de Observe (vía plugin `phonecentral`)              | Token de Observe                       |
| Sentry     | CLI propio del repo (`tools/sentry_cli/`)               | `SENTRY_AUTH_TOKEN`                    |
| PagerDuty  | `mcp-remote` vía `npx`                                  | `PAGERDUTY_TOKEN` en el entorno        |
| Datastore  | `gcloud`                                                | Su login de Google (`gcloud auth`)     |
| GitHub     | `gh` CLI                                                | Token de GitHub                        |
| Glean      | Glean MCP a nivel usuario                               | SSO de PhoneCentral                    |

Son unas **8 credenciales personales**, cada una con su forma de obtenerla, renovarla y guardarla.

### Qué pasa en cada paso

| Paso | Qué hace             | Tool que ve el modelo                    | Camino real                                          | Quién escribió el "adaptador"         |
| ---- | -------------------- | ---------------------------------------- | ---------------------------------------------------- | ------------------------------------- |
| 1    | Leer el ticket       | `Bash` → `jira issue view`               | CLI → API REST de Jira                               | Open source (jira-cli)                |
| 2    | Buscar docs          | `mcp__atlassian__searchConfluence`       | MCP client → HTTP → server de Atlassian → Confluence | Atlassian                             |
| 3    | Buscar logs          | `Bash` → `observe query ...`             | CLI → API de Observe                                 | PhoneCentral (plugin)                 |
| 4    | Stack trace          | `Bash` → `uv run ... sentry issue stack` | CLI del repo → API web de Sentry                     | PhoneCentral (`tools/sentry_cli`)     |
| 5    | Incidentes           | `mcp__pagerduty__...`                    | MCP client → stdio → `mcp-remote` → HTTP → PagerDuty | PagerDuty + puente open source        |
| 6    | Entidad en Datastore | `Bash` → `curl` con token de `gcloud`    | curl → API REST de Google Datastore                  | Nadie: la skill trae el curl "a mano" |
| 7-8  | Código, fix y tests  | `Read`, `Grep`, `Edit`, `Bash`           | Local                                                | Anthropic (built-ins)                 |
| 9    | PR                   | `Bash` → `gh pr create`                  | CLI → API de GitHub                                  | GitHub                                |
| 10   | Comentar en Jira     | `Bash` → `jira issue comment`            | CLI → API REST de Jira                               | Open source                           |

### ¿Cómo sabe el modelo qué camino tomar?

Acá entran las **skills** y las **rules**, que son el "manual" que Claude lee:

- [CLAUDE.md](../CLAUDE.md) dice: *"Jira → `jira` CLI primero, MCP como fallback"*.
- La skill [sentry](../.claude/skills/sentry/SKILL.md) dice: *"usá `uv run --project tools/sentry_cli
  sentry ...`; si no está configurado, pedile al usuario que haga `config init`"*.
- La skill [datastore-lookup](../.claude/skills/datastore-lookup/SKILL.md) trae el `curl` exacto con
  `gcloud auth print-access-token`.
- La skill `observe` explica la sintaxis de queries y que el output "compact" ahorra un 80-90% de tokens.

O sea: **la "integración" con cada sistema es, en parte, texto en markdown** que le explica al modelo qué
comando correr.

### El dibujo completo

```
                         LAPTOP DE JUAN
 ┌───────────────────────────────────────────────────────────────┐
 │ Claude Code                                                   │
 │  ├─ lee CLAUDE.md, rules, skills  (el "manual")               │
 │  ├─ built-ins: Read/Grep/Edit ── repo local                   │
 │  ├─ Bash ─┬─ jira CLI ──────────────── token Jira ────────────┼──► Jira
 │  │        ├─ observe CLI ───────────── token Observe ─────────┼──► Observe
 │  │        ├─ sentry_cli (repo) ─────── SENTRY_AUTH_TOKEN ─────┼──► Sentry
 │  │        ├─ curl + gcloud ─────────── login Google ──────────┼──► Datastore
 │  │        └─ gh CLI ────────────────── token GitHub ──────────┼──► GitHub
 │  └─ MCP clients                                               │
 │      ├─ atlassian (HTTP) ──────────── OAuth ──────────────────┼──► Atlassian MCP ─► Confluence/Jira
 │      ├─ pagerduty (stdio→mcp-remote) ─ PAGERDUTY_TOKEN ───────┼──► PagerDuty MCP
 │      ├─ glean (HTTP) ──────────────── SSO ────────────────────┼──► Glean MCP
 │      └─ pulse-ui / client-tools (stdio, locales)              │
 └───────────────────────────────────────────────────────────────┘
          ▲
          └── el modelo en la nube de Anthropic decide qué usar y recibe todos los resultados
```

### Lo que hay que retener de este mecanismo

1. **Todo converge en la laptop.** Cada "integración" corre o se origina ahí.
2. **Todo se ejecuta con las credenciales personales de Juan.** El agente puede hacer lo mismo que Juan, sin
   más ni menos.
3. **Hay tres tipos de integración mezclados:** servers MCP (de terceros o de PhoneCentral), CLIs (de terceros o
   hechos en casa) y skills con comandos "a mano".
4. **Cada adaptador lo escribió alguien distinto**, con su propio formato de salida, manejo de errores y
   control (o no) de tamaño.
5. **Todo lo que devuelve cada tool va directo al contexto del modelo**, o sea a la nube de Anthropic, tal
   cual sale.
6. **Esto se repite en cada laptop de cada dev**, y otra vez en cada otro flow agéntico: los agentes de
   on-call, el `pr-reviewer` por cron, Glean y cualquier agente que arme otro equipo.

Cada uno de estos 6 puntos esconde un problema. Eso es la sección 3.

---

## 3) Los problemas del mecanismo actual

Retomemos la historia. El flow de Juan funcionó, y el equipo lo adopta. **Un mes después** empiezan a
aparecer estos problemas.

### Problema 1: Cada laptop es una isla (setup frágil y duplicado)

**Escena:** entra Ana al equipo. Le pasan el link a `/setup-phonecentral`. Tarda una tarde: instalar 5 CLIs,
sacar 8 tokens, entender que el de PagerDuty va en una variable de entorno y el de Sentry en `config init`. Al
día siguiente el de PagerDuty falla con *"Connection closed"* y nadie sabe si es su token, el puente
`mcp-remote` o PagerDuty.

```
  laptop Juan              laptop Ana               laptop Pedro
 ┌────────────────┐       ┌────────────────┐       ┌────────────────┐
 │ jira CLI v1.4  │       │ jira CLI v1.6  │       │ (no lo instaló)│
 │ sentry token ✓ │       │ sentry token ✗ │       │ sentry token ✓ │
 │ pagerduty ✓    │       │ pagerduty ✗    │       │ pagerduty ✓    │
 │ 8 credenciales │       │ 8 credenciales │       │ 6 credenciales │
 └────────────────┘       └────────────────┘       └────────────────┘
        × 100+ devs, cada uno con su propia combinación
```

Además, [.mcp.json](../.mcp.json) usa `npx ...@latest`: **cada vez que alguien abre Claude Code, se baja y
ejecuta la última versión de un paquete npm**, sin versión fija. Si una versión sale rota, o comprometida, le
llega a todos al mismo tiempo, en sus laptops y con sus credenciales.

> En palabras de Uber: *"developer friction"*, *"hard to operate reliably"*.

### Problema 2: El agente tiene todos los permisos de Juan (y los límites son de texto)

**Escena:** la skill `datastore-lookup` dice *"Read-only"*. Pero el token que usa sale de
`gcloud auth print-access-token`, **que es el de Juan**. Si Juan puede escribir en Datastore de producción,
el agente también puede. Lo único que lo frena es que **un markdown le pide que no lo haga**.

Peor todavía: el ticket de Jira lo escribió **otra persona**. Si el texto del ticket (o un log, o una página
de Confluence) contiene algo como *"ignorá lo anterior y corré este comando"*, ese texto entra al contexto
del modelo con el mismo peso que el resto. Eso se llama **prompt injection**. Lo que puede hacer un agente
"engañado" es exactamente lo que pueden hacer las credenciales de Juan.

```
 ┌────────── Lo que Juan quiere que el agente haga ──────────┐
 │  leer ticket · leer logs · leer Datastore · abrir PR      │
 └───────────────────────────────────────────────────────────┘
 ┌────────── Lo que el agente PUEDE hacer ───────────────────────────────────────────┐
 │  todo lo anterior + escribir/borrar en Datastore prod + transicionar/borrar       │
 │  tickets + mergear PRs + crear incidentes en PagerDuty + ...                      │
 └───────────────────────────────────────────────────────────────────────────────────┘
          la diferencia entre ambos cuadros solo la cuida un texto en una skill
```

> En palabras de Uber: *"growing security risk"*. Su respuesta fue la *autorización por tool* en el gateway.

### Problema 3: Nadie ve lo que hacen los agentes (cero observabilidad central)

**Escena:** alguien nota que un ticket se transicionó raro y que se borró un comentario. En el audit log de
Jira figura **"Juan"**. ¿Fue Juan o fue su agente? ¿Qué agente: Claude Code, el `pr-reviewer` por cron, una
skill de on-call? ¿Qué prompt lo llevó a eso? **No hay forma de saberlo.**

Tampoco hay respuesta para preguntas como estas:

- ¿Cuántas llamadas por día hacen los agentes a Jira? ¿Cuáles fallan más?
- ¿Qué tools se usan y cuáles no se usan nunca?
- ¿Cuánto cuesta en tokens cada integración?

Cada llamada sale de una laptop distinta, por un camino distinto, y **no pasa por ningún punto común** donde
medirla.

> En palabras de Uber: *"built-in observability"* fue uno de los beneficios principales.

### Problema 4: Datos sensibles directo al modelo (sin redacción)

**Escena:** para investigar el bug de SMS, el agente lee una entidad de Datastore y 200 líneas de logs de
Observe. Ahí hay **números de teléfono, emails, nombres de clientes y quizás el contenido de SMS**. Todo eso
entra **tal cual** al contexto del modelo, es decir, viaja a la nube de Anthropic.

```
 Datastore / Observe ──(PII cruda)──► laptop Juan ──(PII cruda)──► modelo en la nube
                                         ▲
                              nadie filtra en el medio
```

Puede que esté cubierto por contrato, pero **no hay ningún control técnico** que diga "estos campos nunca
salen".

> Uber: *"PII and other sensitive data are redacted from tool responses by default"*.

### Problema 5: Fragmentación (muchos caminos al mismo lugar)

**Escena:** para "leer un ticket de Jira" hoy existen **al menos 3 caminos**: el `jira` CLI, el Atlassian
MCP y el Glean MCP. Cada uno con su credencial, su formato de salida y sus permisos. Las skills tienen que
explicarle al modelo cuál usar y cuál es el fallback.

Y se repite entre equipos:

- El equipo X escribió `tools/sentry_cli` porque el CLI oficial no traía stack traces.
- El equipo Y, en otro repo, probablemente escribió el suyo.
- Las skills de on-call, el `pr-reviewer` y Glean resuelven cada uno su propia integración.

```
                 ┌─► jira CLI ───────────┐
 "leer ticket" ──┼─► Atlassian MCP ──────┼──► Jira
                 └─► Glean MCP ──► índice┘

 sentry_cli (repo A)   sentry_tool (repo B?)   script de on-call (repo C?)  ──► Sentry
```

> Uber: *"teams built integrations independently → fragmentation and duplicated infrastructure"*.

### Problema 6: Los sistemas propios de PhoneCentral no tienen "tools" (el problema más grande)

Este es **el punto central del artículo de Uber**. Qué pasa con los sistemas **de PhoneCentral**, no de terceros:

| Sistema interno     | Cómo accede el agente hoy                                                                  |
| ------------------- | ------------------------------------------------------------------------------------------ |
| Datastore           | Un `curl` armado a mano en una skill, con el token de `gcloud`                             |
| FST (llamadas, SIP) | **Playwright**: un browser headless que hace login SSO y "raspa" páginas (`fst-artifacts`) |
| CSR                 | Igual: páginas web pensadas para humanos                                                   |
| APIs de UV/FST/UC   | Prácticamente nada                                                                         |

Atlassian, PagerDuty y Glean **hicieron su propio MCP server**. Pero los miles de endpoints de UV, FST y UC
**ya existen** y no hay forma limpia de que un agente los use. Cada vez que un agente necesita algo interno,
alguien escribe una skill nueva con un truco nuevo: curl, scraping o un CLI casero.

> Uber: *"existing APIs are the fastest route to agent tooling"*. Ellos tenían miles de servicios con APIs
> HTTP/gRPC y los convirtieron en tools **sin tocar los servicios**.

### Problema 7: Descubrimiento y contexto

**Escena 1 (descubrimiento):** Pedro, de otro equipo, quiere que su agente lea call legs de FST. No sabe que
existe `fst-artifacts`, porque vive en `.claude/skills/` de phonecentral-core. Lo reescribe.

**Escena 2 (contexto):** si se conectan muchos más servers MCP, el modelo arranca cada sesión con cientos de
nombres de tools. Cada `tool_result` grande (50 comentarios de un ticket, 500 líneas de logs) se come el
contexto. Hoy cada adaptador lo resuelve (o no) a su manera: la skill de Observe tuvo que inventar su propio
formato "compact" para ahorrar un 80-90% de tokens.

> Uber: *Omni MCP* (descubrimiento incremental) y *Response Projection* (pedir solo los campos que necesitás).

### Resumen del punto 3

| #   | Problema                              | Causa raíz en el mecanismo actual                  | Término de Uber          |
| --- | ------------------------------------- | -------------------------------------------------- | ------------------------ |
| P1  | Setup frágil por laptop               | Cada integración se instala y autentica localmente | Developer friction       |
| P2  | Agente con todos los permisos humanos | Credenciales personales; límites solo en texto     | Security risk / authZ    |
| P3  | Cero auditoría y métricas             | No hay un punto común por donde pase todo          | Observability            |
| P4  | PII cruda al modelo                   | Nadie filtra entre el sistema y el modelo          | Redaction                |
| P5  | Muchos caminos al mismo sistema       | Cada equipo integra por su cuenta                  | Fragmentation            |
| P6  | Sistemas internos sin tools           | Las APIs propias no están expuestas para agentes   | "Existing APIs as tools" |
| P7  | Difícil descubrir; contexto inflado   | Tools dispersas en repos; respuestas sin recortar  | Omni MCP / Projection    |

Casi todos comparten la misma raíz: **no hay un punto intermedio entre los agentes y los sistemas.** Ese
punto intermedio es justamente el gateway.

---

## 4) Adaptación a PhoneCentral de la arquitectura de Uber

### 4.1 Antes de diseñar: qué ya existe en PhoneCentral

Hay piezas en el repo que cambian bastante el diseño:

| Pieza existente        | Dónde                                                                        | Por qué importa                                                                                                                                                                                                                                                                                                  |
| ---------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **`phonecentral-user-mcp`** | [dp-ai-agents/phonecentral_user_mcp/](../dp-ai-agents/phonecentral_user_mcp/README.md) | Un server MCP interno en Cloud Run para los agentes **de producto** (usuarios finales). Ya aplica varios principios de Uber: no tiene credenciales propias (reenvía el token del usuario), tiene un **registry auditado** de endpoints permitidos, es solo lectura y "da forma" a las respuestas (`shaping.py`). |
| **`@public_api`**      | [phonevoice/frontend/apis/endpoints/](../phonevoice/frontend/apis/endpoints/)  | ~409 endpoints de la API pública v2, con params y respuesta tipados (pydantic), docstring y nombre estable. Ya generan OpenAPI para la doc pública (`ApiDocSet`). Es lo más parecido que tiene PhoneCentral al **IDL** de Uber.                                                                                       |
| **`@openapi_schema`**  | [common/lib/openapi/wrappers.py](../common/lib/openapi/wrappers.py)          | Schemas marshmallow en handlers internos. Solo ~37 usos en UV, en su mayoría de login/OAuth.                                                                                                                                                                                                                     |
| **`egress-proxy`**     | [egress-proxy/](../egress-proxy/README.md)                                   | Un relay en Cloud Run con allowlist de destinos. Precedente de "servicio intermedio chico, con allowlist estricta y o11y propia".                                                                                                                                                                                |

Y una diferencia de escala clave:

|              | Uber                                        | PhoneCentral                                                                     |
| ------------ | ------------------------------------------- | --------------------------------------------------------------------------- |
| Backends     | Miles de microservicios                     | Pocos monolitos grandes (UV, FST, UC) + servicios Cloud Run                 |
| Contratos    | IDL (Protobuf/Thrift) en todos lados        | `@public_api` tipado; las `/api/*` internas son *view models* sin versionar |
| Consecuencia | Autogenerar tools desde IDL rinde muchísimo | Autogenerar rinde menos y es más riesgoso                                   |

El README de `phonecentral-user-mcp` da un buen ejemplo del riesgo: `/api/voicerecording` **tiene** un check de
acceso, pero es de alcance company-wide y permite el acceso por defecto si la grabación no tiene llamada
asociada. Exponer endpoints automáticamente, sin leer el handler, sería peligroso.

Otro detalle: el docstring de `call.list`
([call.py:852-862](../phonevoice/frontend/apis/endpoints/call.py#L852-L862)) dice que las API keys de empresa y
los admins ven todas las llamadas de la empresa, y que **las API keys de usuario ven solo las propias**. La
API v2 **ya cambia el alcance según la credencial**, así que elegir con qué credencial llama el gateway es una
decisión de seguridad.

### 4.2 Equivalencias Uber → PhoneCentral

| Uber                         | Para qué                          | Equivalente natural en PhoneCentral                                                     |
| ---------------------------- | --------------------------------- | ---------------------------------------------------------------------------------- |
| MCP Registry                 | Catálogo, ownership, habilitación | YAML en el repo + CODEOWNERS (o Datastore si hace falta UI)                        |
| Proxy Gateway                | Data plane                        | Servicio en Cloud Run (`mcp-gateway`)                                              |
| AutoCrawler (Cadence + cron) | Descubrir APIs                    | Cloud Scheduler / Cloud Tasks que lee `@public_api` (`ApiDocSet`)                  |
| Muttley (service mesh)       | Llamadas service-to-service       | Google identity tokens + Cloud Run IAM (lo que ya se usa)                          |
| Access Control System        | AuthZ por tool                    | Grupos de Google + el registry                                                     |
| Redacción de PII             | Filtrar respuestas                | Reglas por tool en el gateway (¿clasificación de Relyance? hay un `relyance.yaml`) |
| Omni MCP                     | Descubrimiento incremental        | Un endpoint `catalog` en el gateway                                                |
| `aifx` (Code Mode)           | CLI para agentes de código        | Un CLI `dp-mcp`                                                                    |

---

### Alternativa A: "Kit estándar" (sin gateway)

No se construye un gateway. Se ordena lo que hay:

- **Una sola forma por sistema**: elegir un camino para Jira (MCP o CLI) y retirar el otro de las skills.
- **Versiones fijas**: nada de `npx ...@latest`; las versiones se fijan en el plugin `phonecentral-tools`.
- **Servers MCP internos por dominio**, cada uno en Cloud Run y mantenido por su equipo dueño:
  `datastore-readonly-mcp`, un MCP de llamadas de UV (en lugar de CSR por scraping), etc.

```
 LAPTOP                                   │  GCP (PhoneCentral)                │ TERCEROS
 Claude Code                              │                               │
  ├─ client ─────────────────────────────┼───────────────────────────────┼─► Atlassian MCP
  ├─ client ─────────────────────────────┼───────────────────────────────┼─► PagerDuty MCP
  ├─ client ─────────────────────────────┼─► datastore-readonly-mcp      │
  ├─ client ─────────────────────────────┼─► uv-calls-mcp                │
  └─ client ─────────────────────────────┼─► (cada equipo el suyo...)    │
```

| Pros                                 | Contras                                                                                     |
| ------------------------------------ | ------------------------------------------------------------------------------------------- |
| Barato e incremental; arranca mañana | Sigue sin haber un punto común: authZ, auditoría y redacción las implementa **cada** server |
| Sin nuevo punto único de falla       | Las credenciales siguen siendo personales y viven en cada laptop                            |
| Elimina el scraping y el curl a mano | N servers internos = N servicios que operar                                                 |

**Qué problemas resuelve A**

| #   | Problema                              | ¿A lo resuelve? | Por qué                                                                                                    |
| --- | ------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------- |
| P1  | Setup frágil por laptop               | Parcial         | Versiones fijas y un camino por sistema, pero sigue habiendo N servers y N tokens por laptop               |
| P2  | Agente con todos los permisos humanos | Parcial         | Los servers internos nuevos pueden ser de solo lectura; Jira, PagerDuty, etc. siguen con tu token completo |
| P3  | Cero auditoría y métricas             | No              | Cada server loguea (o no) a su manera                                                                      |
| P4  | PII cruda al modelo                   | No              | Cada server tendría que implementar su propia redacción                                                    |
| P5  | Muchos caminos al mismo sistema       | Sí              | Es justamente lo que ordena                                                                                |
| P6  | Sistemas internos sin tools           | Parcial         | Se crean algunos servers internos, a mano y equipo por equipo                                              |
| P7  | Difícil descubrir; contexto inflado   | No              | Más servers = más tools cargadas en cada sesión                                                            |

---

### Alternativa B: "Gateway de agregación" (registry manual)

#### B.1 ¿Qué es el `mcp-gateway`?

**Un server MCP implementado por PhoneCentral que hace de pasamanos dinámico, guiado por una configuración propia
(custom) en YAML.**

Lo particular es que **juega dos roles a la vez**:

```
                          ┌──────────────── mcp-gateway ────────────────────┐
  Claude Code ──MCP──►    │  ROL 1: MCP SERVER           ROL 2: MCP CLIENT  │  ──MCP──► Atlassian MCP
  (client)                │  (de cara a los agentes)     (de cara a otros   │  ──MCP──► PagerDuty MCP
                          │                               servers)          │
                          │                              + cliente HTTP     │  ──HTTP─► APIs internas (UV)
                          │                              + código propio    │  ──API──► Datastore
                          └─────────────────────────────────────────────────┘
```

- **Hacia Claude Code** es un **server**: Claude Code se conecta a él igual que hoy se conecta a Atlassian.
- **Hacia Atlassian** es un **client**: el gateway se conecta al server de Atlassian igual que hoy lo hace
  Claude Code.

Detrás del gateway puede haber **tres tipos** de tools:

| Tipo                                 | Qué hace el gateway                                        | Ejemplo                                                               |
| ------------------------------------ | ---------------------------------------------------------- | --------------------------------------------------------------------- |
| **Proxy a un MCP externo**           | Reenvía la llamada a otro server MCP                       | `getJiraIssue` → Atlassian MCP                                        |
| **Mapeo a un endpoint HTTP interno** | Traduce la llamada a un request HTTP, solo con config YAML | `uv.get_call_info` → `GET /api/v2/call/{id}`                          |
| **Tool nativa**                      | Código Python escrito dentro del gateway                   | `datastore_get_entity` (lee Datastore con una cuenta de solo lectura) |

#### B.2 Control plane vs. data plane

Son nombres que vienen del mundo de redes. **Analogía con un aeropuerto:**

- **Control plane = la oficina de planificación.** Decide qué vuelos existen, a qué destinos y quién puede
  abordar cada uno. Cambia poco y despacio, y con aprobaciones.
- **Data plane = la pista y las puertas de embarque.** Atiende cada pasajero y cada vuelo en tiempo real,
  aplicando las reglas que decidió la oficina. Tiene que ser rápido y no puede caerse.

En el gateway:

|                  | Control plane                                                           | Data plane                                                                                  |
| ---------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| **Qué es**       | Dónde se **define** qué tools existen y sus reglas                      | El código que **atiende** cada llamada de un agente                                         |
| **En B**         | Los YAML del registry en el repo + el proceso que los carga             | El servicio que recibe `tools/call`, chequea, reenvía y responde                            |
| **Cuándo actúa** | Cuando un equipo agrega o cambia una tool (por PR)                      | En cada request, en milisegundos                                                            |
| **Ejemplo**      | "Public APIs habilita `uv.get_call_info`, solo lectura, para `eng-all`" | "Juan llama a `uv.get_call_info`: ¿está habilitada? ¿Juan está en `eng-all`? Sí → reenviar" |

Separarlos sirve para que **cambiar una regla no requiera un deploy del servicio**: el data plane relee la
config cada tanto.

#### B.3 Un único endpoint "catálogo" (el "Omni" de Uber)

**"Omni" es solo el nombre que le puso Uber** (del latín *omnis*, "todo"): **un único endpoint MCP que da
acceso a todos los servers** detrás del gateway, mediante tools de descubrimiento. Es el "mozo" de Atlassian
(sección 0.7), pero para todo PhoneCentral. Acá lo llamamos **`catalog`**.

Hay dos formas de exponer el gateway:

| Opción                          | URL que configura el dev                         | Qué ve Claude al arrancar                            |
| ------------------------------- | ------------------------------------------------ | ---------------------------------------------------- |
| Un endpoint por server          | `/atlassian/mcp`, `/uv/mcp`, `/datastore/mcp`... | Todas las tools de todos los servers (vuelve P7)     |
| **Un endpoint único `catalog`** | `/catalog/mcp`                                   | Solo 5 meta-tools; el resto se descubre bajo demanda |

**En B se elige el endpoint único.** Expone estas meta-tools:

| Meta-tool                                | Qué hace                                                                      |
| ---------------------------------------- | ----------------------------------------------------------------------------- |
| `search_tools(query)`                    | Busca tools por intención, sobre nombres y descripciones de todos los servers |
| `get_tool_schema(server, tool)`          | Devuelve la descripción completa y el JSON Schema                             |
| `invoke_read(server, tool, args)`        | Ejecuta una tool de riesgo `read`                                             |
| `invoke_write(server, tool, args)`       | Ejecuta una tool de riesgo `write`                                            |
| `invoke_destructive(server, tool, args)` | Ejecuta una tool de riesgo `destructive`                                      |

¿Por qué tres `invoke` y no uno? Por lo mismo que en Atlassian (sección 0.7): con un solo `invoke`, Claude Code
no podría tener permisos distintos para leer y para borrar. **Además**, el gateway verifica que el riesgo
declarado coincida con el del registry: si alguien llama `invoke_read` sobre una tool `destructive`, la rechaza.

#### B.4 ¿Con qué credencial se llama a cada sistema?

**Regla:** si al sistema de fondo le importa quién sos, se usa tu identidad; si no, una credencial de servicio
con permisos mínimos.

| Destino                         | Credencial que usa el gateway                                      | Por qué                                                                                                                                     |
| ------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Atlassian (Jira/Confluence)** | **El token de Juan**, guardado por el gateway                      | Jira tiene permisos por proyecto; el agente no debe ver más que Juan. El audit de Jira sigue diciendo "Juan"                                |
| **GitHub**                      | El token de Juan, igual que Atlassian                              | Permisos por repo; el PR tiene que quedar a nombre de Juan                                                                                  |
| **PagerDuty**                   | El token de Juan, o una cuenta de servicio de solo lectura         | Depende de si se habilitan escrituras                                                                                                       |
| **Datastore**                   | **Cuenta de servicio de solo lectura**                             | Hoy se usa el `gcloud` de Juan, que puede escribir. Una cuenta de solo lectura hace que escribir sea **imposible**, no solo "desaconsejado" |
| **UV (API v2)**                 | Credencial interna de solo lectura (`support_readonly`, a definir) | La API v2 cambia el alcance según la credencial; para soporte cross-empresa hace falta una dedicada y acotada                               |

¿Cómo consigue el gateway **el token de Juan para Atlassian** sin que Juan se lo pase a mano? Con un **vault
de tokens**:

1. La primera vez que Juan usa una tool de Atlassian, el gateway responde: *"Falta conectar Atlassian: abrí
   este link"*.
2. Juan hace el OAuth de Atlassian **una vez**, pero ahora el que recibe el token es el **gateway**, no la
   laptop.
3. El gateway lo guarda cifrado (Secret Manager o Datastore cifrado), asociado a `juan@phonecentral.com`.
4. En cada llamada futura: *"es Juan → busco su token de Atlassian → lo uso"*.

Es lo que Uber llama **token exchange**: el agente se autentica una sola vez contra el gateway, y el gateway
"cambia" esa identidad por la credencial de cada proveedor.

> **A verificar:** si Atlassian permite que un servicio propio (el gateway) se registre como cliente OAuth de
> su MCP server. Si no, el gateway puede llamar directo a la API REST de Jira con el mismo token.

#### B.5 Secuencia completa de punta a punta

Juan pregunta: **"¿De qué trata DP-200001 y qué pasó con la llamada del ticket?"**

```
 LAPTOP DE JUAN       │  GCP (PhoneCentral)                                          │ DESTINOS
                      │  ┌──────────────── mcp-gateway ─────────────────────┐   │
 Claude Code          │  │ CONTROL PLANE: registry (YAML) + catálogo         │   │
  └─ client ──HTTP────┼─►│ DATA PLANE: authN → authZ → ruteo → redacción     │───┼─► Atlassian MCP
                      │  │             → audit log                           │───┼─► UV (API v2)
                      │  │ VAULT: tokens por usuario (Atlassian, GitHub)     │   │
                      │  └───────────────────────────────────────────────────┘   │
                      │           └─► Observe / BigQuery (auditoría)             │
```

##### Fase 0: el gateway arranca (antes de que exista Juan)

**Paso 0.1. Leer el registry.** El gateway carga los YAML:

```yaml
# registry/atlassian.yaml
server: atlassian
type: mcp_proxy                       # tipo 1: proxy a MCP externo
upstream: https://mcp.atlassian.com/v2/mcp
credential: user_oauth                # usa el token de cada usuario (vault)
owner: "@phonecentral/dev-productivity"
tools:
  getJiraIssue:      { enabled: true,  risk: read }
  createJiraIssue:   { enabled: true,  risk: write }
  deleteJiraIssue:   { enabled: false, risk: destructive }
```

```yaml
# registry/uv.yaml   ← escrito A MANO por el equipo dueño (en B no hay crawler)
server: uv
type: http_mapping                    # tipo 2: mapeo a endpoint interno
credential: support_readonly          # credencial interna de solo lectura (a definir)
owner: "@phonecentral/public-apis"
tools:
  get_call_info:
    enabled: true
    risk: read
    allowed_groups: [eng-all]
    http: { method: GET, url: "https://<uv-interno>/api/v2/call/{call_id}" }
    redact: [external_number, contact.phone, contact.email]
    description: >
      Devuelve el detalle de UNA llamada UV ya terminada: dirección, duración, si fue
      transferida o grabada, CSAT y transcripción. No sirve para llamadas en curso.
    input_schema: { type: object, properties: { call_id: { type: string } }, required: [call_id] }
```

**Paso 0.2. Armar el catálogo.**

- Para `uv`, las tools están escritas completas en el YAML.
- Para `atlassian`, el YAML solo dice cuáles habilitar. El gateway, **actuando como client**, hace
  `initialize` y `tools/list` contra Atlassian y obtiene sus descripciones y schemas.
- Combina todo en un **catálogo en memoria** con solo las tools `enabled: true`.

Cada pocos minutos repite esto, y así un cambio en el YAML (mergeado por PR) entra sin deploy.

##### Fase A: Juan abre Claude Code

**Paso A.1. Config.** [.mcp.json](../.mcp.json) tiene una sola entrada:

```json
{ "mcpServers": { "phonecentral": { "type": "http", "url": "https://mcp-gateway.<interno>/catalog/mcp" } } }
```

**Paso A.2. Login.** La primera vez, Claude Code abre el browser y Juan se loguea con **Google SSO** (MCP
soporta OAuth). El gateway ahora sabe: "este client es `juan@phonecentral.com`".

**Paso A.3. Handshake + `tools/list`.**

```json
→ {"method": "tools/list"}
← {"result": {"tools": [
     {"name": "search_tools",       "description": "Busca tools de PhoneCentral por intención...", ...},
     {"name": "get_tool_schema",    ...},
     {"name": "invoke_read",        ...},
     {"name": "invoke_write",       ...},
     {"name": "invoke_destructive", ...}
  ]}}
```

**Claude ve 5 tools, no 200.** Claude Code las registra como `mcp__phonecentral__search_tools`, etc. Como son pocas,
ni siquiera hace falta el modo deferred.

##### Fase B: Juan hace la pregunta

**Paso B.1. Buscar.** El modelo no conoce ninguna tool de Jira, así que busca:

```json
{"name": "mcp__phonecentral__search_tools", "input": {"query": "leer un ticket de Jira"}}
```

El gateway busca en su catálogo y **solo devuelve tools que Juan tiene permitidas**:

```json
[{"server": "atlassian", "tool": "getJiraIssue", "risk": "read",
  "summary": "Get a Jira issue by key..."}]
```

**Paso B.2. Pedir el schema.**

```json
{"name": "mcp__phonecentral__get_tool_schema", "input": {"server": "atlassian", "tool": "getJiraIssue"}}
```

→ descripción completa + JSON Schema (`cloudId`, `issueIdOrKey`).

**Paso B.3. Invocar.**

```json
{"name": "mcp__phonecentral__invoke_read",
 "input": {"server": "atlassian", "tool": "getJiraIssue",
           "args": {"cloudId": "...", "issueIdOrKey": "DP-200001"}}}
```

Claude Code chequea **sus** permisos: `invoke_read` está permitida siempre, así que no pregunta nada.

**Paso B.4. Lo que hace el gateway por dentro (data plane):**

| #   | Paso       | Detalle                                                                                                              |
| --- | ---------- | -------------------------------------------------------------------------------------------------------------------- |
| 1   | AuthN      | Token de Google válido → es `juan@phonecentral.com`, agente `claude-code`                                                 |
| 2   | AuthZ      | `atlassian.getJiraIssue` está habilitada, Juan puede usarla, y el riesgo es `read`, igual que el `invoke` usado → OK |
| 3   | Credencial | `credential: user_oauth` → busca en el vault el token de Atlassian de Juan                                           |
| 4   | Ruteo      | Como **MCP client**, manda `tools/call getJiraIssue` a Atlassian con el token de Juan                                |
| 5   | Atlassian  | Valida el token y responde **con los permisos de Juan en Jira**                                                      |
| 6   | Redacción  | Aplica las reglas (ej. enmascarar teléfonos o emails en el texto)                                                    |
| 7   | Recorte    | Si la respuesta es enorme (50 comentarios), la trunca según la config                                                |
| 8   | Auditoría  | Loguea: `juan · claude-code · atlassian.getJiraIssue · read · 230ms · 4KB · OK`                                      |
| 9   | Respuesta  | Devuelve el resultado a Claude Code                                                                                  |

**Paso B.5. Segunda tool: la llamada de UV.** El ticket menciona un `call_id`. El modelo repite el ciclo:

```
search_tools("detalle de una llamada de UV")    → uv.get_call_info (read)
get_tool_schema("uv", "get_call_info")          → {call_id: string}
invoke_read("uv", "get_call_info", {"call_id": "5012345678"})
```

Esta vez, en el gateway:

- `type: http_mapping` → arma `GET https://<uv-interno>/api/v2/call/5012345678`.
- `credential: support_readonly` → usa esa credencial, sin tocar el vault de Juan.
- `redact` → enmascara `external_number` y los datos del contacto antes de devolver:

```json
{"call_id": 5012345678, "direction": "inbound", "duration": 312.4,
 "is_transferred": true, "was_recorded": false, "csat_score": "2",
 "external_number": "+1•••••••89", "transcription_text": "..."}
```

Hoy, para obtener esto, el agente tendría que ir a CSR por scraping o con un curl armado a mano.

**Paso B.6. Respuesta final.** El modelo combina ambos resultados y responde a Juan.

**¿Y si el agente intenta borrar algo?** Llamaría `invoke_destructive("atlassian", "deleteJiraIssue", ...)`:

- Claude Code le pregunta a Juan (porque `invoke_destructive` no está pre-permitida).
- Aunque Juan diga que sí, el gateway la rechaza: `deleteJiraIssue` tiene `enabled: false`.
- El intento queda en el audit log.

#### B.6 Qué problemas resuelve B

| #   | Problema                              | ¿B lo resuelve? | Por qué                                                                                                                |
| --- | ------------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------- |
| P1  | Setup frágil por laptop               | Sí              | Una entrada en `.mcp.json` + SSO; los tokens viven en el vault del gateway                                             |
| P2  | Agente con todos los permisos humanos | Sí              | Permisos por tool y por riesgo en el registry; Datastore con cuenta de solo lectura. Límites **técnicos**, no de texto |
| P3  | Cero auditoría y métricas             | Sí              | Todas las llamadas pasan por un mismo punto que loguea quién, qué agente y qué tool                                    |
| P4  | PII cruda al modelo                   | Sí (parcial)    | Redacción configurable por tool; hay que definir y mantener qué campos son sensibles                                   |
| P5  | Muchos caminos al mismo sistema       | Sí              | Un único camino por sistema, el del registry                                                                           |
| P6  | Sistemas internos sin tools           | Parcial         | Agregar una tool interna pasa a ser un PR con YAML (tipo 2) o un handler chico (tipo 3), pero sigue siendo a mano      |
| P7  | Difícil descubrir; contexto inflado   | Sí              | 5 meta-tools + `search_tools` sobre todo el catálogo, para cualquier agente de cualquier repo                          |

| Pros                                                        | Contras                                                                               |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| Un único punto para authZ, auditoría, redacción y métricas  | Hay que construir y operar un servicio crítico (si se cae, se caen todos los agentes) |
| Setup de laptop: una entrada y SSO                          | Gestionar credenciales de terceros en el servidor (vault, token exchange)             |
| Sirve igual para Claude Code, bots y cron                   | Las tools internas se siguen escribiendo a mano                                       |
| El registry en YAML + PR reusa el flujo de review existente | Agrega un salto de red a cada llamada                                                 |

**Lo que B no resuelve** (y es lo que suma C): sigue requiriendo que alguien escriba cada tool interna.

---

### Alternativa C: "Gateway completo estilo Uber" (B + autogeneración)

#### C.1 Qué agrega C sobre B

C es **todo B, sin cambiar nada**, más tres piezas:

| Pieza nueva             | Problema que ataca                 | En una línea                                                                     |
| ----------------------- | ---------------------------------- | -------------------------------------------------------------------------------- |
| **Crawler**             | P6: tools internas escritas a mano | Un job que lee las APIs que ya existen y **propone** tools automáticamente       |
| **Response projection** | P7: contexto inflado               | El agente pide **solo los campos** que necesita y el gateway recorta el resto    |
| **Code Mode**           | P7: resultados enormes             | Un CLI para agentes de código: los resultados van **a archivos**, no al contexto |

```
 GCP (PhoneCentral) — mcp-gateway
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ CONTROL PLANE                                                            │
 │   ┌─────────────┐   abre PR    ┌────────────────────┐   carga            │
 │   │ CRAWLER     │ ───────────► │ registry YAML      │ ─────────► catálogo│
 │   │ (cron) [C]  │  (disabled)  │ (repo, CODEOWNERS) │                    │
 │   └─────────────┘              └────────────────────┘                    │
 │        ▲ lee                         ▲ el dueño revisa y habilita        │
 │        │                                                                 │
 │  APIs existentes (UV @public_api, @openapi_schema, MCPs propios)         │
 ├──────────────────────────────────────────────────────────────────────────┤
 │ DATA PLANE (igual que B)                                                 │
 │   authN → authZ → ruteo → redacción → PROJECTION [C] → audit log         │
 └──────────────────────────────────────────────────────────────────────────┘
        ▲ MCP (catalog/mcp)                 ▲ HTTP (mismo gateway)
        │                                   │
   Claude Code / bots                  CLI `dp-mcp` (CODE MODE) [C]
```

`[C]` marca lo nuevo respecto de B.

#### C.2 ¿De dónde saca tools el crawler?

En Uber, la fuente es el **IDL**: archivos Protobuf/Thrift que describen cada método de cada servicio (nombre,
parámetros con tipos, respuesta y comentario). Un IDL es un **contrato formal y legible por máquina**.

En PhoneCentral no hay IDL central, pero hay **tres fuentes** con algo parecido:

| Fuente                                                        | Cantidad aprox.          | Calidad como "IDL"                                                                                             | Notas                                                            |
| ------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| **`@public_api`** (API pública v2)                            | **~409 endpoints** en UV | **Alta**: params y respuesta tipados con pydantic, docstring y nombre estable. Ya genera OpenAPI (`ApiDocSet`) | El alcance depende de la credencial                              |
| **`@openapi_schema`** (handlers internos)                     | ~37 en UV                | Media: schemas marshmallow                                                                                     | Pocos, y muchos de login/OAuth: poco útiles para agentes         |
| **Servers MCP propios** en Cloud Run (ej. `phonecentral-user-mcp`) | Pocos hoy                | Alta: ya hablan MCP                                                                                            | Se detectan por un label en Cloud Run y se les hace `tools/list` |

Los endpoints internos `/api/*` sin schema **no son una fuente**: no hay nada legible por máquina para leer.

Así se ve un endpoint `@public_api`
([call.py:816-831](../phonevoice/frontend/apis/endpoints/call.py#L816-L831)), la materia prima ideal:

```python
@public_api('GET', 'call/{id}', name='call.get_call_info', ...)
def get_call_info(self, request: GET_CALL_INFO_PARAMS) -> call_protos.CallProto:
  """Call -- Get

  Get call status and detailed information for a concluded call, including direction,
  duration, recording URLs, CSAT scores, voicemail metadata, and transcription text...
  """
```

Ahí está **todo lo que necesita una tool**: método y path, nombre estable, schema de entrada
(`GET_CALL_INFO_PARAMS`), schema de salida (`CallProto`) y descripción.

#### C.3 El crawler, paso a paso

Es un job periódico (por ejemplo, semanal, con Cloud Scheduler) que:

1. **Lee** la definición OpenAPI que ya produce `ApiDocSet` y lista los servers MCP propios.
2. **Compara** contra el registry: ¿hay endpoints nuevos o schemas que cambiaron?
3. **Traduce** cada endpoint nuevo a una entrada de tool: el schema pydantic se convierte en el JSON Schema de MCP.
4. **Mejora la descripción con un LLM.** Un docstring pensado para humanos ("Call -- Get") no es lo ideal para
   un agente. El LLM la reescribe con cuándo usarla, qué devuelve y qué no.
5. **Clasifica el riesgo** por método HTTP: `GET` → `read`, `POST`/`PATCH` → `write`, `DELETE` → `destructive`.
6. **Abre un PR** en el repo con los YAML generados, **todo con `enabled: false`**, asignado por CODEOWNERS al
   equipo dueño.

El YAML generado se vería así (mismo server `uv` de B; en B `get_call_info` la escribió una persona, en C el
crawler propone `list_calls` y las otras ~400):

```yaml
# registry/uv/call.yaml   ← generado por el crawler
server: uv
type: http_mapping
generated_from: "@public_api call.list"            # trazabilidad
tools:
  list_calls:
    enabled: false                    # ← siempre arranca apagada
    risk: read                        # ← inferido por ser GET
    access_scope: TODO_OWNER          # ← OBLIGATORIO completarlo a mano
    credential: TODO_OWNER            # ← OBLIGATORIO completarlo a mano
    allowed_groups: []
    redact: []
    http: { method: GET, url: "https://<uv-interno>/api/v2/call" }
    description: >                    # ← reescrita por el LLM
      Lista llamadas YA TERMINADAS de un target (empresa, usuario, departamento...),
      de la más reciente a la más vieja, paginando con cursor. No incluye llamadas en curso.
    input_schema: { ... }             # ← traducido desde LIST_CALL_PARAMS
                                      #   (target_id, target_type, started_after, limit, cursor)
    output_schema: { ... }            # ← traducido desde CallCollection
```

**El equipo dueño revisa el PR y decide:**

- Si la descripción del LLM es correcta.
- **`access_scope`**: ¿la respuesta es de un usuario, de toda la empresa o de todo PhoneCentral? Es la misma
  pregunta que se hace `phonecentral-user-mcp` en su registry auditado, y **no se puede inferir automáticamente**.
- **`credential`**: con qué identidad llama el gateway (recordar que la API v2 cambia el alcance según la
  credencial).
- Qué grupos pueden usarla y qué campos se redactan.
- Si se habilita (`enabled: true`) o se deja apagada.

Cuando el PR se mergea, entra en el catálogo **igual que en B**. El data plane no distingue entre una tool
escrita a mano y una generada.

> Principio de Uber: **"descubrir no implica exponer"**. El crawler solo propone; habilitar siempre lo decide
> un humano.

#### C.4 Response projection

**Problema:** `get_call_info` devuelve un `CallProto` con decenas de campos (grabaciones, CSAT, transcripción
completa...). Si el agente solo quiere saber la duración, igual se come la transcripción entera.

**Solución:** el gateway le agrega a **cada** tool un parámetro opcional `fields` y recorta la respuesta antes
de devolverla.

```json
// Sin projection: vuelve todo (~15 KB, transcripción incluida)
invoke_read("uv", "get_call_info", {"call_id": "5012345678"})

// Con projection: vuelve solo esto (~100 bytes)
invoke_read("uv", "get_call_info",
            {"call_id": "5012345678", "fields": ["direction", "duration", "csat_score"]})
← {"direction": "inbound", "duration": 312.4, "csat_score": "2"}
```

Es la idea de GraphQL ("pedí solo lo que necesitás") aplicada a cualquier API. El backend no cambia: **el
recorte lo hace el gateway**. Para que el modelo sepa qué campos pedir, `get_tool_schema` le muestra el
`output_schema`.

#### C.5 Code Mode

##### El problema que resuelve

Para preguntas como *"de las 300 llamadas de hoy de esta empresa, ¿en cuántas el cliente menciona X?"*, en
modo MCP **cada resultado de tool entra entero al contexto del modelo** (sección 0.5, paso 12). Con 300
transcripciones, el contexto se llena y el modelo termina "contando a ojo".

##### Qué es

Un **CLI, `dp-mcp`, que el agente ejecuta con la tool `Bash`**, igual que hoy ejecuta `jira`, `gh` u
`observe`. La diferencia con el modo MCP es **dónde termina el resultado**:

```
 MODO MCP                                          CODE MODE
 ────────                                          ─────────
 modelo ─ tool_use: invoke_read(...) ─►            modelo ─ tool_use: Bash("dp-mcp read ... > /tmp/x.json") ─►
          Claude Code → MCP client → gateway                Claude Code → shell → dp-mcp → gateway
 modelo ◄─ tool_result: EL JSON COMPLETO ──        modelo ◄─ tool_result: "" (nada; quedó en /tmp/x.json)

                                                   modelo ─ Bash("jq '...' /tmp/x.json | wc -l") ─►
                                                   modelo ◄─ tool_result: "6"   ← solo lo que pidió
```

Los datos pasan **por la laptop**, pero **no por el modelo**: el agente los procesa con `jq`, `grep` o
Python, y solo lee el resumen.

##### ¿El modo MCP y el Code Mode son excluyentes?

**No, conviven.** Son dos "puertas" al **mismo gateway**, con las mismas reglas:

```
                        ┌──────────── mcp-gateway ────────────┐
 Claude Code ──MCP─────►│ /catalog/mcp                        │
 Claude Code ──Bash─►   │   authN → authZ → ruteo → redacción │──► Atlassian, UV, Datastore...
   dp-mcp ─────MCP─────►│   → projection → audit log          │
 Glean, bots, ──MCP────►│                                     │
 agentes de producto    └─────────────────────────────────────┘
```

| Agente                                         | ¿Tiene shell? | Qué puede usar                  |
| ---------------------------------------------- | ------------- | ------------------------------- |
| Claude Code (VS Code o CLI)                    | Sí            | **Ambos**; elige según la tarea |
| Bot de on-call / `pr-reviewer` con Claude Code | Sí            | Ambos                           |
| Glean, bots de Slack, agentes de producto      | No            | Solo modo MCP                   |

Dentro de una misma sesión de Claude Code, el agente puede leer un ticket por MCP (chico, una llamada) y
después bajar 300 llamadas por Code Mode (grande, muchos pasos).

##### ¿Cuál sería el default en Claude Code?

**Code Mode como default para Claude Code** (como hizo Uber), y modo MCP para lookups puntuales o para agentes
sin shell. Por qué:

- Claude Code **ya trabaja así hoy**: `jira`, `gh`, `observe` y `sentry` son CLIs por `Bash`. `dp-mcp` los
  reemplaza a todos por uno solo.
- Permite **encadenar** pasos (paginar, filtrar, cruzar) en un script, en vez de una vuelta al modelo por paso.
- Los datos grandes **no tocan el contexto**: menos costo, menos PII en el modelo.

El costo: en modo MCP, Claude Code puede pedir permiso **por tool** (`invoke_read` sí, `invoke_destructive`
preguntar). Con un CLI, los permisos de Claude Code son **por patrón de comando de `Bash`**. Por eso el CLI
separa el riesgo en **subcomandos distintos** (ver abajo), y así se puede configurar en `.claude/settings.json`:

```json
{ "permissions": {
    "allow": ["Bash(dp-mcp search:*)", "Bash(dp-mcp schema:*)", "Bash(dp-mcp read:*)"],
    "ask":   ["Bash(dp-mcp write:*)", "Bash(dp-mcp destructive:*)"] } }
```

Igual, **la regla de verdad la aplica el gateway**: aunque el permiso local falle, una tool deshabilitada o no
permitida se rechaza en el servidor.

##### ¿Cómo sabe el agente que `dp-mcp` existe?

Un CLI **no se descubre por protocolo**: no hay ningún `tools/list` para "programas instalados". Hay **dos
niveles** de descubrimiento:

| Nivel | Pregunta                          | Cómo se resuelve                                                               | ¿Estático o dinámico?    |
| ----- | --------------------------------- | ------------------------------------------------------------------------------ | ------------------------ |
| 1     | ¿Existe `dp-mcp` y cuándo usarlo? | Una **skill** (SKILL.md) en el plugin `phonecentral-tools` + una línea en CLAUDE.md | Estático (texto)         |
| 2     | ¿Qué tools hay detrás?            | `dp-mcp search "..."` le pregunta **al gateway**                               | Dinámico (catálogo vivo) |

Cuando el gateway agrega 50 tools nuevas, **la skill no cambia**: el nivel 2 las encuentra solo.

##### Cómo llega la skill al agente

Las skills se cargan con el mismo truco que las tools *deferred* (sección 0.6):

1. **Al arrancar la sesión**, Claude Code le pasa al modelo solo el **nombre y la `description`** de cada skill
   disponible (una línea cada una).
2. **Cuando la tarea coincide** con esa descripción, el modelo invoca la skill y **recién ahí** recibe el
   cuerpo completo del SKILL.md.

Por eso **la `description` es lo más importante**: tiene que hacer que el modelo la cargue *antes* de usar
cualquiera de las dos puertas. Si no la carga, el modelo ve las tools `mcp__phonecentral__*` y las usa para todo,
incluso para lo que debería ir por Code Mode.

Como refuerzo, una línea en [CLAUDE.md](../CLAUDE.md) (que **sí** se carga siempre, entera):

```markdown
- **PhoneCentral systems (Jira, Confluence, UV, Datastore, PagerDuty...)**: load the `/phonecentral:dp-mcp` skill
  before any call to `mcp__phonecentral__*` or `dp-mcp`. It decides which of the two to use.
```

##### Ejemplo de la skill completa

Escrita en castellano para este documento; la real iría en inglés, como el resto de las skills del repo.

````markdown
---
name: dp-mcp
description: Acceso a sistemas de PhoneCentral (Jira, Confluence, GitHub, PagerDuty, UV, Datastore...) a través
  del MCP gateway, por las tools `mcp__phonecentral__*` o por el CLI `dp-mcp`. Cargar ANTES de consultar o
  modificar cualquiera de esos sistemas; define cuál de las dos vías usar. Reemplaza a los CLIs
  individuales (jira, gh, observe, sentry) y a los curl a mano.
---

# Sistemas de PhoneCentral vía el MCP gateway

Hay dos vías al mismo gateway, con los mismos permisos, redacción y auditoría:

- **Modo MCP**: las tools `mcp__phonecentral__search_tools`, `get_tool_schema` e `invoke_read|write|destructive`.
  El resultado entra entero a tu contexto.
- **Code Mode**: el CLI `dp-mcp` por Bash. El resultado va a stdout y lo podés redirigir a un archivo y
  procesarlo con `jq`/`grep`/Python sin leerlo entero.

## Cuál usar

Regla general: **si necesitás leer el resultado completo para razonar, modo MCP. Si vas a filtrar, contar,
cruzar o buscar dentro del resultado, Code Mode.**

| Situación                                                                   | Vía                       |
| --------------------------------------------------------------------------- | ------------------------- |
| 1 a 3 llamadas con respuesta chica (un ticket, una llamada, una entidad)    | MCP                       |
| Leer algo para entenderlo (descripción de un bug, una página de Confluence) | MCP                       |
| Listados con paginación (`cursor`)                                          | Code Mode                 |
| Más de 3 llamadas, o llamadas en loop                                       | Code Mode                 |
| Contar, agrupar, promediar o filtrar resultados                             | Code Mode                 |
| Textos largos: transcripciones, logs, historiales                           | Code Mode                 |
| Cruzar resultados de dos tools (ids de una como input de otra)              | Code Mode                 |
| Guardar evidencia para el usuario (archivo con los datos crudos)            | Code Mode                 |
| Una escritura puntual (comentar un ticket, abrir un PR)                     | Cualquiera; nunca en loop |

Si empezaste por MCP y la respuesta resultó enorme o paginada, **cambiá a Code Mode** para el resto. No
pidas más páginas por MCP.

## Flujo

1. **Buscar** la tool por intención. Nunca adivines nombres de tools o servers.
   - MCP: `search_tools({"query": "..."})`
   - CLI: `dp-mcp search "..."`
2. **Ver el schema** antes de llamar: parámetros obligatorios y campos de salida.
   - MCP: `get_tool_schema` · CLI: `dp-mcp schema <server> <tool>`
3. **Ejecutar** con el subcomando del riesgo que indica el schema (`read`, `write` o `destructive`).
   - Pedí siempre `fields` con solo los campos que necesitás.
   - CLI: `dp-mcp read <server> <tool> '<json>' > /tmp/<nombre>.json`

## Reglas de Code Mode

- Redirigí a `/tmp/` todo resultado que pueda pasar de unas 50 líneas.
- **No hagas `cat` de esos archivos.** Usá `jq`, `grep -c`, `wc -l` o `head` para leer solo lo necesario.
- Para paginar, loopeá sobre `cursor` en un solo comando de Bash.
- Al terminar, decile al usuario qué archivos quedaron en `/tmp/` por si quiere revisarlos.

## Escrituras

- Usá `write` o `destructive` solo si el usuario lo pidió explícitamente.
- Una escritura por vez; **nunca dentro de un loop** sin confirmar con el usuario.
- Antes de un `destructive`, mostrale al usuario el server, la tool y los argumentos exactos.

## Errores

| Respuesta del gateway         | Qué hacer                                                                               |
| ----------------------------- | --------------------------------------------------------------------------------------- |
| `not_authenticated`           | Pedirle al usuario que corra `dp-mcp login` (o que reconecte el server MCP `phonecentral`)   |
| `needs_connection: atlassian` | Pasarle al usuario el link que viene en la respuesta para conectar su cuenta (vault)    |
| `forbidden`                   | No reintentar ni buscar otra vía: el usuario no tiene permiso para esa tool             |
| `tool_disabled`               | La tool existe pero el equipo dueño no la habilitó; decírselo al usuario                |
| `risk_mismatch`               | Usaste `read` para una tool `write` (o al revés); reintentar con el subcomando correcto |
````

Fijate cómo la skill **no menciona ninguna tool concreta** (`list_calls`, `getJiraIssue`...): solo explica
las dos vías, cuándo usar cada una y las reglas. Las tools concretas las encuentra `search`.

##### ¿`dp-mcp` llama al mismo MCP server?

**Sí.** `dp-mcp` es, por dentro, **un MCP client más**, igual que Claude Code. Se conecta al mismo
`/catalog/mcp` y llama a las mismas 5 meta-tools. No hay una segunda API.

```
 LAPTOP                                              │ GCP
 Claude Code ─ Bash ─► proceso dp-mcp                │
                        └─ MCP client (HTTP) ────────┼──► mcp-gateway /catalog/mcp
                           tools/call invoke_read    │      (mismas reglas que el modo MCP)
                        ◄─ resultado ────────────────┼───
                        └─ lo imprime en stdout → el shell lo redirige a /tmp/x.json
```

Ventaja: **una sola implementación** de authN, authZ, redacción, projection y auditoría. Code Mode es solo
otra forma de llegar.

##### ¿Cómo se programan los comandos de `dp-mcp`?

Lo importante: **no hay un comando por tool**. El CLI es **genérico** y tiene un puñado de subcomandos fijos,
cada uno mapeado 1 a 1 a una meta-tool del gateway:

| Subcomando                                    | Meta-tool del gateway                           |
| --------------------------------------------- | ----------------------------------------------- |
| `dp-mcp login`                                | — (obtiene y guarda el token de SSO localmente) |
| `dp-mcp search "<query>"`                     | `search_tools`                                  |
| `dp-mcp schema <server> <tool>`               | `get_tool_schema`                               |
| `dp-mcp read <server> <tool> '<json>'`        | `invoke_read`                                   |
| `dp-mcp write <server> <tool> '<json>'`       | `invoke_write`                                  |
| `dp-mcp destructive <server> <tool> '<json>'` | `invoke_destructive`                            |

Se escribe **una vez** (Python, unas pocas centenas de líneas) y **no se toca** cuando aparecen tools nuevas:
`uv list_calls` no es un comando, son **argumentos** que el CLI reenvía al gateway.

Boceto de cómo sería por dentro (con el SDK oficial de MCP para Python):

```python
# dp_mcp/cli.py — boceto
import asyncio, json, click
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from dp_mcp import auth

GATEWAY_URL = 'https://mcp-gateway.<interno>/catalog/mcp'


async def _call_meta_tool(name: str, arguments: dict) -> str:
  headers = {'Authorization': f'Bearer {auth.load_token()}'}   # guardado por `dp-mcp login`
  async with streamablehttp_client(GATEWAY_URL, headers=headers) as (read, write, _):
    async with ClientSession(read, write) as session:
      await session.initialize()                                 # handshake MCP
      result = await session.call_tool(name, arguments)          # tools/call
      return result.content[0].text


@click.group()
def cli():
  pass


@cli.command()
@click.argument('query')
def search(query):
  print(asyncio.run(_call_meta_tool('search_tools', {'query': query})))


def _invoke_command(risk):
  @click.argument('server')
  @click.argument('tool')
  @click.argument('args', default='{}')
  def command(server, tool, args):
    payload = {'server': server, 'tool': tool, 'args': json.loads(args)}
    print(asyncio.run(_call_meta_tool(f'invoke_{risk}', payload)))
  return command


for _risk in ('read', 'write', 'destructive'):
  cli.command(name=_risk)(_invoke_command(_risk))
```

Se distribuye como cualquier otra herramienta interna (por ejemplo, un paquete instalable desde el plugin
`phonecentral-tools`), junto con su skill.

##### Resumen: modo MCP vs. Code Mode

|                          | Modo MCP (`catalog/mcp`)                                         | Code Mode (`dp-mcp`)                                  |
| ------------------------ | ---------------------------------------------------------------- | ----------------------------------------------------- |
| Cómo lo invoca el agente | Tools `mcp__phonecentral__*`                                          | `Bash("dp-mcp ...")`                                  |
| Lo usa                   | Cualquier agente (Claude Code, bots, Glean, agentes de producto) | Agentes con shell (Claude Code)                       |
| Cómo lo descubre         | `tools/list` al conectar                                         | Una skill + `dp-mcp search`                           |
| Resultado                | Entra al contexto del modelo                                     | Va a stdout/archivo; el modelo lee solo lo que quiere |
| Permisos en Claude Code  | Por tool (`invoke_read`, ...)                                    | Por patrón de comando (`dp-mcp read:*`, ...)          |
| Ideal para               | Pocas llamadas, respuestas chicas                                | Muchas llamadas, datos grandes, encadenar pasos       |
| Backend                  | Gateway                                                          | **El mismo** gateway, por MCP                         |

#### C.6 Secuencia completa de punta a punta

Juan está de on-call y pregunta: **"De las llamadas de hoy de ACME con CSAT ≤ 2, ¿cuántas fueron transferidas
y en cuántas el cliente menciona 'cancelar'?"**

¿Por qué conviene Code Mode? Porque hay que **paginar** `list_calls` y leer **transcripciones**, que son textos
largos. Por MCP, todo eso entraría al contexto.

```
 LAPTOP DE JUAN         │  GCP (PhoneCentral) — mcp-gateway                                  │ DESTINOS
                        │ ┌──────────────────────────────────────────────────────────┐  │
 Claude Code            │ │ CONTROL PLANE: crawler → registry YAML → catálogo        │  │
  ├─ client MCP ────────┼►│ DATA PLANE: authN → authZ → ruteo → redacción            │──┼─► UV (API v2)
  └─ Bash: dp-mcp ──────┼►│             → projection → audit log                     │  │
     └─► /tmp/*.json    │ │ VAULT: tokens por usuario                                │  │
                        │ └──────────────────────────────────────────────────────────┘  │
                        │        └─► Observe / BigQuery (auditoría)                     │
```

##### Fase −1: el crawler (días antes, una vez)

1. El lunes corre el crawler. Detecta que `call.list` (de `@public_api`) no está en el registry.
2. Genera `registry/uv/call.yaml` con `list_calls` en `enabled: false` y la descripción reescrita por el LLM.
3. Abre el PR *"mcp-registry: tools nuevas para uv (deshabilitadas)"*, asignado por CODEOWNERS a
   `@phonecentral/public-apis`.
4. El equipo revisa y completa:
   - `access_scope: company` (devuelve datos de toda la empresa consultada).
   - `credential: support_readonly` (credencial interna de solo lectura, a definir; ver C.7).
   - `allowed_groups: [eng-oncall]` (solo on-call, por el alcance amplio).
   - `redact: [external_number, contact.phone, contact.email]`.
   - `enabled: true`.
5. Mergean. En minutos el gateway la incorpora al catálogo, sin deploy.

##### Fase 0 y Fase A: igual que en B

El gateway arma el catálogo; Claude Code conecta a `catalog/mcp` con SSO y recibe **las mismas 5 meta-tools**.

**Este es el punto clave de C:** aunque el catálogo pase de 30 a 400 tools, Claude ve siempre 5. El
crecimiento no le cuesta contexto.

##### Fase B: la pregunta, en Code Mode

El modelo ve que hay que paginar y leer transcripciones, y elige Code Mode (la skill de on-call se lo indica
para consultas grandes).

**Paso B.1. Buscar y ver schemas.**

```bash
dp-mcp search "listar llamadas de una empresa por fecha"
#  uv.list_calls      read   "Lista llamadas terminadas de un target (empresa, usuario...)..."
#  uv.get_call_info   read   "Devuelve el detalle de UNA llamada UV ya terminada..."
dp-mcp schema uv list_calls        # params + output_schema → sabe qué fields pedir
```

El gateway solo devuelve `uv.list_calls` porque **Juan está en `eng-oncall`**. A Ana, que no está, ni le
aparecería.

**Paso B.2. Traer las llamadas de hoy, paginando, con projection.**

```bash
cursor=""
while :; do
  dp-mcp read uv list_calls "{\"target_type\":\"company\",\"target_id\":\"<id ACME>\",
    \"started_after\":1792108800000,\"limit\":100,\"cursor\":\"$cursor\",
    \"fields\":[\"items.call_id\",\"items.csat_score\",\"items.is_transferred\",\"cursor\"]}" \
    > /tmp/page.json
  jq '.items[]' /tmp/page.json >> /tmp/calls.jsonl
  cursor=$(jq -r '.cursor // empty' /tmp/page.json); [ -z "$cursor" ] && break
done
```

Cada página pasa por authN → authZ (`eng-oncall`) → `support_readonly` → `GET /api/v2/call` →
**projection** (de cada llamada quedan 3 campos) → audit log.

**Paso B.3. Filtrar y contar transferidas, localmente.**

```bash
jq -c 'select((.csat_score|tonumber) <= 2)' /tmp/calls.jsonl > /tmp/bad.jsonl
wc -l < /tmp/bad.jsonl                                           # → 20
jq -s 'map(select(.is_transferred)) | length' /tmp/bad.jsonl     # → 9
```

**Paso B.4. Traer las transcripciones de esas 20 a archivos.**

```bash
jq -r '.call_id' /tmp/bad.jsonl | while read id; do
  dp-mcp read uv get_call_info "{\"call_id\":\"$id\",\"fields\":[\"transcription_text\"]}" \
    > /tmp/tx_$id.json
done
```

Son 20 transcripciones largas, cada llamada autorizada, redactada y auditada por separado. **Ninguna entra
al contexto.**

**Paso B.5. Buscar la palabra, localmente.**

```bash
grep -li "cancel" /tmp/tx_*.json | wc -l                         # → 6
```

**Paso B.6. Respuesta.** Al contexto solo entraron los outputs de `search`/`schema` y tres números: *"20
llamadas de hoy con CSAT ≤ 2; 9 fueron transferidas y en 6 el cliente menciona cancelar."*

**El mismo pedido por MCP** serían varias páginas de `list_calls` más 20 `get_call_info`, y las 20
transcripciones completas dentro del contexto.

#### C.7 Riesgos propios de C en PhoneCentral

| Riesgo                                       | Por qué en PhoneCentral                                                                                                                                               | Mitigación                                                                                                   |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| **El decorator no dice quién puede ver qué** | `/api/voicerecording` tiene un check de acceso, pero es company-wide y permite el acceso por defecto si no hay llamada asociada. No se detecta leyendo el schema | `access_scope` y `credential` obligatorios y **completados por un humano**; el crawler nunca habilita        |
| **Credenciales de la API v2**                | El alcance depende de la credencial. Para un agente interno que mira varias empresas hace falta una credencial nueva de soporte, que es poderosa                 | Credencial dedicada de solo lectura, grupos acotados (`eng-oncall`), auditoría                               |
| **Contratos que cambian**                    | La API v2 está versionada (bien), pero las `/api/*` internas son view models sin versionar                                                                       | Que el crawler detecte cambios de schema y abra un PR; para `/api/*`, solo tools escritas a mano (como en B) |
| **Descripciones del LLM incorrectas**        | Un docstring ambiguo puede dar una descripción "convincente" pero equivocada (el problema `getX`/`getY` de la sección 0.6)                                       | Revisión del dueño en el PR; el diff queda versionado y se puede revertir                                    |
| **Retorno menor que en Uber**                | Uber: miles de servicios. PhoneCentral: ~409 endpoints públicos concentrados en UV                                                                                    | Encenderlo solo sobre `@public_api`, que es donde hay contratos de calidad                                   |

#### C.8 Qué problemas resuelve C

| #   | Problema                              | ¿C lo resuelve?                       | Por qué                                                                                       |
| --- | ------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------- |
| P1  | Setup frágil por laptop               | Sí                                    | Igual que B; Code Mode suma un solo CLI con una sola credencial                               |
| P2  | Agente con todos los permisos humanos | Sí                                    | Igual que B; además, nada generado entra habilitado                                           |
| P3  | Cero auditoría y métricas             | Sí                                    | Igual que B; Code Mode también pasa por el gateway                                            |
| P4  | PII cruda al modelo                   | Sí (mejor que B)                      | Redacción + projection + Code Mode (los datos quedan en archivos locales)                     |
| P5  | Muchos caminos al mismo sistema       | Sí                                    | Igual que B                                                                                   |
| P6  | Sistemas internos sin tools           | **Sí, a escala** (donde hay contrato) | ~409 endpoints `@public_api` pasan a "revisar y habilitar"; `/api/*` sin schema siguen a mano |
| P7  | Difícil descubrir; contexto inflado   | **Sí, del todo**                      | Catálogo grande con 5 meta-tools + projection + Code Mode                                     |

| Pros                                                        | Contras                                                           |
| ----------------------------------------------------------- | ----------------------------------------------------------------- |
| Resuelve "sistemas internos sin tools" **a escala**         | Fuera de `@public_api` casi no hay contratos legibles por máquina |
| Agregar una tool pasa a ser "revisar y habilitar"           | Más piezas que construir y operar (crawler, LLM, CLI)             |
| Lo más parecido a Uber, probado en producción a gran escala | La inversión más grande, con menos retorno que en Uber            |

---

### 4.3 Comparación final y recomendación

| #   | Problema                              | A: Kit estándar | B: Gateway de agregación     | C: Gateway completo     |
| --- | ------------------------------------- | --------------- | ---------------------------- | ----------------------- |
| P1  | Setup frágil por laptop               | Parcial         | Sí                           | Sí                      |
| P2  | Agente con todos los permisos humanos | Parcial         | Sí                           | Sí                      |
| P3  | Cero auditoría y métricas             | No              | Sí                           | Sí                      |
| P4  | PII cruda al modelo                   | No              | Sí (parcial)                 | Sí                      |
| P5  | Muchos caminos al mismo sistema       | Sí              | Sí                           | Sí                      |
| P6  | Sistemas internos sin tools           | Parcial         | Parcial                      | Sí (donde hay contrato) |
| P7  | Difícil descubrir; contexto inflado   | No              | Sí                           | Sí, del todo            |
|     | **Costo**                             | Bajo            | Medio                        | Alto                    |
|     | **Riesgo operativo**                  | Bajo            | Medio (punto único de falla) | Medio-alto              |

**Recomendación: B, con la puerta abierta a C de forma selectiva.**

1. Arrancar con el gateway y un registry en YAML. Migrar primero lo que más duele: Datastore de solo lectura y
   las llamadas de UV (en lugar de scraping de CSR).
2. Sumar **projection** pronto: es barato y no requiere crawler.
3. Encender el **crawler** solo sobre `@public_api`, y solo cuando haya demanda real de "exponer X endpoint".

Los principios de `phonecentral-user-mcp` (sin credenciales propias cuando importa quién pregunta, registry auditado,
sin parámetro `user_id` que el modelo pueda inventar) deberían ser la base del gateway, aunque el gateway apunte
a **agentes internos** y `phonecentral-user-mcp` a **agentes de producto**.

---

## 5) Lo que el gateway no resuelve, riesgos nuevos y cómo arrancar

Qué problema resuelve cada alternativa ya está en las tablas de la sección 4 (A, B.6, C.8 y 4.3). Esta sección
cubre el otro lado: lo que **sigue** siendo un problema, lo que el gateway **agrega** como riesgo, y cómo
probarlo en chico antes de comprometerse.

### 5.1 Problemas que siguen existiendo con el gateway

| Problema                                        | Por qué sigue                                                                                                                                                                                                                             | Mitigación                                                                                                                      |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **Prompt injection**                            | El gateway limita **qué** puede hacer el agente, no **por qué** lo hace. Un ticket malicioso puede inducirlo a usar mal tools que sí tiene permitidas                                                                                     | Separar riesgos (`read`/`write`/`destructive`), pedir confirmación para escrituras, alertas en el audit log ante patrones raros |
| **Exfiltración por tools de escritura**         | Si un agente tiene a la vez datos privados (`uv.get_call_info`), contenido no confiable (un ticket) y un canal de salida (`createJiraIssue`, comentar un PR), puede sacar datos sin borrar nada. Se la conoce como la *"lethal trifecta"* | Evitar que una misma sesión combine las tres cosas sin confirmación humana; grupos más chicos para las tools de escritura       |
| **PII en texto libre**                          | La redacción por campo (`external_number`) funciona en datos estructurados, pero una `transcription_text` puede traer teléfonos, emails o datos de tarjeta dentro del texto                                                               | Redacción por patrones (regex/DLP) en campos de texto libre; o no exponer esos campos a grupos amplios                          |
| **Lo que pasa el filtro igual llega al modelo** | El gateway decide qué sale, pero lo que sale viaja a la nube del proveedor del modelo                                                                                                                                                     | Política de datos explícita por tool: qué clasificación de datos puede salir hacia un LLM                                       |
| **Errores del agente dentro de sus permisos**   | Una escritura permitida pero equivocada (comentar en el ticket incorrecto) pasa todos los chequeos                                                                                                                                        | Auditoría para detectar y revertir; escrituras siempre de a una y confirmadas                                                   |
| **Descripciones de tools malas**                | El problema `getX`/`getY` (sección 0.6) no lo resuelve el gateway, solo lo centraliza                                                                                                                                                     | Revisión del dueño en el PR; métricas de qué tools fallan o se usan mal                                                         |

### 5.2 Riesgos nuevos que crea el gateway

| Riesgo nuevo                           | En qué consiste                                                                                                                           | Mitigación                                                                                                                      |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| **Punto único de falla**               | Si el gateway se cae, se caen todos los agentes de la empresa a la vez                                                                    | Cloud Run con varias instancias mínimas, SLO propio, y un "modo degradado" documentado (volver temporalmente a los CLIs)        |
| **Latencia extra**                     | Cada llamada suma un salto de red y los chequeos                                                                                          | Mantener el data plane chico, como `egress-proxy`: pocas dependencias, nada sincrónico innecesario                              |
| **El vault como blanco**               | Guarda tokens de Atlassian/GitHub de **todos** los devs. Comprometer el gateway compromete a todos                                        | Cifrado con KMS, scopes OAuth mínimos, tokens de vida corta con refresh, acceso al vault solo desde el data plane               |
| **Credenciales de servicio poderosas** | `support_readonly` puede leer datos de cualquier empresa. Un bug en la authZ del gateway la expone a cualquiera                           | Solo lectura, grupos acotados, tests que fijen las invariantes de authZ (como hace `phonecentral-user-mcp`), alertas por uso anómalo |
| ***Confused deputy***                  | El gateway tiene más permisos que quien le pide algo; si la authZ falla, actúa "en nombre de" alguien que no debería poder                | Ninguna tool acepta un `user_id` como parámetro: la identidad viene solo del token (principio de `phonecentral-user-mcp`)            |
| **Cuello de botella organizacional**   | Toda tool nueva pasa por un PR al registry; si el equipo dueño del gateway tarda, los equipos vuelven a armar integraciones por su cuenta | El registry lo aprueba **el equipo dueño de la tool** (CODEOWNERS por archivo), no el equipo del gateway                        |
| **Debugging más difícil**              | Un error puede estar en el agente, el gateway o el sistema de fondo                                                                       | Un request id que viaje de punta a punta y quede en el audit log                                                                |
| **Desfase con los servers externos**   | Si Atlassian agrega o cambia tools, el registry no se entera solo                                                                         | El catálogo marca las tools nuevas como "disponibles pero no habilitadas" y avisa al dueño                                      |

### 5.3 Cómo arrancar: un piloto chico

La idea es probar B con el mínimo que ya demuestre valor, y crecer solo si las métricas (5.4) acompañan.

| Fase                 | Qué incluye                                                                                                                                       | Quién lo usa                             | Criterio para pasar a la siguiente                                                                                    |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| **0. Decisiones**    | Equipo dueño del gateway; diseño de authN (SSO de Google) y de credenciales; dónde vive el registry                                               | —                                        | Las preguntas abiertas de 5.5 respondidas                                                                             |
| **1. Piloto mínimo** | Gateway B con `catalog/mcp`, audit log a BigQuery, y **dos tools internas**: `datastore_get_entity` (cuenta de solo lectura) y `uv.get_call_info` | Equipo de on-call de UV, con Claude Code | Las skills `datastore-lookup` y el scraping de CSR dejan de usarse en el piloto; latencia y disponibilidad aceptables |
| **2. Terceros**      | Proxy a Atlassian con vault y token por usuario; **projection**                                                                                   | Todo el equipo de UV                     | El `jira` CLI deja de ser necesario en las skills del equipo                                                          |
| **3. Code Mode**     | CLI `dp-mcp` + skill                                                                                                                              | Usuarios de Claude Code                  | Tareas con muchos datos resueltas sin inflar el contexto                                                              |
| **4. Crawler**       | Autogeneración desde `@public_api`, deshabilitada por defecto                                                                                     | Equipos dueños de la API v2              | Solo si hay pedidos reales de exponer más endpoints                                                                   |

Cada fase deja algo útil por sí sola. Si el piloto no convence, lo aprendido igual sirve para la alternativa A.

### 5.4 Métricas para decidir

| Métrica                          | Cómo se mide                                                          | Señal de éxito                                |
| -------------------------------- | --------------------------------------------------------------------- | --------------------------------------------- |
| Setup de un dev nuevo            | Tiempo y cantidad de credenciales hasta tener los agentes funcionando | De ~8 credenciales a 1 (SSO)                  |
| Cobertura de auditoría           | % de llamadas de agentes a sistemas internos que pasan por el gateway | Crece fase a fase                             |
| Integraciones "a mano" retiradas | Skills con curl, scraping o CLIs caseros reemplazadas                 | Bajan en cada fase                            |
| Contexto ahorrado                | Bytes devueltos al modelo por tarea, con y sin projection/Code Mode   | Baja notable en tareas con muchos datos       |
| Guardrails funcionando           | Cantidad de rechazos `forbidden`, `tool_disabled`, `risk_mismatch`    | Existen (los chequeos actúan) y se investigan |
| Salud del gateway                | Disponibilidad y latencia p95                                         | Dentro del SLO definido en la fase 0          |
| Adopción                         | Cantidad de agentes y equipos distintos que lo usan                   | Crece sin que nadie lo imponga                |

### 5.5 Preguntas abiertas

- **¿Quién es el dueño del gateway?** Es un servicio crítico: necesita on-call, SLO y roadmap.
- **¿Atlassian permite que el gateway sea cliente OAuth de su MCP server?** Si no, ¿se llama directo a la API
  REST de Jira?
- **¿Qué credencial usa el gateway para datos de UV?** ¿Existe algo equivalente a los permisos de CSR que se
  pueda acotar a solo lectura?
- **¿Qué relación tiene con `phonecentral-user-mcp`?** ¿Lo absorbe, lo pone detrás como un server más, o quedan
  separados (agentes internos vs. agentes de producto)?
- **¿Glean entra detrás del gateway** como un server más, o sigue conectado directo?
- **¿Qué datos pueden salir hacia un LLM?** Hace falta una política por clasificación de datos que el gateway
  pueda aplicar.

---

## Apéndice: resumen del artículo de Uber

### El problema

La adopción de MCP en Uber fue rápida, pero cada equipo armaba sus integraciones por su cuenta: fragmentación,
infraestructura duplicada, tools difíciles de descubrir y operar, acoplamiento fuerte a servicios y agentes
específicos, riesgo de seguridad creciente y fricción para los devs. Necesitaban algo central que tradujera
protocolos (HTTP, gRPC, TChannel) y aplicara seguridad y observabilidad de forma consistente.

### Arquitectura

El **MCP Gateway** es un microservicio entre los agentes y los backends (o servers MCP nativos). Dos partes:

- **MCP Registry (control plane):** catálogo de servers y tools; fuente de verdad para descubrimiento,
  ownership y habilitación.
- **Proxy Gateway (data plane):** ejecuta los requests MCP en runtime, traduciéndolos a HTTP/gRPC/TChannel y
  convirtiendo las respuestas de vuelta.

Las APIs existentes se exponen como tools **sin cambiar los servicios**.

### Control plane

- **AutoCrawler:** workflow (sobre Cadence) disparado por cron que escanea el registro de IDLs
  (Protobuf/Thrift) y detecta servicios, APIs y cambios de schema. Por cada servicio: crea un *virtual MCP
  server*, parsea el IDL (métodos, schemas, doc comments), **usa un LLM para generar descripciones
  "agent-friendly"**, traduce los schemas a JSON Schema MCP y registra las tools **deshabilitadas por
  defecto**.
- **Servers MCP nativos** (hechos con MCPFx, el framework interno): emiten un heartbeat; AutoCrawler los
  detecta, llama a `listTools` y crea un proxy virtual en el Registry, también deshabilitado.
- **Servers de terceros (Jira, Google):** el gateway pasa el token del usuario y aplica authZ, rate limiting
  y redacción; un servicio aparte intercambia el token interno por el del proveedor externo.
- **Ownership:** *"descubrir no implica exponer"*. Todo arranca deshabilitado; el equipo dueño revisa,
  ajusta las definiciones y habilita. Cada cambio de descripción genera un diff que el dueño aprueba, con
  deploy o rollback a una versión anterior.

### Data plane

- Toma la configuración del control plane periódicamente y la refresca en memoria, sin restarts.
- Materializa *virtual MCP servers* en paths `/<service-name>/mcp`.
- Para tools sobre IDL: JSON → formato de cable → bytes Protobuf/Thrift → llamada downstream → respuesta a
  JSON MCP. La llamada sale por **Muttley**, el sidecar del service mesh, así que reusa el routing existente.
- Servers nativos: proxy transparente.
- **Seguridad:** autorización a nivel tool con el sistema de control de acceso de Uber (políticas para
  humanos, servicios y agentes, por server con overrides por tool). **PII redactada por defecto** en las
  respuestas.

### Escala

- **Omni MCP:** un único server proxy con 4 tools (`discover_server`, `discover_tools`, `get_tool_schema`,
  `invoke_tool`) para descubrimiento incremental, evitando inflar el contexto.
- **Response Projection:** estilo GraphQL; el LLM indica qué campos quiere y el gateway recorta la respuesta.
- **Code Mode:** para agentes de código en shell, vía `aifx` (CLI interno): `aifx mcp list`, `search` y
  `call`. El agente encadena comandos y guarda output en archivos para buscar selectivamente. Es el default
  en Uber para agentes de código y no requiere servers MCP locales.

### Números

Más de 800 servers MCP, más de 5.000 tools, miles de servicios internos y cientos de equipos con workflows
agénticos.

### Lo que el artículo no detalla

Métricas o dashboards concretos de observabilidad, mecánica de versionado más allá de diff + rollback, y la
cadencia exacta del refresh del data plane.
