# Mini Split Engine — Desafio Técnico Cakto

API REST desenvolvida como desafio técnico para a Cakto, construída com Django 6 e Django REST Framework.

---

## Stack

| Tecnologia | Versão |
|---|---|
| Python | 3.12+ |
| Django | 6.0.3 |
| Django REST Framework | 3.17 |
| djangorestframework-simplejwt | 5.5 |
| drf-spectacular | 0.29 |
| django-filter | 25.2 |
| python-decouple | 3.8 |
| psycopg2-binary | 2.9 |
| Ruff | 0.15 |

Gerenciamento de dependências via **Poetry**.

---

## Configuração de variáveis de ambiente

As variáveis de ambiente são carregadas a partir do arquivo `.env` via **python-decouple**. Essa escolha foi intencional para demonstrar conhecimento sobre boas práticas no Django em relação à exposição de dados sensíveis — `SECRET_KEY` nunca deve ser exposta no código-fonte nem versionada, e `DEBUG` deve ser explicitamente controlado por ambiente para evitar vazamento de informações em produção.

Crie um arquivo `.env` na raiz do projeto a partir do exemplo:

```bash
cp .env.example .env
```

Conteúdo do `.env.example`:

```env
# Django
SECRET_KEY=sua-secret-key-aqui
DEBUG=True

# PostgreSQL
DB_NAME=mini_split
DB_USER=mini_split_user
DB_PASSWORD=mini_split_pass
DB_HOST=db
DB_PORT=5432
```

> **Nota:** `DB_HOST=db` aponta para o serviço PostgreSQL do Docker Compose. Para rodar localmente sem Docker, altere para `DB_HOST=localhost`.

---

## Estrutura do projeto

```
mini-split-engine/
├── apps/                         # Aplicações Django
│   ├── core/                     # Base compartilhada
│   │   ├── handlers/
│   │   │   ├── paginator.py      # Paginação customizada
│   │   │   └── logger-engine.py  # Logger do projeto
│   │   └── models.py             # TimeStampedModel (model abstrato base)
│   │
│   ├── users/                    # Autenticação e usuários
│   │   └── models.py             # CustomUser com auth via e-mail
│   │
│   ├── bbcs/                     # Domínio principal do desafio
│   │   ├── services/
│   │   │   └── split_calculator.py  # Cálculo de taxas e split
│   │   ├── models.py             # Payment, LedgerEntry, Plan
│   │   ├── serializers.py        # Validação de entrada e serialização de saída
│   │   └── tests.py              # Testes da calculadora
│   │
│   ├── payees/                   # Recebedores do split
│   │   └── models.py             # Recipient
│   │
│   └── audit/                    # Auditoria de operações
│       └── models.py             # OutboxEvent
│
├── engine/                       # Configurações do projeto Django
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── static/                       # Arquivos estáticos
├── templates/
│   └── rapidoc.html              # Documentação interativa da API
├── manage.py
├── pyproject.toml
└── .env                          # Variáveis de ambiente (não versionado)
```

### Descrição das apps

| App | Responsabilidade |
|---|---|
| `core` | Model abstrato base (`TimeStampedModel`), paginação e logger compartilhados |
| `users` | Modelo de usuário customizado com autenticação por e-mail e JWT |
| `bbcs` | Domínio principal: `Payment`, `LedgerEntry` e `Plan` |
| `payees` | Cadastro de recebedores elegíveis ao split (`Recipient`) |
| `audit` | Registro e rastreamento de operações |

### Modelos de domínio

#### `bbcs`

| Model | Responsabilidade |
|---|---|
| `Payment` | Transação confirmada com valores bruto, taxa e líquido, método, parcelas e idempotência |
| `LedgerEntry` | Lançamento por recebedor gerado a partir do split do `net_amount` |
| `Plan` | Tabela de taxas (`fee_table`) e prazos de liquidação (`settlement_table`) por modalidade e parcela |

#### `payees`

| Model | Responsabilidade |
|---|---|
| `Recipient` | Participante elegível ao split, com papel (`role`), `external_id` como referência na API e dados bancários opcionais |

#### `audit`

| Model | Responsabilidade |
|---|---|
| `OutboxEvent` | Evento de domínio persistido atomicamente com o pagamento para publicação assíncrona |

---

## Padrões adotados

### Enumerações com `enum.Enum`

Todos os campos de escolha nos models usam `enum.Enum` puro em vez de `models.TextChoices`. Cada membro carrega uma tupla `(code, label)` — ou `(code, label, flag)` quando há uma regra de negócio associada (ex: `allows_installments` em `PaymentMethodEnum`). O método de classe `choices()` retorna a lista de tuplas compatível com o argumento `choices` dos campos Django.

Essa abordagem centraliza tanto os dados de exibição quanto as regras de negócio ligadas ao tipo em um único lugar, sem depender da infraestrutura do ORM.

### `TimeStampedModel` — model abstrato base

Todos os models de domínio herdam de `TimeStampedModel` (`apps/core/models.py`), que fornece:

- `id` como `UUIDField` (evita exposição de sequências numéricas)
- `created_at` e `updated_at` automáticos
- `active` para **soft delete** — registros nunca são deletados fisicamente
- Manager `objects` que retorna apenas registros ativos por padrão
- Manager `allobjects` para acesso irrestrito quando necessário

### `CustomUser` — autenticação por e-mail

O modelo de usuário substitui o padrão do Django para usar e-mail como `USERNAME_FIELD`, eliminando o campo `username`. Segue o mesmo padrão de UUID como chave primária.

### `Plan` — tabela de taxas e prazos como JSONField

As regras financeiras de cada modalidade de cobrança (débito, crédito, parcelado) ficam em dois `JSONField`: `fee_table` para taxas e `settlement_table` para prazos de liquidação por parcela. A estrutura JSON foi escolhida para dar flexibilidade e velocidade no contexto do desafio — adicionar uma nova modalidade não exige alteração de schema.

### `Recipient.bank_account` — JSONField por pragmatismo

Os dados bancários do recebedor são armazenados como `JSONField` opcional. Em produção, o correto seria uma tabela `BankAccount` separada com FK para `Recipient`, garantindo rastreabilidade completa de mudanças de conta ao longo do tempo (histórico, auditoria, rollback).

### `recipient_id` no split — string livre vs. entidade cadastrada

No `SplitInputSerializer`, o campo `recipient_id` é atualmente um `CharField` livre, alinhado com o payload de exemplo do desafio (`"producer_1"`, `"affiliate_9"`). O desafio não exige pré-cadastro de recebedores.

Em produção, o correto seria validar o `recipient_id` contra o `external_id` do model `Recipient` via `SlugRelatedField`, garantindo que apenas recebedores cadastrados participem de um split:

```python
recipient_id = serializers.SlugRelatedField(
    slug_field="external_id",
    queryset=Recipient.objects.all(),
)
```

Isso adicionaria integridade referencial na camada de entrada, antes de qualquer cálculo ou persistência.

### `OutboxEvent` — padrão Transactional Outbox

Eventos críticos (como `payment_captured`) são persistidos na mesma transação do pagamento. Um worker externo lê os eventos com `status="pending"` e os publica no broker, atualizando para `"published"`. Isso elimina o risco de inconsistência entre banco e mensageria: se a transação falhar, o evento não é criado; se o evento existir, o pagamento foi confirmado.

### Estratégia de idempotência — `Payment`

O modelo `Payment` possui dois campos relacionados à idempotência:

- `idempotency_key` — chave fornecida pelo cliente via header, com `unique=True` e índice de banco. Garante que não existam dois pagamentos com a mesma chave.
- `idempotency_payload_hash` — campo **opcional** (nullable) com SHA-256 do payload original. Quando presente, uma `UniqueConstraint` composta entre `idempotency_key` e `idempotency_payload_hash` reforça no banco que a mesma chave não pode ser reutilizada com um payload diferente.

**Por que o hash é opcional?**

O desafio não exige hash — a detecção de conflito pode ser feita comparando diretamente o `payload` (JSONField) na camada de serviço. O hash foi introduzido como decisão técnica para oferecer uma segunda linha de defesa no banco: comparar 64 caracteres é indexável e determinístico, enquanto a comparação de JSON é sensível à ordenação de chaves.

**Comportamento resultante:**

| Cenário | Camada de proteção |
|---|---|
| Mesma key, mesmo payload | Service retorna resultado existente (sem inserção) |
| Mesma key, payload diferente, hash presente | Banco rejeita via `UniqueConstraint` + service retorna 409 |
| Mesma key, payload diferente, hash ausente | Service detecta divergência e retorna 409 |

> **Nota:** No PostgreSQL, `NULL != NULL` em constraints de unicidade — dois registros com `idempotency_payload_hash = NULL` não colidem no banco. Quando o hash não é fornecido, toda a responsabilidade de conflito recai sobre a service.

---

## Como executar

### Com Docker Compose (recomendado)

Sobe o banco PostgreSQL e a aplicação Django em containers:

```bash
# Copiar e configurar variáveis de ambiente
cp .env.example .env

# Subir os serviços
docker compose up --build
```

A API estará disponível em `http://localhost:8000`.

Para rodar em background:

```bash
docker compose up -d --build
```

Para parar os serviços:

```bash
docker compose down
```

Para destruir os volumes (apaga os dados do banco):

```bash
docker compose down -v
```

### Localmente (sem Docker)

Altere `DB_HOST=localhost` no `.env` e certifique-se de ter um PostgreSQL rodando localmente. Então:

```bash
# Instalar dependências
poetry install

# Aplicar migrações
python manage.py migrate

# Rodar o servidor
python manage.py runserver
```

---

## Populando a base de dados (seed)

Os commands de seed usam a lib **Faker** para gerar dados fictícios realistas.

```bash
# Popula tudo com os valores padrão (20 recebedores + 30 pagamentos)
python manage.py seed

# Ajusta as quantidades
python manage.py seed --payees 50 --payments 100

# Limpa os dados existentes antes de popular
python manage.py seed --clear

# Commands individuais
python manage.py seed_payees --count 30
python manage.py seed_bbcs --payments 50 --skip-plans
```

| Command | O que cria |
|---|---|
| `seed` | Orquestra `seed_payees` + `seed_bbcs` |
| `seed_payees` | `Recipient` com dados bancários fictícios |
| `seed_bbcs` | `Plan` (padrão + premium), `Payment` e `LedgerEntry` |

---

## Como executar os testes

```bash
# Ativar o ambiente virtual e rodar todos os testes
source .venv/bin/activate
pytest

# Com cobertura
pytest --cov=apps

# Apenas um módulo
pytest apps/bbcs/tests.py
```

---

## Decisões técnicas

### 1. Precisão e arredondamento

Todos os cálculos financeiros usam `Decimal` (módulo `decimal` do Python) com arredondamento explícito via `ROUND_DOWN` (truncamento). Float foi descartado por acumular erros de representação binária — em contextos financeiros isso é inaceitável.

A taxa da plataforma é calculada como:

```
fee = (gross_amount × fee_rate).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
net_amount = gross_amount − fee
```

O truncamento favorece o recebedor (evita cobrar centavo extra), o que é a convenção adotada em processadores de pagamento como Stripe e Adyen.

### 2. Regra de centavos no split

Ao distribuir o `net_amount` entre os recebedores, cada parcela é truncada em 2 casas decimais. O centavo residual (diferença entre a soma das parcelas e o `net_amount`) é absorvido pelo **primeiro recebedor da lista**.

**Por quê?** Qualquer estratégia de distribuição de centavo envolve uma escolha arbitrária. O primeiro recebedor foi escolhido por ser determinístico (sem aleatoriedade), auditável (qualquer repetição do cálculo produz o mesmo resultado) e simples de implementar e testar. O README e os testes documentam essa regra explicitamente para que não haja surpresas.

### 3. Estratégia de idempotência

A idempotência é implementada em duas camadas:

- **Camada de serviço:** ao receber uma `Idempotency-Key`, a service busca o `Payment` existente antes de qualquer inserção. Se encontrado, verifica o `idempotency_payload_hash` (SHA-256 do payload normalizado com chaves ordenadas). Hash igual → retorna o pagamento existente. Hash diferente → lança `PaymentConflictError` (HTTP 409).
- **Camada de banco:** `idempotency_key` tem `unique=True`. Uma `UniqueConstraint` composta entre `idempotency_key` e `idempotency_payload_hash` atua como segunda linha de defesa contra race conditions, garantindo integridade mesmo sob concorrência.

O hash normaliza o payload com `json.dumps(sort_keys=True)` para tornar a comparação independente da ordem de serialização das chaves.

### 4. Métricas que colocaria em produção

| Métrica | Ferramenta sugerida | Por quê |
|---|---|---|
| Latência p50/p95/p99 do `POST /api/v1/payments` | Prometheus + Grafana | SLA de pagamentos exige latência baixa e previsível |
| Taxa de erros 4xx/5xx por endpoint | Prometheus counter | Distingue erros de cliente (400/409/422) de falhas internas (500) |
| Taxa de hits de idempotência | Contador custom | Indica clientes com retry excessivo ou bugs de integração |
| Fila de `OutboxEvent` com `status=pending` | Job periódico + alerta | Eventos não publicados indicam falha no worker de mensageria |
| Tempo de processamento da transação atômica | Histogram | Detecta contenção no banco sob carga |

---
