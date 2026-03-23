import uuid

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models


class CustomUserManager(BaseUserManager):
    """
    Gerenciador customizado para o modelo de usuário com autenticação por e-mail.

    Substitui o gerenciador padrão do Django, que usa username como identificador,
    pelo e-mail. Esse é o padrão adotado em todos os projetos Django para garantir
    que a autenticação seja feita via e-mail em vez de username.

    Métodos:
        create_user: Cria um usuário comum com e-mail e senha.
        create_superuser: Cria um superusuário com is_staff e is_superuser ativos.
    """

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("O campo e-mail é obrigatório")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    """
    Modelo de usuário customizado com autenticação por e-mail.

    Substitui o modelo padrão do Django (User) para permitir autenticação via
    e-mail em vez de username. Esse é o padrão adotado em todos os projetos Django,
    garantindo flexibilidade e controle total sobre os campos e comportamentos do usuário.

    Herda de AbstractBaseUser (fornece hash de senha e last_login) e PermissionsMixin
    (fornece suporte a grupos e permissões).

    Atributos:
        id (UUIDField): Identificador único universal, gerado automaticamente.
        name (CharField): Nome do usuário (opcional).
        email (EmailField): E-mail único, usado como identificador de autenticação.
        date_joined (DateTimeField): Data e hora de cadastro do usuário.
        updated_at (DateTimeField): Data e hora da última atualização do registro.
        is_active (BooleanField): Indica se o usuário está ativo. Padrão: True.
        is_staff (BooleanField): Indica se o usuário tem acesso ao admin. Padrão: False.
        objects (CustomUserManager): Gerenciador customizado com autenticação por e-mail.

    Meta:
        verbose_name: "Usuário"
        verbose_name_plural: "Usuários"
        ordering: Ordenado por data de cadastro decrescente.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(blank=True, null=True)
    email = models.EmailField(unique=True, verbose_name="Email")
    date_joined = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    objects = CustomUserManager()
    updated_at = models.DateTimeField(auto_now=True)
    USERNAME_FIELD = "email"

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"
        ordering = ["-date_joined"]
