import hashlib
import json
import random
import uuid
from decimal import ROUND_DOWN, Decimal

from django.core.management.base import BaseCommand
from faker import Faker

from apps.bbcs.models import LedgerEntry, Payment, PaymentMethodEnum, PaymentStatusEnum, Plan

fake = Faker("pt_BR")


DEFAULT_PLANS = [
    {
        "name": "Padrão",
        "is_default": True,
        "fee_table": {
            "pix": {"1": {"taxa": 0.0}},
            "card": {str(i): {"taxa": round(2.99 + (i - 1) * 0.5, 2)} for i in range(1, 13)},
        },
        "settlement_table": {
            "pix": {"1": {"prazo": 1}},
            "card": {str(i): {"prazo": i * 30} for i in range(1, 13)},
        },
    },
    {
        "name": "Premium",
        "is_default": False,
        "fee_table": {
            "pix": {"1": {"taxa": 0.0}},
            "card": {str(i): {"taxa": round(1.99 + (i - 1) * 0.4, 2)} for i in range(1, 13)},
        },
        "settlement_table": {
            "pix": {"1": {"prazo": 1}},
            "card": {str(i): {"prazo": i * 30} for i in range(1, 13)},
        },
    },
]

ROLES = ["Industria", "distributor", "coproducer"]


def _get_fee_rate(plan: Plan, method: str, installments: int) -> Decimal:
    try:
        taxa = plan.fee_table[method][str(installments)]["taxa"]
        return Decimal(str(taxa)) / Decimal("100")
    except (KeyError, TypeError):
        return Decimal("0")


def _build_splits(recipients: list[str]) -> list[dict]:
    """Distribui 100% entre os recebedores aleatoriamente."""
    n = len(recipients)
    if n == 1:
        return [{"recipient_id": recipients[0], "role": random.choice(ROLES), "percent": Decimal("100.00")}]

    percents = []
    remaining = Decimal("100.00")
    for idx in range(n - 1):
        max_share = remaining - Decimal("1.00") * (n - 1 - idx)
        low = min(10, int(max_share))
        share = Decimal(str(random.randint(low, int(max_share)))).quantize(Decimal("0.01"))
        percents.append(share)
        remaining -= share
    percents.append(remaining)

    return [
        {"recipient_id": rid, "role": random.choice(ROLES), "percent": p}
        for rid, p in zip(recipients, percents, strict=True)
    ]


def _split_amount(net_amount: Decimal, splits: list[dict]) -> list[dict]:
    entries = []
    total = Decimal("0.00")
    for split in splits:
        amount = (net_amount * split["percent"] / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        entries.append({**split, "amount": amount})
        total += amount
    residual = net_amount - total
    if residual and entries:
        entries[0]["amount"] += residual
    return entries


def _payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()

class Command(BaseCommand):
    help = "Popula Plans, Payments e LedgerEntries com dados fictícios via Faker."

    def add_arguments(self, parser):
        parser.add_argument(
            "--payments",
            type=int,
            default=30,
            help="Quantidade de pagamentos a criar (padrão: 30).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Remove todos os dados de bbcs antes de criar novos.",
        )
        parser.add_argument(
            "--skip-plans",
            action="store_true",
            help="Não recria os planos padrão.",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            le_count, _ = LedgerEntry.allobjects.all().delete()
            pay_count, _ = Payment.allobjects.all().delete()
            plan_count, _ = Plan.allobjects.all().delete()
            self.stdout.write(
                self.style.WARNING(
                    f"  Removidos: {plan_count} plano(s), {pay_count} pagamento(s), {le_count} lançamento(s)."
                )
            )

        # ── Planos ────────────────────────────────────────────────────────────
        if not options["skip_plans"]:
            for plan_data in DEFAULT_PLANS:
                Plan.objects.update_or_create(
                    name=plan_data["name"],
                    defaults={
                        "fee_table": plan_data["fee_table"],
                        "settlement_table": plan_data["settlement_table"],
                        "is_default": plan_data["is_default"],
                    },
                )
            self.stdout.write(self.style.SUCCESS(f"  {len(DEFAULT_PLANS)} plano(s) sincronizado(s)."))

        plan = Plan.objects.filter(is_default=True).first()
        if not plan:
            self.stdout.write(self.style.ERROR("  Nenhum plano padrão encontrado. Abortando pagamentos."))
            return

        # ── Pagamentos ────────────────────────────────────────────────────────
        methods = [PaymentMethodEnum.PIX, PaymentMethodEnum.CARD]
        statuses = [s.code for s in PaymentStatusEnum]
        created = 0

        for _ in range(options["payments"]):
            method = random.choice(methods)
            installments = 1 if method == PaymentMethodEnum.PIX else random.randint(1, 12)
            gross_amount = Decimal(str(random.randint(5000, 500000))) / Decimal("100")

            fee_rate = _get_fee_rate(plan, method.code, installments)
            fee = (gross_amount * fee_rate).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            net_amount = gross_amount - fee

            n_recipients = random.randint(1, 3)
            recipient_ids = [f"{random.choice(ROLES)}_{i}" for i in random.sample(range(1, 50), n_recipients)]
            splits = _build_splits(recipient_ids)

            payload = {
                "amount": str(gross_amount),
                "currency": "BRL",
                "payment_method": method.code,
                "installments": installments,
                "splits": [
                    {"recipient_id": s["recipient_id"], "role": s["role"], "percent": str(s["percent"])}
                    for s in splits
                ],
            }
            idempotency_key = str(uuid.uuid4())
            payload_hash = _payload_hash(payload)

            payment = Payment.objects.create(
                gross_amount=gross_amount,
                platform_fee_amount=fee,
                net_amount=net_amount,
                payment_method=method.code,
                installments=installments,
                currency="BRL",
                status=random.choice(statuses),
                idempotency_key=idempotency_key,
                idempotency_payload_hash=payload_hash,
                payload=payload,
            )

            entries = _split_amount(net_amount, splits)
            LedgerEntry.objects.bulk_create([
                LedgerEntry(
                    payment=payment,
                    recipient_id=e["recipient_id"],
                    role=e["role"],
                    percent=e["percent"],
                    amount=e["amount"],
                )
                for e in entries
            ])
            created += 1

        self.stdout.write(self.style.SUCCESS(f"  {created} pagamento(s) e seus lançamentos criados."))
