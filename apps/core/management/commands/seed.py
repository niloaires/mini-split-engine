from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Popula toda a base de dados com dados fictícios (payees + bbcs)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--payees",
            type=int,
            default=20,
            help="Quantidade de recebedores a criar (padrão: 20).",
        )
        parser.add_argument(
            "--payments",
            type=int,
            default=30,
            help="Quantidade de pagamentos a criar (padrão: 30).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Limpa todos os dados existentes antes de popular.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Iniciando seed..."))

        self.stdout.write("→ Recebedores (payees)")
        call_command("seed_payees", count=options["payees"], clear=options["clear"], stdout=self.stdout)

        self.stdout.write("→ Planos e pagamentos (bbcs)")
        call_command("seed_bbcs", payments=options["payments"], clear=options["clear"], stdout=self.stdout)

        self.stdout.write(self.style.SUCCESS("Seed concluído."))
