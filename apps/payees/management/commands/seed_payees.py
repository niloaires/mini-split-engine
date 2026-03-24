import random

from django.core.management.base import BaseCommand
from faker import Faker

from apps.payees.models import Recipient, RecipientRoleEnum

fake = Faker("pt_BR")

BANKS = ["001", "033", "104", "237", "341", "756"]
ACCOUNT_TYPES = ["checking", "savings"]
ROLES = [role.code for role in RecipientRoleEnum]


def _fake_document(role: str) -> str:
    """Gera CPF para Industria/distributor e CNPJ para coproducer."""
    if role == RecipientRoleEnum.STOREKEEPER.code:
        return fake.cnpj()
    return fake.cpf()


def _fake_bank_account() -> dict:
    return {
        "bank": random.choice(BANKS),
        "agency": str(random.randint(1000, 9999)),
        "account": f"{random.randint(10000, 99999)}-{random.randint(0, 9)}",
        "type": random.choice(ACCOUNT_TYPES),
    }


class Command(BaseCommand):
    help = "Popula a tabela de recebedores (Recipient) com dados fictícios via Faker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=20,
            help="Quantidade de recebedores a criar (padrão: 20).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Remove todos os recebedores existentes antes de criar novos.",
        )

    def handle(self, *args, **options):
        count = options["count"]

        if options["clear"]:
            deleted, _ = Recipient.allobjects.all().delete()
            self.stdout.write(self.style.WARNING(f"  {deleted} recebedor(es) removido(s)."))

        created = 0
        for i in range(1, count + 1):
            role = random.choice(ROLES)
            external_id = f"{role}_{i}_{fake.lexify('????')}"
            document = _fake_document(role)

            _, was_created = Recipient.objects.get_or_create(
                external_id=external_id,
                defaults={
                    "name": fake.name(),
                    "document": document,
                    "email": fake.email(),
                    "role": role,
                    "bank_account": _fake_bank_account(),
                },
            )
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(f"  {created} recebedor(es) criado(s)."))
