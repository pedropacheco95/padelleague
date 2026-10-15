"""Generic editor/CSV writes must not target the read-only compat models.

The nine pre-v2 competition classes (Division, Edition, Match, the shuffle
classes and their association tables) map onto views in schema `compat`;
writing them raises CompatWriteError at flush. The generic CRUD screens and
CSV loaders refuse them up front with a message naming the v2 action instead.
"""

COMPAT_WRITE_MESSAGE = (
    "{model} é só de leitura desde a migração v2: usa as ações da divisão "
    "(substituir/readicionar jogador), os endpoints /api/v1/divisions e "
    "/api/v1/editions ou `flask create-edition`."
)


def is_compat_model(model_cls):
    table = getattr(model_cls, "__table__", None)
    return table is not None and table.schema == "compat"


def compat_write_message(model_cls):
    return COMPAT_WRITE_MESSAGE.format(model=model_cls.__name__)
