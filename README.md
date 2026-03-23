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
│   │
│   └── audit/                    # Auditoria de operações
│
├── engine/                       # Configurações do projeto Django
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── manage.py
├── pyproject.toml
└── .env                          # Variáveis de ambiente (não versionado)
```

### Descrição das apps

| App | Responsabilidade |
|---|---|
| `core` | Model abstrato base (`TimeStampedModel`), paginação e logger compartilhados |
| `users` | Modelo de usuário customizado com autenticação por e-mail e JWT |
| `bbcs` | Domínio principal do desafio técnico |
| `audit` | Registro e rastreamento de operações |

---

## Padrões adotados

### `TimeStampedModel` — model abstrato base

Todos os models de domínio herdam de `TimeStampedModel` (`apps/core/models.py`), que fornece:

- `id` como `UUIDField` (evita exposição de sequências numéricas)
- `created_at` e `updated_at` automáticos
- `active` para **soft delete** — registros nunca são deletados fisicamente
- Manager `objects` que retorna apenas registros ativos por padrão
- Manager `allobjects` para acesso irrestrito quando necessário

### `CustomUser` — autenticação por e-mail

O modelo de usuário substitui o padrão do Django para usar e-mail como `USERNAME_FIELD`, eliminando o campo `username`. Segue o mesmo padrão de UUID como chave primária.

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
