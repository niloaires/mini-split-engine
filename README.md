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

As variáveis `SECRET_KEY` e `DEBUG` do Django são carregadas a partir do arquivo `.env` via **python-decouple**. Essa escolha foi intencional para demonstrar conhecimento sobre boas práticas no Django em relação à exposição de dados sensíveis — `SECRET_KEY` nunca deve ser exposta no código-fonte nem versionada, e `DEBUG` deve ser explicitamente controlado por ambiente para evitar vazamento de informações em produção.

Crie um arquivo `.env` na raiz do projeto:

```env
SECRET_KEY=sua-secret-key-aqui
DEBUG=True
```

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

```bash
# Instalar dependências
poetry install

# Aplicar migrações
python manage.py migrate

# Rodar o servidor
python manage.py runserver
```

---

> Mais seções serão adicionadas conforme o desenvolvimento avança.
